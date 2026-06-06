# backend/router_compat.py
"""
Compatibility / aggregation router.

Registered FIRST in main.py so its paths take priority over parameterised
catch-all routes in the legacy routers.  The canonical conflict that
motivated this: /api/events/day/{date} must win over /api/events/{id}.

This router either:
  · delegates to a legacy router's endpoint function directly (sharing the
    same DB connection injected by Depends), or
  · aggregates multiple queries into a single response shape the frontend
    can consume in one round-trip.

Endpoints
─────────
GET  /api/events/day/{date}   events for one day (recurrence expanded)
GET  /api/tasks/today         active + inbox tasks sorted by priority
GET  /api/journal/today       today's entry (null when not yet created)
GET  /api/today               combined Today-view payload
POST /api/quick-capture       create a task from the capture bar
GET  /api/debug/test          diagnostic: row counts per table
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import List, Optional

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from db import get_db
from helpers import (
    INBOX_ID, UNCATEGORIZED_ID,
    contexts_of, tags_of,
    validate_contexts, resolve_tags,
    set_contexts, set_tags,
    ContextSummary,
)
import service_markdown as md
from service_links import sync_links
from service_priority import compute_priority_score
from model_event   import OccurrenceResponse
from model_task    import (
    TaskResponse, RecurrenceRule,
    TaskCreate, TaskStatus, Importance,
)
from model_journal import JournalResponse
from model_note    import NoteResponse

router = APIRouter(prefix="/api", tags=["compat"])


# ─── response helpers ─────────────────────────────────────────────────────────

_TASK_SEL = """
    SELECT o.id, o.title, o.created_at, o.updated_at,
           t.description, t.status, t.importance, t.time_estimate_min,
           t.due_date, t.recurrence_rule, t.recurrence_anchor, t.parent_task_id
    FROM objects o JOIN tasks t ON t.id = o.id
"""

_JOURNAL_SEL = """
    SELECT o.id, o.title, o.created_at, o.updated_at,
           j.entry_date, j.filepath
    FROM objects o JOIN journal_entries j ON j.id = o.id
