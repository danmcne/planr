"""
Event routes.

  GET    /api/events?start=&end=                         occurrences in date range
  POST   /api/events                                     create event (+ optional rrule)
  GET    /api/events/{id}                                get single event or occurrence
  PATCH  /api/events/{id}?edit_mode=this|future|all     update
  DELETE /api/events/{id}?edit_mode=this|future|all     delete

Virtual occurrence IDs look like  "{master_uuid}::{YYYY-MM-DD}".
Real stored rows use plain UUIDs.

Edit modes:
  this   → create/update a stored override for this one slot
  future → truncate master series, spawn new master from this date onward
  all    → update the master directly, wipe all stored children
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

import aiosqlite
from dateutil import rrule as rrulelib
from fastapi import APIRouter, Depends, HTTPException, Query, status

from db import get_db
from model_event import (
    ContextSummary, EditMode, EventCreate, EventStatus,
    EventUpdate, OccurrenceResponse,
)
from service_recurrence import expand_master, parse_virtual_id, _dt, _date
from service_links import sync_links, propagate_rename

router = APIRouter(prefix="/events", tags=["events"])

_INBOX_ID = "ctx-inbox"

_SEL = """
    SELECT o.id, o.title, o.created_at, o.updated_at,
           e.start_datetime, e.end_datetime, e.all_day, e.location,
           e.description, e.status, e.rrule, e.rrule_until,
           e.parent_event_id, e.root_event_id, e.original_date
    FROM objects o JOIN events e ON e.id = o.id
