"""routers/events.py"""
import uuid as _uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException

from db import db
from db_utils import sync_tags, sync_fts
from models import EventCreate, EventUpdate

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("")
def list_events(
    start: Optional[str] = None,
    end: Optional[str] = None,
    context_id: Optional[int] = None,
):
    with db() as conn:
        clauses, params = [], []
        if start:
            # Event overlaps the range if it hasn't ended before `start`.
            clauses.append("date(COALESCE(e.end_at, e.start_at)) >= date(?)")
            params.append(start)
        if end:
            clauses.append("e.start_at <= ?"); params.append(end)
        if context_id:
            clauses.append("e.context_id = ?"); params.append(context_id)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(
            f"""SELECT e.*, c.full_path AS context_path, c.color AS context_color
                FROM events e LEFT JOIN contexts c ON e.context_id = c.id
                {where} ORDER BY e.start_at ASC""",
            params,
        ).fetchall()
        return [dict(r) for r in rows]


@router.post("")
def create_event(data: EventCreate):
    uid = str(_uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        conn.execute(
            """INSERT INTO events
               (uuid,title,description,context_id,start_at,end_at,all_day,
                recurrence,location,root_uuid,created_at,modified_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (uid, data.title, data.description, data.context_id,
             data.start_at, data.end_at, int(data.all_day),
             data.recurrence, data.location, uid, now, now),
        )
        sync_tags(conn, uid, "event", data.description)
        sync_fts(conn, uid, "event", data.title, data.description)
        return dict(conn.execute("SELECT * FROM events WHERE uuid = ?", (uid,)).fetchone())


@router.get("/{event_uuid}")
def get_event(event_uuid: str):
    with db() as conn:
        row = conn.execute(
            """SELECT e.*, c.full_path AS context_path, c.color AS context_color
               FROM events e LEFT JOIN contexts c ON e.context_id = c.id
               WHERE e.uuid = ?""",
            (event_uuid,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Event not found")
        return dict(row)


@router.put("/{event_uuid}")
def update_event(event_uuid: str, data: EventUpdate):
    with db() as conn:
        existing = conn.execute("SELECT * FROM events WHERE uuid = ?", (event_uuid,)).fetchone()
        if not existing:
            raise HTTPException(404, "Event not found")
        now = datetime.now(timezone.utc).isoformat()
        updates = data.model_dump(exclude_none=True)
        if not updates:
            return dict(existing)
        if "all_day" in updates:
            updates["all_day"] = int(updates["all_day"])
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(
            f"UPDATE events SET {set_clause}, modified_at = ? WHERE uuid = ?",
            list(updates.values()) + [now, event_uuid],
        )
        if "description" in updates:
            sync_tags(conn, event_uuid, "event", updates["description"])
        if "title" in updates or "description" in updates:
            sync_fts(conn, event_uuid, "event",
                     updates.get("title", existing["title"]),
                     updates.get("description", existing["description"]))
        return dict(conn.execute("SELECT * FROM events WHERE uuid = ?", (event_uuid,)).fetchone())


@router.delete("/{event_uuid}")
def delete_event(event_uuid: str):
    with db() as conn:
        if not conn.execute("SELECT uuid FROM events WHERE uuid = ?", (event_uuid,)).fetchone():
            raise HTTPException(404, "Event not found")
        conn.execute("DELETE FROM events WHERE uuid = ?", (event_uuid,))
        conn.execute("DELETE FROM object_tags WHERE object_uuid = ?", (event_uuid,))
        conn.execute("DELETE FROM search_index WHERE uuid = ?", (event_uuid,))
        return {"deleted": event_uuid}