"""


async def _priority_weights(db: aiosqlite.Connection) -> dict:
    cur = await db.execute(
        "SELECT urgency_weight, importance_weight, effort_weight, staleness_weight "
        "FROM priority_profiles WHERE is_active = 1 LIMIT 1"
    )
    row = await cur.fetchone()
    return dict(row) if row else {
        "urgency_weight": 0.40, "importance_weight": 0.40,
        "effort_weight":  0.15, "staleness_weight":  0.05,
    }


def _parse_recurrence(raw: Optional[str]) -> Optional[RecurrenceRule]:
    if not raw:
        return None
    try:
        return RecurrenceRule(**json.loads(raw))
    except Exception:
        return None


async def _enrich_task(row, db: aiosqlite.Connection, weights: dict) -> TaskResponse:
    tid = row["id"]
    due = date.fromisoformat(row["due_date"]) if row["due_date"] else None
    updated = datetime.fromisoformat(row["updated_at"]).replace(tzinfo=timezone.utc)

    cur = await db.execute(
        "SELECT COUNT(*) as n FROM tasks WHERE parent_task_id = ?", (tid,)
    )
    subtask_count = (await cur.fetchone())["n"]

    # Pydantic v2 is strict about model identity: helpers.ContextSummary and
    # model_task.ContextSummary are different classes even though they have
    # identical fields.  Converting to dicts lets Pydantic coerce each item
    # into the exact type the response model expects.
    ctx_dicts = [c.model_dump() for c in await contexts_of(tid, db)]
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
        contexts=ctx_dicts,
        tags=await tags_of(tid, db),
        subtask_count=subtask_count,
        priority_score=compute_priority_score(
            importance=row["importance"],
            due_date=due,
            time_estimate_min=row["time_estimate_min"],
            updated_at=updated,
            weights=weights,
        ),
    )


async def _build_journal(row, db: aiosqlite.Connection) -> JournalResponse:
    p = Path(row["filepath"])
    _, content = md.parse(p.read_text(encoding="utf-8") if p.exists() else "")
    # Same dict-coercion fix as _enrich_task — see comment above.
    ctx_dicts = [c.model_dump() for c in await contexts_of(row["id"], db)]
    return JournalResponse(
        id=row["id"],
        entry_date=date.fromisoformat(row["entry_date"]),
        title=row["title"] or None,
        filepath=row["filepath"],
        content=content,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        contexts=ctx_dicts,
        tags=await tags_of(row["id"], db),
        outgoing_links=md.extract_links(content),
    )


# ─── Today-view combined payload ──────────────────────────────────────────────

class TodayView(BaseModel):
    date:    str
    events:  List[OccurrenceResponse]
    tasks:   List[TaskResponse]
    journal: Optional[JournalResponse] = None


# ─── /api/events/day/{date} ──────────────────────────────────────────────────

@router.get("/events/day/{day}", response_model=List[OccurrenceResponse])
async def events_for_day(
    day: str,
    context_id: Optional[str] = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    """
    Events for a single day, with recurrence expansion applied.
    This route must be registered before /api/events so that 'day' is not
    mistaken for an event UUID.
    """
    try:
        d = date.fromisoformat(day)
    except ValueError:
        raise HTTPException(400, detail=f"Invalid date: {day!r}. Use YYYY-MM-DD.")

    # Reuse the range-query logic from the events router
    from router_events import list_events
    return await list_events(start=d, end=d, context_id=context_id, db=db)


# ─── /api/tasks/today ────────────────────────────────────────────────────────

@router.get("/tasks/today", response_model=List[TaskResponse])
async def tasks_today(
    context_id: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    db: aiosqlite.Connection = Depends(get_db),
):
    """
    Inbox + active tasks sorted by priority score.
    Registered before /api/tasks so that 'today' is not treated as a UUID.
    """
    where = ["t.status IN ('inbox','active')", "t.parent_task_id IS NULL"]
    params: list = []
    if context_id:
        where.append(
            "o.id IN (SELECT object_id FROM object_contexts WHERE context_id = ?)"
        )
        params.append(context_id)
    # Fetch up to 500 matching tasks, score all, sort, then slice.
    # This avoids the "priority sort after SQL LIMIT" problem where the LIMIT
    # cuts off high-priority older tasks before scores are computed.
    params.append(500)

    cur = await db.execute(
        f"{_TASK_SEL} WHERE {' AND '.join(where)} ORDER BY o.created_at DESC LIMIT ?",
        params,
    )
    rows = await cur.fetchall()
    weights = await _priority_weights(db)
    tasks = [await _enrich_task(r, db, weights) for r in rows]
    tasks.sort(key=lambda t: t.priority_score or 0.0, reverse=True)
    return tasks[:limit]


# ─── /api/journal/today ──────────────────────────────────────────────────────

@router.get("/journal/today", response_model=Optional[JournalResponse])
async def journal_today(db: aiosqlite.Connection = Depends(get_db)):
    """
    Today's journal entry, or null if one hasn't been created yet.
    Registered before /api/journal so that 'today' isn't treated as a UUID.
    """
    today = datetime.now(timezone.utc).date().isoformat()
    cur = await db.execute(
        _JOURNAL_SEL + "WHERE j.entry_date = ?", (today,)
    )
    row = await cur.fetchone()
    if not row:
        return None
    return await _build_journal(row, db)


# ─── /api/today ──────────────────────────────────────────────────────────────

@router.get("/today", response_model=TodayView)
async def today_view(
    context_id: Optional[str] = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    """Combined payload for the Today view (single round-trip)."""
    today = datetime.now(timezone.utc).date()

    events  = await events_for_day(today.isoformat(), context_id=context_id, db=db)
    tasks   = await tasks_today(context_id=context_id, limit=20, db=db)
    journal = await journal_today(db=db)

    return TodayView(
        date=today.isoformat(),
        events=events,
        tasks=tasks,
        journal=journal,
    )


# ─── /api/quick-capture ──────────────────────────────────────────────────────

_CONTEXT_RE = re.compile(r"@([\w.]+)")


class QuickCapture(BaseModel):
    text: str   # e.g. "Call dentist @personal" or "Review PR @work.projectalpha"


class QuickCaptureResult(BaseModel):
    task_id:     str
    title:       str
    context_ids: List[str]


@router.post(
    "/quick-capture",
    response_model=QuickCaptureResult,
    status_code=status.HTTP_201_CREATED,
)
async def quick_capture(
    payload: QuickCapture,
    db: aiosqlite.Connection = Depends(get_db),
):
    """
    Parse a raw capture string and create a task.

    @mention resolution is case-insensitive and dot-notation aware:
      "Review PR @work.projectalpha"  →  context whose name is "work.projectalpha"
    Unknown mentions are silently dropped; task falls back to Inbox.
    """
    text = payload.text.strip()
    if not text:
        raise HTTPException(400, detail="Capture text must not be empty.")

    mentions = _CONTEXT_RE.findall(text)
    title = _CONTEXT_RE.sub("", text).strip()
    if not title:
        raise HTTPException(400, detail="Title is empty after stripping context mentions.")

    # Global title uniqueness check
    cur = await db.execute("SELECT id FROM objects WHERE title = ?", (title,))
    if await cur.fetchone():
        raise HTTPException(409, detail=f"Title already in use: '{title}'")

    # Resolve mentions to context IDs (case-insensitive)
    ctx_ids: List[str] = []
    for mention in mentions:
        cur = await db.execute(
            "SELECT id FROM contexts WHERE name = ? COLLATE NOCASE", (mention,)
        )
        row = await cur.fetchone()
        if row:
            ctx_ids.append(row["id"])

    if not ctx_ids:
        ctx_ids = [INBOX_ID]

    tid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    tag_ids = await resolve_tags([], db)  # quick-capture carries no tags
    validated_ctx_ids = await validate_contexts(ctx_ids, db, default_ctx=INBOX_ID)

    try:
        await db.execute(
            "INSERT INTO objects (id, title, type, date, created_at, updated_at) "
            "VALUES (?, ?, 'task', NULL, ?, ?)",
            (tid, title, now, now),
        )
        await db.execute(
            "INSERT INTO tasks (id, status, importance) VALUES (?, 'inbox', 'normal')",
            (tid,),
        )
        await set_contexts(tid, validated_ctx_ids, db)
        await set_tags(tid, tag_ids, db)
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return QuickCaptureResult(task_id=tid, title=title, context_ids=validated_ctx_ids)


# ─── /api/debug/test ─────────────────────────────────────────────────────────

@router.get("/debug/test")
async def debug_test(db: aiosqlite.Connection = Depends(get_db)):
    """Diagnostic: row counts and column names for every table."""
    tables = [
        "objects", "tasks", "events", "notes", "journal_entries",
        "contexts", "tags", "object_contexts", "object_tags",
        "links", "priority_profiles",
    ]
    result: dict = {}
    for table in tables:
        try:
            cur = await db.execute(f"SELECT COUNT(*) AS n FROM {table}")
            count = (await cur.fetchone())["n"]
            cur = await db.execute(f"PRAGMA table_info({table})")
            cols = [r["name"] for r in await cur.fetchall()]
            result[table] = {"rows": count, "columns": cols}
        except Exception as exc:
            result[table] = {"error": str(exc)}
    return result