"""


# ─── shared helpers (duplicated from tasks; will refactor in a later phase) ──

async def _contexts_of(eid: str, db: aiosqlite.Connection) -> List[ContextSummary]:
    cur = await db.execute(
        "SELECT c.id, c.name, c.color FROM contexts c "
        "JOIN object_contexts oc ON oc.context_id = c.id WHERE oc.object_id = ?", (eid,)
    )
    return [ContextSummary(id=r["id"], name=r["name"], color=r["color"])
            for r in await cur.fetchall()]


async def _tags_of(eid: str, db: aiosqlite.Connection) -> List[str]:
    cur = await db.execute(
        "SELECT tg.name FROM tags tg "
        "JOIN object_tags ot ON ot.tag_id = tg.id WHERE ot.object_id = ?", (eid,)
    )
    return [r["name"] for r in await cur.fetchall()]


async def _validate_contexts(ctx_ids: List[str], db: aiosqlite.Connection) -> List[str]:
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


async def _set_contexts(eid: str, ctx_ids: List[str], db: aiosqlite.Connection) -> None:
    await db.execute("DELETE FROM object_contexts WHERE object_id = ?", (eid,))
    for cid in ctx_ids:
        await db.execute(
            "INSERT OR IGNORE INTO object_contexts (object_id, context_id) VALUES (?, ?)",
            (eid, cid)
        )


async def _set_tags(eid: str, tag_ids: List[str], db: aiosqlite.Connection) -> None:
    await db.execute("DELETE FROM object_tags WHERE object_id = ?", (eid,))
    for tid in tag_ids:
        await db.execute(
            "INSERT OR IGNORE INTO object_tags (object_id, tag_id) VALUES (?, ?)",
            (eid, tid)
        )


async def _fetch_row(event_id: str, db: aiosqlite.Connection) -> aiosqlite.Row:
    cur = await db.execute(_SEL + "WHERE o.id = ?", (event_id,))
    row = await cur.fetchone()
    if not row:
        raise HTTPException(404, detail="Event not found")
    return row


def _row_to_response(row, contexts, tags) -> OccurrenceResponse:
    start_dt = _dt(row["start_datetime"])
    end_dt   = _dt(row["end_datetime"])
    return OccurrenceResponse(
        id              = row["id"],
        title           = row["title"],
        start_datetime  = start_dt,
        end_datetime    = end_dt,
        all_day         = bool(row["all_day"]),
        location        = row["location"],
        description     = row["description"],
        status          = row["status"],
        rrule           = row["rrule"],
        rrule_until     = _date(row["rrule_until"]),
        is_recurring    = bool(row["rrule"]),
        is_override     = bool(row["parent_event_id"]),
        is_virtual      = False,
        parent_event_id = row["parent_event_id"],
        root_event_id   = row["root_event_id"],
        original_date   = _date(row["original_date"]),
        created_at      = row["created_at"],
        updated_at      = row["updated_at"],
        contexts        = contexts,
        tags            = tags,
    )


def _validate_rrule(rrule: str, dtstart: datetime) -> None:
    try:
        rrulelib.rrulestr(rrule, dtstart=dtstart, ignoretz=False)
    except Exception as exc:
        raise HTTPException(422, detail=f"Invalid RRULE: {exc}")


# ─── routes ──────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[OccurrenceResponse])
async def list_events(
    start: date = Query(..., description="Range start YYYY-MM-DD"),
    end:   date = Query(..., description="Range end YYYY-MM-DD (inclusive)"),
    context_id: Optional[str] = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    start_iso, end_iso = start.isoformat(), end.isoformat()

    # Fetch masters: non-recurring in range, OR recurring with overlap
    cur = await db.execute(
        _SEL + """
        WHERE e.parent_event_id IS NULL
        AND (
            (e.rrule IS NULL AND date(e.start_datetime) BETWEEN ? AND ?)
            OR
            (e.rrule IS NOT NULL
             AND date(e.start_datetime) <= ?
             AND (e.rrule_until IS NULL OR e.rrule_until >= ?))
        )""",
        (start_iso, end_iso, end_iso, start_iso)
    )
    master_rows = [dict(r) for r in await cur.fetchall()]

    if not master_rows:
        return []

    master_ids = [r["id"] for r in master_rows]

    # Fetch stored overrides for these masters in this range
    ph = ",".join("?" * len(master_ids))
    cur = await db.execute(
        _SEL + f"""
        WHERE e.root_event_id IN ({ph})
        AND e.original_date BETWEEN ? AND ?""",
        (*master_ids, start_iso, end_iso)
    )
    # Build override index: {master_id: {original_date: row}}
    override_map: dict[str, dict[str, dict]] = {}
    for ov in await cur.fetchall():
        ov = dict(ov)
        override_map.setdefault(ov["root_event_id"], {})[ov["original_date"]] = ov

    results: List[OccurrenceResponse] = []

    for master in master_rows:
        # Optional context filter (applies to master; overrides inherit)
        if context_id:
            cur2 = await db.execute(
                "SELECT 1 FROM object_contexts WHERE object_id = ? AND context_id = ?",
                (master["id"], context_id)
            )
            if not await cur2.fetchone():
                continue

        contexts = await _contexts_of(master["id"], db)
        tags     = await _tags_of(master["id"], db)
        overrides = override_map.get(master["id"], {})

        results.extend(expand_master(master, start, end, overrides, contexts, tags))

    results.sort(key=lambda r: r.start_datetime)
    return results


@router.post("/", response_model=OccurrenceResponse, status_code=status.HTTP_201_CREATED)
async def create_event(payload: EventCreate, db: aiosqlite.Connection = Depends(get_db)):
    cur = await db.execute("SELECT id FROM objects WHERE title = ?", (payload.title,))
    if await cur.fetchone():
        raise HTTPException(409, detail=f"Title already in use: '{payload.title}'")

    start_dt = payload.start_datetime
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)

    if payload.rrule:
        _validate_rrule(payload.rrule, start_dt)

    ctx_ids = await _validate_contexts(payload.context_ids, db)
    tag_ids = await _resolve_tags(payload.tag_names, db)

    end_dt = payload.end_datetime
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=timezone.utc)

    eid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    try:
        await db.execute(
            "INSERT INTO objects (id, title, type, date, created_at, updated_at) "
            "VALUES (?, ?, 'event', ?, ?, ?)",
            (eid, payload.title, start_dt.date().isoformat(), now, now)
        )
        await db.execute(
            "INSERT INTO events "
            "(id, start_datetime, end_datetime, all_day, location, description, status, rrule) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (eid, start_dt.isoformat(), end_dt.isoformat(), int(payload.all_day),
             payload.location, payload.description, payload.status.value, payload.rrule)
        )
        await _set_contexts(eid, ctx_ids, db)
        await _set_tags(eid, tag_ids, db)
        await sync_links(eid, payload.description or "", db)
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    row = await _fetch_row(eid, db)
    return _row_to_response(row, await _contexts_of(eid, db), await _tags_of(eid, db))


@router.get("/{event_id}", response_model=OccurrenceResponse)
async def get_event(event_id: str, db: aiosqlite.Connection = Depends(get_db)):
    master_id, original_date = parse_virtual_id(event_id)
    row = await _fetch_row(master_id, db)
    contexts = await _contexts_of(master_id, db)
    tags     = await _tags_of(master_id, db)

    if original_date is None:
        return _row_to_response(row, contexts, tags)

    # Virtual occurrence — return master data shifted to requested date
    from service_recurrence import _shift, _virtual
    start_dt = _dt(row["start_datetime"])
    end_dt   = _dt(row["end_datetime"])
    v_start, v_end = _shift(start_dt, end_dt, original_date)
    return _virtual(dict(row), original_date, v_start, v_end, contexts, tags)


@router.patch("/{event_id}", response_model=OccurrenceResponse)
async def update_event(
    event_id: str,
    payload: EventUpdate,
    edit_mode: EditMode = Query(EditMode.this),
    db: aiosqlite.Connection = Depends(get_db),
):
    master_id, original_date = parse_virtual_id(event_id)
    master_row = await _fetch_row(master_id, db)
    master = dict(master_row)

    # ── non-recurring or edit_mode=all: update master, wipe children ──────────
    if not master["rrule"] or edit_mode == EditMode.all:
        await _apply_updates_to_master(master_id, payload, db)
        if master["rrule"] and edit_mode == EditMode.all:
            # Remove all override children
            cur = await db.execute(
                "SELECT id FROM events WHERE root_event_id = ?", (master_id,)
            )
            child_ids = [r["id"] for r in await cur.fetchall()]
            for cid in child_ids:
                await db.execute("DELETE FROM objects WHERE id = ?", (cid,))
        await db.commit()
        row = await _fetch_row(master_id, db)
        return _row_to_response(row,
            await _contexts_of(master_id, db), await _tags_of(master_id, db))

    # ── edit_mode=this: create or update a stored override ────────────────────
    if edit_mode == EditMode.this:
        target_date = original_date
        if target_date is None:
            raise HTTPException(422, "edit_mode=this requires a virtual occurrence ID "
                                     "(format: {event_id}::{YYYY-MM-DD})")

        # Check if a stored override already exists for this slot
        cur = await db.execute(
            "SELECT id FROM events WHERE root_event_id = ? AND original_date = ?",
            (master_id, target_date.isoformat())
        )
        existing = await cur.fetchone()

        if existing:
            # Update the existing override
            await _apply_updates_to_master(existing["id"], payload, db)
            await db.commit()
            row = await _fetch_row(existing["id"], db)
            return _row_to_response(row,
                await _contexts_of(existing["id"], db), await _tags_of(existing["id"], db))
        else:
            # Compute what the virtual occurrence looked like, then apply updates
            from service_recurrence import _shift
            orig_start = _dt(master["start_datetime"])
            orig_end   = _dt(master["end_datetime"])
            v_start, v_end = _shift(orig_start, orig_end, target_date)

            new_start = payload.start_datetime or v_start
            new_end   = payload.end_datetime   or v_end
            if new_start.tzinfo is None:
                new_start = new_start.replace(tzinfo=timezone.utc)
            if new_end.tzinfo is None:
                new_end = new_end.replace(tzinfo=timezone.utc)

            title = payload.title or master["title"]
            cur = await db.execute("SELECT id FROM objects WHERE title = ?", (title,))
            if await cur.fetchone():
                raise HTTPException(409, detail=f"Title already in use: '{title}'")

            child_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()

            try:
                await db.execute(
                    "INSERT INTO objects (id, title, type, date, created_at, updated_at) "
                    "VALUES (?, ?, 'event', ?, ?, ?)",
                    (child_id, title, new_start.date().isoformat(), now, now)
                )
                await db.execute(
                    "INSERT INTO events "
                    "(id, start_datetime, end_datetime, all_day, location, description, "
                    " status, parent_event_id, root_event_id, original_date) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (child_id,
                     new_start.isoformat(), new_end.isoformat(),
                     int(payload.all_day if payload.all_day is not None else master["all_day"]),
                     payload.location    if payload.location    is not None else master["location"],
                     payload.description if payload.description is not None else master["description"],
                     payload.status.value if payload.status else master["status"],
                     master_id, master_id, target_date.isoformat())
                )
                # Override inherits master's contexts + tags (can be changed later)
                ctx_ids = master_id and await _get_master_context_ids(master_id, db)
                for cid in ctx_ids:
                    await db.execute(
                        "INSERT OR IGNORE INTO object_contexts VALUES (?, ?)", (child_id, cid)
                    )
                tag_ids = await _get_master_tag_ids(master_id, db)
                for tid in tag_ids:
                    await db.execute(
                        "INSERT OR IGNORE INTO object_tags VALUES (?, ?)", (child_id, tid)
                    )
                await db.commit()
            except Exception:
                await db.rollback()
                raise

            row = await _fetch_row(child_id, db)
            return _row_to_response(row,
                await _contexts_of(child_id, db), await _tags_of(child_id, db))

    # ── edit_mode=future: truncate master, create new master from this date ───
    if edit_mode == EditMode.future:
        target_date = original_date
        if target_date is None:
            raise HTTPException(422, "edit_mode=future requires a virtual occurrence ID")

        new_title = payload.title or master["title"]
        cur = await db.execute(
            "SELECT id FROM objects WHERE title = ? AND id != ?", (new_title, master_id)
        )
        if await cur.fetchone():
            raise HTTPException(409, detail=f"Title already in use: '{new_title}'")

        # Shift start/end of new master to target_date
        from service_recurrence import _shift
        orig_start = _dt(master["start_datetime"])
        orig_end   = _dt(master["end_datetime"])
        new_start, new_end = _shift(orig_start, orig_end, target_date)

        if payload.start_datetime:
            ns = payload.start_datetime
            new_start = ns if ns.tzinfo else ns.replace(tzinfo=timezone.utc)
        if payload.end_datetime:
            ne = payload.end_datetime
            new_end = ne if ne.tzinfo else ne.replace(tzinfo=timezone.utc)

        new_rrule = payload.rrule if payload.rrule is not None else master["rrule"]
        if new_rrule:
            _validate_rrule(new_rrule, new_start)

        new_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        # Truncate old series one day before target
        old_until = (target_date - timedelta(days=1)).isoformat()

        try:
            # End the old master's series
            await db.execute(
                "UPDATE events SET rrule_until = ? WHERE id = ?",
                (old_until, master_id)
            )
            # Remove overrides of old master on or after target_date
            cur = await db.execute(
                "SELECT id FROM events WHERE root_event_id = ? AND original_date >= ?",
                (master_id, target_date.isoformat())
            )
            for r in await cur.fetchall():
                await db.execute("DELETE FROM objects WHERE id = ?", (r["id"],))

            # Create new master
            await db.execute(
                "INSERT INTO objects (id, title, type, date, created_at, updated_at) "
                "VALUES (?, ?, 'event', ?, ?, ?)",
                (new_id, new_title, new_start.date().isoformat(), now, now)
            )
            await db.execute(
                "INSERT INTO events "
                "(id, start_datetime, end_datetime, all_day, location, description, status, rrule) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (new_id,
                 new_start.isoformat(), new_end.isoformat(),
                 int(payload.all_day if payload.all_day is not None else master["all_day"]),
                 payload.location    if payload.location    is not None else master["location"],
                 payload.description if payload.description is not None else master["description"],
                 payload.status.value if payload.status else master["status"],
                 new_rrule)
            )
            ctx_ids = await _get_master_context_ids(master_id, db)
            for cid in ctx_ids:
                await db.execute(
                    "INSERT OR IGNORE INTO object_contexts VALUES (?, ?)", (new_id, cid)
                )
            tag_ids = await _get_master_tag_ids(master_id, db)
            for tid in tag_ids:
                await db.execute(
                    "INSERT OR IGNORE INTO object_tags VALUES (?, ?)", (new_id, tid)
                )
            await db.commit()
        except Exception:
            await db.rollback()
            raise

        row = await _fetch_row(new_id, db)
        return _row_to_response(row,
            await _contexts_of(new_id, db), await _tags_of(new_id, db))


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: str,
    edit_mode: EditMode = Query(EditMode.this),
    db: aiosqlite.Connection = Depends(get_db),
):
    master_id, original_date = parse_virtual_id(event_id)
    master_row = await _fetch_row(master_id, db)
    master = dict(master_row)

    # Non-recurring or delete all: remove master (cascades to children)
    if not master["rrule"] or edit_mode == EditMode.all:
        await db.execute("DELETE FROM objects WHERE id = ?", (master_id,))
        await db.commit()
        return

    if edit_mode == EditMode.this:
        target_date = original_date
        if target_date is None:
            raise HTTPException(422, "edit_mode=this requires a virtual occurrence ID")

        # If there is a stored override for this slot, delete it first.
        cur = await db.execute(
            "SELECT id FROM events WHERE root_event_id = ? AND original_date = ?",
            (master_id, target_date.isoformat())
        )
        existing = await cur.fetchone()
        if existing:
            await db.execute("DELETE FROM objects WHERE id = ?", (existing["id"],))

        # In all cases, record the date in the master's exceptions array so
        # expand_master() skips this slot entirely.  This replaces the old
        # "cancelled override" approach that polluted the objects table with
        # titles like "Meeting (cancelled 2026-06-04)" and showed up in search.
        cur = await db.execute(
            "SELECT exceptions FROM events WHERE id = ?", (master_id,)
        )
        exc_row = await cur.fetchone()
        exceptions = json.loads(exc_row["exceptions"] if exc_row else "[]")
        date_str = target_date.isoformat()
        if date_str not in exceptions:
            exceptions.append(date_str)
        await db.execute(
            "UPDATE events SET exceptions = ? WHERE id = ?",
            (json.dumps(sorted(exceptions)), master_id)
        )
        await db.commit()
        return

    if edit_mode == EditMode.future:
        target_date = original_date
        if target_date is None:
            raise HTTPException(422, "edit_mode=future requires a virtual occurrence ID")

        old_until = (target_date - timedelta(days=1)).isoformat()
        await db.execute(
            "UPDATE events SET rrule_until = ? WHERE id = ?", (old_until, master_id)
        )
        cur = await db.execute(
            "SELECT id FROM events WHERE root_event_id = ? AND original_date >= ?",
            (master_id, target_date.isoformat())
        )
        for r in await cur.fetchall():
            await db.execute("DELETE FROM objects WHERE id = ?", (r["id"],))
        await db.commit()


# ─── private update helpers ──────────────────────────────────────────────────

async def _apply_updates_to_master(
    event_id: str,
    payload: EventUpdate,
    db: aiosqlite.Connection,
) -> None:
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        return

    obj_up  = {k: v for k, v in updates.items() if k == "title"}
    evt_up  = {k: v for k, v in updates.items()
               if k in {"start_datetime","end_datetime","all_day","location",
                         "description","status","rrule"}}

    if "title" in obj_up:
        # Read old title BEFORE the UPDATE so rename propagation works correctly
        cur = await db.execute("SELECT title FROM objects WHERE id = ?", (event_id,))
        old_row = await cur.fetchone()
        old_title = old_row["title"] if old_row else None

        cur = await db.execute(
            "SELECT id FROM objects WHERE title = ? AND id != ?",
            (obj_up["title"], event_id)
        )
        if await cur.fetchone():
            raise HTTPException(409, detail=f"Title already in use: '{obj_up['title']}'")
        await db.execute("UPDATE objects SET title = ? WHERE id = ?",
                         (obj_up["title"], event_id))

        # Propagate [[old title]] → [[new title]] in all linked content
        if old_title and old_title != obj_up["title"]:
            from service_links import propagate_rename
            await propagate_rename(event_id, old_title, obj_up["title"], db)

    if evt_up:
        for k in ("start_datetime", "end_datetime"):
            if k in evt_up and evt_up[k] is not None:
                v = evt_up[k]
                evt_up[k] = (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()
        if "status" in evt_up and hasattr(evt_up["status"], "value"):
            evt_up["status"] = evt_up["status"].value
        if "all_day" in evt_up:
            evt_up["all_day"] = int(evt_up["all_day"])

        cols = ", ".join(f"{k} = ?" for k in evt_up)
        await db.execute(f"UPDATE events SET {cols} WHERE id = ?",
                         (*evt_up.values(), event_id))

    if payload.context_ids is not None:
        ctx_ids = await _validate_contexts(payload.context_ids, db)
        await _set_contexts(event_id, ctx_ids, db)

    if payload.tag_names is not None:
        tag_ids = await _resolve_tags(payload.tag_names, db)
        await _set_tags(event_id, tag_ids, db)


async def _get_master_context_ids(master_id: str, db: aiosqlite.Connection) -> List[str]:
    cur = await db.execute(
        "SELECT context_id FROM object_contexts WHERE object_id = ?", (master_id,)
    )
    return [r["context_id"] for r in await cur.fetchall()]


async def _get_master_tag_ids(master_id: str, db: aiosqlite.Connection) -> List[str]:
    cur = await db.execute(
        "SELECT tag_id FROM object_tags WHERE object_id = ?", (master_id,)
    )
    return [r["tag_id"] for r in await cur.fetchall()]
