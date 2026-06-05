"""
Task routes.

  GET    /api/tasks                   list (filters: status, context_id, tag; sort: priority|due_date|importance|created_at|title)
  POST   /api/tasks                   create
  GET    /api/tasks/{id}              detail
  PATCH  /api/tasks/{id}             partial update
  DELETE /api/tasks/{id}             delete (subtasks become top-level via ON DELETE SET NULL)
  GET    /api/tasks/{id}/subtasks    direct children
"""

from __future__ import annotations

import json
import uuid
from datetime import date as date_type, datetime, timezone
from typing import List, Optional

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, status

from db import get_db
from model_task import (
    ContextSummary, RecurrenceRule,
    TaskCreate, TaskResponse, TaskUpdate,
)
from service_priority import compute_priority_score
from service_links import sync_links, propagate_rename

router = APIRouter(prefix="/tasks", tags=["tasks"])

_INBOX_ID = "ctx-inbox"

# Reusable SELECT that joins objects + tasks
_SEL = """
    SELECT o.id, o.title, o.created_at, o.updated_at,
           t.description, t.status, t.importance, t.time_estimate_min,
           t.due_date, t.recurrence_rule, t.recurrence_anchor, t.parent_task_id
    FROM objects o
    JOIN tasks t ON t.id = o.id
"""

# ─── private helpers ─────────────────────────────────────────────────────────

async def _weights(db: aiosqlite.Connection) -> dict:
    cur = await db.execute(
        "SELECT urgency_weight, importance_weight, effort_weight, staleness_weight "
        "FROM priority_profiles WHERE is_active = 1 LIMIT 1"
    )
    row = await cur.fetchone()
    return dict(row) if row else {
        "urgency_weight": 0.40, "importance_weight": 0.40,
        "effort_weight":  0.15, "staleness_weight":  0.05,
    }


async def _fetch_row(task_id: str, db: aiosqlite.Connection) -> aiosqlite.Row:
    cur = await db.execute(_SEL + "WHERE o.id = ?", (task_id,))
    row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return row


async def _contexts_of(task_id: str, db: aiosqlite.Connection) -> List[ContextSummary]:
    cur = await db.execute(
        "SELECT c.id, c.name, c.color FROM contexts c "
        "JOIN object_contexts oc ON oc.context_id = c.id WHERE oc.object_id = ?",
        (task_id,)
    )
    return [ContextSummary(id=r["id"], name=r["name"], color=r["color"])
            for r in await cur.fetchall()]


async def _tags_of(task_id: str, db: aiosqlite.Connection) -> List[str]:
    cur = await db.execute(
        "SELECT tg.name FROM tags tg "
        "JOIN object_tags ot ON ot.tag_id = tg.id WHERE ot.object_id = ?",
        (task_id,)
    )
    return [r["name"] for r in await cur.fetchall()]


async def _subtask_count(task_id: str, db: aiosqlite.Connection) -> int:
    cur = await db.execute(
        "SELECT COUNT(*) as n FROM tasks WHERE parent_task_id = ?", (task_id,)
    )
    row = await cur.fetchone()
    return row["n"] if row else 0


def _parse_recurrence(raw: Optional[str]) -> Optional[RecurrenceRule]:
    if not raw:
        return None
    try:
        return RecurrenceRule(**json.loads(raw))
    except Exception:
        return None


