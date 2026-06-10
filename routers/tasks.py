"""routers/tasks.py"""
import uuid as _uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException

from db import db
from db_utils import sync_tags, sync_fts
from models import TaskCreate, TaskUpdate
from priority import compute_priority_score

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _recompute(conn, task_uuid: str):
    row = conn.execute("SELECT * FROM tasks WHERE uuid = ?", (task_uuid,)).fetchone()
    if not row:
        return
    score = compute_priority_score(
        status=row["status"],
        importance=row["importance"],
        effort=row["effort"],
        user_urgency=row["user_urgency"],
        due_at=row["due_at"],
        created_at=row["created_at"],
        last_active_at=row["last_active_at"],
        defer_count=row["defer_count"],
    )
    conn.execute("UPDATE tasks SET priority_score = ? WHERE uuid = ?", (score, task_uuid))


@router.get("")
def list_tasks(
    status: Optional[str] = None,
    context_id: Optional[int] = None,
    importance: Optional[str] = None,
    effort: Optional[str] = None,
    sort: str = "priority",
    limit: int = 200,
    offset: int = 0,
):
    with db() as conn:
        clauses, params = [], []

        if status:
            clauses.append("t.status = ?"); params.append(status)
        else:
            clauses.append("t.status != 'done'")

        if context_id:
            clauses.append("t.context_id = ?"); params.append(context_id)
        if importance:
            clauses.append("t.importance = ?"); params.append(importance)
        if effort:
            clauses.append("t.effort = ?"); params.append(effort)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        order = {
            "priority":   "t.priority_score DESC",
            "due":        "t.due_at ASC NULLS LAST",
            "created":    "t.created_at DESC",
            "importance": "CASE t.importance WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END",
            "title":      "t.title COLLATE NOCASE",
        }.get(sort, "t.priority_score DESC")

        rows = conn.execute(
            f"""SELECT t.*, c.full_path AS context_path, c.color AS context_color
                FROM tasks t LEFT JOIN contexts c ON t.context_id = c.id
                {where} ORDER BY {order} LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()
        return [dict(r) for r in rows]


@router.post("")
def create_task(data: TaskCreate):
    uid = str(_uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        conn.execute(
            """INSERT INTO tasks
               (uuid,title,description,context_id,status,importance,effort,
                user_urgency,due_at,scheduled_at,recurrence,recurrence_type,
                parent_uuid,root_uuid,location,priority_score,created_at,modified_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)""",
            (uid, data.title, data.description, data.context_id,
             data.status, data.importance, data.effort, data.user_urgency,
             data.due_at, data.scheduled_at, data.recurrence, data.recurrence_type,
             data.parent_uuid, data.parent_uuid or uid,
             data.location, now, now),
        )
        _recompute(conn, uid)
        sync_tags(conn, uid, "task", data.description)
        sync_fts(conn, uid, "task", data.title, data.description)
        return dict(conn.execute("SELECT * FROM tasks WHERE uuid = ?", (uid,)).fetchone())


@router.get("/day/{date_str}")
def tasks_for_day(
    date_str: str,
    effort: Optional[str] = None,
    context_id: Optional[int] = None,
    limit: int = 30,
):
    with db() as conn:
        clauses = ["t.status NOT IN ('done','someday')"]
        params: list = []
        if effort:
            clauses.append("t.effort = ?"); params.append(effort)
        if context_id:
            clauses.append("t.context_id = ?"); params.append(context_id)
        clauses.append(
            "(t.due_at IS NULL OR date(t.due_at) <= ? OR date(t.scheduled_at) = ?)"
        )
        params += [date_str, date_str]
        rows = conn.execute(
            f"""SELECT t.*, c.full_path AS context_path, c.color AS context_color
                FROM tasks t LEFT JOIN contexts c ON t.context_id = c.id
                WHERE {' AND '.join(clauses)}
                ORDER BY t.priority_score DESC LIMIT ?""",
            params + [limit],
        ).fetchall()
        return [dict(r) for r in rows]


@router.get("/{task_uuid}")
def get_task(task_uuid: str):
    with db() as conn:
        row = conn.execute(
            """SELECT t.*, c.full_path AS context_path, c.color AS context_color
               FROM tasks t LEFT JOIN contexts c ON t.context_id = c.id
               WHERE t.uuid = ?""",
            (task_uuid,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Task not found")
        return dict(row)


@router.put("/{task_uuid}")
def update_task(task_uuid: str, data: TaskUpdate):
    with db() as conn:
        existing = conn.execute("SELECT * FROM tasks WHERE uuid = ?", (task_uuid,)).fetchone()
        if not existing:
            raise HTTPException(404, "Task not found")
        now = datetime.now(timezone.utc).isoformat()
        updates = data.model_dump(exclude_none=True)
        if not updates:
            return dict(existing)
        if updates.get("status") == "active" and existing["status"] != "active":
            updates["last_active_at"] = now
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(
            f"UPDATE tasks SET {set_clause}, modified_at = ? WHERE uuid = ?",
            list(updates.values()) + [now, task_uuid],
        )
        _recompute(conn, task_uuid)
        if "description" in updates:
            sync_tags(conn, task_uuid, "task", updates["description"])
            sync_fts(conn, task_uuid, "task",
                     updates.get("title", existing["title"]),
                     updates["description"])
        elif "title" in updates:
            sync_fts(conn, task_uuid, "task", updates["title"], existing["description"])
        return dict(conn.execute("SELECT * FROM tasks WHERE uuid = ?", (task_uuid,)).fetchone())


@router.delete("/{task_uuid}")
def delete_task(task_uuid: str):
    with db() as conn:
        if not conn.execute("SELECT uuid FROM tasks WHERE uuid = ?", (task_uuid,)).fetchone():
            raise HTTPException(404, "Task not found")
        conn.execute("DELETE FROM tasks WHERE uuid = ?", (task_uuid,))
        conn.execute("DELETE FROM object_tags WHERE object_uuid = ?", (task_uuid,))
        conn.execute("DELETE FROM links WHERE source_uuid = ?", (task_uuid,))
        conn.execute("DELETE FROM search_index WHERE uuid = ?", (task_uuid,))
        return {"deleted": task_uuid}