async def _enrich(row: aiosqlite.Row, db: aiosqlite.Connection, w: dict) -> TaskResponse:
    tid = row["id"]
    due = date_type.fromisoformat(row["due_date"]) if row["due_date"] else None
    updated = datetime.fromisoformat(row["updated_at"]).replace(tzinfo=timezone.utc)

    return TaskResponse(
        id=tid,
        title=row["title"],
        description=row["description"],
        status=row["status"],
        importance=row["importance"],
        time_estimate_min=row["time_estimate_min"],
        due_date=due,
        recurrence_rule=_parse_recurrence(row["recurrence_rule"]),
        parent_task_id=row["parent_task_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        contexts=await _contexts_of(tid, db),
        tags=await _tags_of(tid, db),
        subtask_count=await _subtask_count(tid, db),
        priority_score=compute_priority_score(
            importance=row["importance"],
            due_date=due,
            time_estimate_min=row["time_estimate_min"],
            updated_at=updated,
            weights=w,
        ),
    )


async def _validate_contexts(ctx_ids: List[str], db: aiosqlite.Connection) -> List[str]:
    """Validate IDs exist; default to Inbox when list is empty."""
    if not ctx_ids:
        return [_INBOX_ID]
    ph = ",".join("?" * len(ctx_ids))
    cur = await db.execute(f"SELECT id FROM contexts WHERE id IN ({ph})", ctx_ids)
    found = {r["id"] for r in await cur.fetchall()}
    missing = set(ctx_ids) - found
    if missing:
        raise HTTPException(422, detail=f"Unknown context IDs: {sorted(missing)}")
    return ctx_ids


async def _resolve_tags(names: List[str], db: aiosqlite.Connection) -> List[str]:
    """Get or create tags (case-folded); return UUIDs."""
    ids: List[str] = []
    for raw in names:
        name = raw.strip().lower()
        if not name:
            continue
        cur = await db.execute("SELECT id FROM tags WHERE name = ?", (name,))
        row = await cur.fetchone()
        if row:
            ids.append(row["id"])
        else:
            tid = str(uuid.uuid4())
            await db.execute("INSERT INTO tags (id, name) VALUES (?, ?)", (tid, name))
            ids.append(tid)
    return ids


async def _set_contexts(task_id: str, ctx_ids: List[str], db: aiosqlite.Connection) -> None:
    await db.execute("DELETE FROM object_contexts WHERE object_id = ?", (task_id,))
    for cid in ctx_ids:
        await db.execute(
            "INSERT OR IGNORE INTO object_contexts (object_id, context_id) VALUES (?, ?)",
            (task_id, cid)
        )


async def _set_tags(task_id: str, tag_ids: List[str], db: aiosqlite.Connection) -> None:
    await db.execute("DELETE FROM object_tags WHERE object_id = ?", (task_id,))
    for tid in tag_ids:
        await db.execute(
            "INSERT OR IGNORE INTO object_tags (object_id, tag_id) VALUES (?, ?)",
            (task_id, tid)
        )


# ─── routes ──────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[TaskResponse])
async def list_tasks(
    status: Optional[str] = Query(
        None, enum=["inbox", "active", "done", "deferred", "someday"]),
    context_id: Optional[str] = None,
    tag: Optional[str] = None,
    sort_by: str = Query(
        "priority",
        enum=["priority", "due_date", "importance", "created_at", "title"]),
    include_subtasks: bool = False,
    limit: int = Query(50, ge=1, le=200),
    db: aiosqlite.Connection = Depends(get_db),
):
    where, params = ["1=1"], []

    if status:
        where.append("t.status = ?"); params.append(status)
    if not include_subtasks:
        where.append("t.parent_task_id IS NULL")
    if context_id:
        where.append(
            "o.id IN (SELECT object_id FROM object_contexts WHERE context_id = ?)"
        )
        params.append(context_id)
    if tag:
        where.append(
            "o.id IN (SELECT ot.object_id FROM object_tags ot "
            "JOIN tags tg ON tg.id = ot.tag_id WHERE tg.name = ?)"
        )
        params.append(tag.strip().lower())

    sql_order = {
        "due_date":   "t.due_date ASC NULLS LAST",
        "importance": ("CASE t.importance WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
                       "WHEN 'normal' THEN 2 ELSE 3 END"),
        "created_at": "o.created_at DESC",
        "title":      "o.title ASC",
    }
    order = sql_order.get(sort_by, "o.created_at DESC")
    params.append(limit)

    cur = await db.execute(
        f"{_SEL} WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ?", params
    )
    rows = await cur.fetchall()
    w = await _weights(db)
    tasks = [await _enrich(r, db, w) for r in rows]

    if sort_by == "priority":
        tasks.sort(key=lambda t: t.priority_score or 0.0, reverse=True)

    return tasks


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str, db: aiosqlite.Connection = Depends(get_db)):
    return await _enrich(await _fetch_row(task_id, db), db, await _weights(db))


@router.post("/", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(payload: TaskCreate, db: aiosqlite.Connection = Depends(get_db)):
    # Global title uniqueness
    cur = await db.execute("SELECT id FROM objects WHERE title = ?", (payload.title,))
    if await cur.fetchone():
        raise HTTPException(409, detail=f"Title already in use: '{payload.title}'")

    if payload.parent_task_id:
        cur = await db.execute("SELECT id FROM tasks WHERE id = ?", (payload.parent_task_id,))
        if not await cur.fetchone():
            raise HTTPException(422, detail="parent_task_id not found")

    ctx_ids = await _validate_contexts(payload.context_ids, db)
    tag_ids = await _resolve_tags(payload.tag_names, db)

    tid     = str(uuid.uuid4())
    now     = datetime.now(timezone.utc).isoformat()
    due_str = payload.due_date.isoformat() if payload.due_date else None
    rec_json = (
        json.dumps(payload.recurrence_rule.model_dump())
        if payload.recurrence_rule else None
    )

    try:
        await db.execute(
            "INSERT INTO objects (id, title, type, date, created_at, updated_at) "
            "VALUES (?, ?, 'task', ?, ?, ?)",
            (tid, payload.title, due_str, now, now)
        )
        await db.execute(
            "INSERT INTO tasks "
            "(id, description, status, importance, time_estimate_min, "
            " due_date, recurrence_rule, parent_task_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (tid, payload.description, payload.status.value,
             payload.importance.value, payload.time_estimate_min,
             due_str, rec_json, payload.parent_task_id)
        )
        await _set_contexts(tid, ctx_ids, db)
        await _set_tags(tid, tag_ids, db)
        await sync_links(tid, payload.description or "", db)
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return await _enrich(await _fetch_row(tid, db), db, await _weights(db))


@router.patch("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: str,
    payload: TaskUpdate,
    db: aiosqlite.Connection = Depends(get_db),
):
    await _fetch_row(task_id, db)  # 404 guard

    updates = payload.model_dump(exclude_none=True)
    if not updates:
        return await _enrich(await _fetch_row(task_id, db), db, await _weights(db))

    _obj_cols  = {"title"}
    _task_cols = {"description", "status", "importance", "time_estimate_min",
                  "due_date", "recurrence_rule", "parent_task_id"}

    obj_up  = {k: v for k, v in updates.items() if k in _obj_cols}
    task_up = {k: v for k, v in updates.items() if k in _task_cols}

    if "title" in obj_up:
        cur = await db.execute(
            "SELECT id FROM objects WHERE title = ? AND id != ?",
            (obj_up["title"], task_id)
        )
        if await cur.fetchone():
            raise HTTPException(409, detail=f"Title already in use: '{obj_up['title']}'")

    # Serialise enums + special types before hitting SQLite
    for key in ("status", "importance"):
        if key in task_up and hasattr(task_up[key], "value"):
            task_up[key] = task_up[key].value
    if "due_date" in task_up and task_up["due_date"] is not None:
        task_up["due_date"] = task_up["due_date"].isoformat()
    if "recurrence_rule" in task_up:
        rule = task_up["recurrence_rule"]
        task_up["recurrence_rule"] = json.dumps(rule.model_dump()) if rule else None

    # Capture the old title BEFORE the UPDATE so rename propagation has the
    # right source string.  Reading it after the UPDATE always returns the
    # new title, which means the condition old != new is always False.
    old_title: Optional[str] = None
    if "title" in obj_up:
        cur2 = await db.execute("SELECT title FROM objects WHERE id = ?", (task_id,))
        old_row = await cur2.fetchone()
        old_title = old_row["title"] if old_row else None

    try:
        if obj_up:
            cols = ", ".join(f"{k} = ?" for k in obj_up)
            await db.execute(
                f"UPDATE objects SET {cols} WHERE id = ?",
                (*obj_up.values(), task_id)
            )
        if task_up:
            cols = ", ".join(f"{k} = ?" for k in task_up)
            await db.execute(
                f"UPDATE tasks SET {cols} WHERE id = ?",
                (*task_up.values(), task_id)
            )
        if payload.context_ids is not None:
            ctx_ids = await _validate_contexts(payload.context_ids, db)
            await _set_contexts(task_id, ctx_ids, db)
        if payload.tag_names is not None:
            tag_ids = await _resolve_tags(payload.tag_names, db)
            await _set_tags(task_id, tag_ids, db)
        # Propagate rename now that the new title is committed
        if old_title is not None and old_title != obj_up.get("title"):
            await propagate_rename(task_id, old_title, obj_up["title"], db)
        desc = task_up.get("description") if task_up else None
        if desc is not None:
            await sync_links(task_id, desc, db)
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return await _enrich(await _fetch_row(task_id, db), db, await _weights(db))


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: str, db: aiosqlite.Connection = Depends(get_db)):
    await _fetch_row(task_id, db)  # 404 guard
    # Cascades: objects → tasks, object_contexts, object_tags (ON DELETE CASCADE)
    # Subtasks' parent_task_id → NULL (ON DELETE SET NULL) — they become top-level
    await db.execute("DELETE FROM objects WHERE id = ?", (task_id,))
    await db.commit()


@router.get("/{task_id}/subtasks", response_model=List[TaskResponse])
async def list_subtasks(task_id: str, db: aiosqlite.Connection = Depends(get_db)):
    await _fetch_row(task_id, db)  # 404 guard
    cur = await db.execute(
        _SEL + "WHERE t.parent_task_id = ? ORDER BY o.created_at ASC", (task_id,)
    )
    rows = await cur.fetchall()
    w = await _weights(db)
    return [await _enrich(r, db, w) for r in rows]
