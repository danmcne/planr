"""routers/events.py"""
import uuid as _uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException

from db import db
from recurrence import (expand, parse_exceptions, format_exceptions,
                        merge_rule, set_until, shift_rule, shift_exceptions,
                        rules_equal_structurally, retime, retime_exceptions,
                        retime_rule)
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
            # Event overlaps the range if it hasn't ended before `start` —
            # or is recurring, in which case occurrences may fall inside it.
            clauses.append(
                "(date(COALESCE(e.end_at, e.start_at)) >= date(?) OR e.recurrence <> '')")
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
        if start and end:  # bounded range → expand recurrences into it
            out = []
            for r in rows:
                out.extend(expand(dict(r),
                                  date.fromisoformat(start[:10]),
                                  date.fromisoformat(end[:10])))
            out.sort(key=lambda d: d.get("start_at") or "")
            return out
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
    """Update an event. For recurring series, `scope` selects the reach:

        (absent)/'this' — update only this stored row (plain events,
                          and 'only this event' on an override row)
        'occurrence'    — override one occurrence: the master gains an
                          exception date and a standalone override row is
                          created under the same root
        'future'        — split: this segment's rule is capped with UNTIL
                          just before `occurrence_at`; a new segment row
                          (same root) carries the series onward
        'all'           — every row sharing the root: content fields are
                          overwritten; start/end shift by the delta the
                          user applied; each segment keeps its own
                          UNTIL/COUNT so past splits stay intact

    `occurrence_at` is the *original* start of the occurrence the user
    opened (before their edits) — the reference point for 'occurrence',
    'future', and the 'all' delta.
    """
    with db() as conn:
        existing = conn.execute("SELECT * FROM events WHERE uuid = ?", (event_uuid,)).fetchone()
        if not existing:
            raise HTTPException(404, "Event not found")
        now = datetime.now(timezone.utc).isoformat()
        scope = data.scope
        occ_at = data.occurrence_at
        updates = data.model_dump(exclude_none=True)
        updates.pop("scope", None)
        updates.pop("occurrence_at", None)

        series = bool(existing["recurrence"]) or bool(existing["parent_uuid"])
        if scope in (None, "", "this") or not series:
            return _plain_update(conn, existing, updates, now)

        if scope == "occurrence":
            if not existing["recurrence"]:
                return _plain_update(conn, existing, updates, now)  # override row
            if not occ_at:
                raise HTTPException(422, "occurrence_at required for scope=occurrence")
            return _override_occurrence(conn, existing, updates, occ_at, now)

        if scope == "future":
            if not existing["recurrence"]:
                raise HTTPException(422, "scope=future requires a recurring event")
            if not occ_at:
                raise HTTPException(422, "occurrence_at required for scope=future")
            return _split_future(conn, existing, updates, occ_at, now)

        if scope == "all":
            return _update_all(conn, existing, updates, occ_at, now)

        raise HTTPException(422, f"unknown scope '{scope}'")


def _plain_update(conn, existing, updates, now):
    if not updates:
        return dict(existing)
    if "all_day" in updates:
        updates["all_day"] = int(updates["all_day"])
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    conn.execute(
        f"UPDATE events SET {set_clause}, modified_at = ? WHERE uuid = ?",
        list(updates.values()) + [now, existing["uuid"]],
    )
    _resync(conn, existing["uuid"], updates, existing)
    return dict(conn.execute("SELECT * FROM events WHERE uuid = ?",
                             (existing["uuid"],)).fetchone())


def _resync(conn, uid, updates, existing):
    if "description" in updates:
        sync_tags(conn, uid, "event", updates["description"])
    if "title" in updates or "description" in updates:
        sync_fts(conn, uid, "event",
                 updates.get("title", existing["title"]),
                 updates.get("description", existing["description"]))


def _root_of(row) -> str:
    return row["root_uuid"] or row["uuid"]


def _override_occurrence(conn, master, updates, occ_at, now):
    """Exclude `occ_at` from the master's series and create a standalone
    override event carrying the edited fields, linked under the same root."""
    ex = parse_exceptions(master["recur_exceptions"])
    ex.add(occ_at)
    conn.execute("UPDATE events SET recur_exceptions = ?, modified_at = ? WHERE uuid = ?",
                 (format_exceptions(ex), now, master["uuid"]))

    uid = str(_uuid.uuid4())
    row = {
        "title":       updates.get("title", master["title"]),
        "description": updates.get("description", master["description"]),
        "context_id":  updates.get("context_id", master["context_id"]),
        "start_at":    updates.get("start_at", occ_at),
        "end_at":      updates.get("end_at"),
        "all_day":     int(updates.get("all_day", master["all_day"])),
        "location":    updates.get("location", master["location"]),
    }
    conn.execute(
        """INSERT INTO events
           (uuid,title,description,context_id,start_at,end_at,all_day,
            recurrence,recur_exceptions,recurrence_id,parent_uuid,root_uuid,
            location,created_at,modified_at)
           VALUES (?,?,?,?,?,?,?,'','',?,?,?,?,?,?)""",
        (uid, row["title"], row["description"], row["context_id"],
         row["start_at"], row["end_at"], row["all_day"],
         occ_at, master["uuid"], _root_of(master),
         row["location"], now, now),
    )
    sync_tags(conn, uid, "event", row["description"])
    sync_fts(conn, uid, "event", row["title"], row["description"])
    return dict(conn.execute("SELECT * FROM events WHERE uuid = ?", (uid,)).fetchone())


def _split_future(conn, master, updates, occ_at, now):
    """Cap this segment before occ_at; continue the series in a new segment
    row under the same root, carrying edited fields and any exception dates
    that fall after the split (shifted by the same delta as the series)."""
    occ_dt = datetime.fromisoformat(occ_at)
    master_dt = datetime.fromisoformat(master["start_at"])
    new_rule = merge_rule(updates.get("recurrence", master["recurrence"]),
                          master["recurrence"])

    if occ_dt <= master_dt:
        # Splitting at (or before) the first occurrence — the "future" IS
        # this whole segment; update it in place, keeping its own bounds.
        u = dict(updates); u["recurrence"] = new_rule
        return _plain_update(conn, master, u, now)

    new_start = updates.get("start_at", occ_at)
    delta = datetime.fromisoformat(new_start) - occ_dt

    # Exceptions before the split stay with the master; later ones move
    # (shifted, so an occurrence deleted at 15:00 stays deleted at 15:30).
    ex_before, ex_after = set(), set()
    for t in parse_exceptions(master["recur_exceptions"]):
        try:
            (ex_before if datetime.fromisoformat(t) < occ_dt else ex_after).add(t)
        except ValueError:
            ex_before.add(t)

    conn.execute(
        "UPDATE events SET recurrence = ?, recur_exceptions = ?, modified_at = ? WHERE uuid = ?",
        (set_until(master["recurrence"], occ_dt - timedelta(seconds=1)),
         format_exceptions(ex_before), now, master["uuid"]))

    uid = str(_uuid.uuid4())
    row = {
        "title":       updates.get("title", master["title"]),
        "description": updates.get("description", master["description"]),
        "context_id":  updates.get("context_id", master["context_id"]),
        "start_at":    new_start,
        "end_at":      updates.get("end_at"),
        "all_day":     int(updates.get("all_day", master["all_day"])),
        "location":    updates.get("location", master["location"]),
    }
    conn.execute(
        """INSERT INTO events
           (uuid,title,description,context_id,start_at,end_at,all_day,
            recurrence,recur_exceptions,recurrence_id,parent_uuid,root_uuid,
            location,created_at,modified_at)
           VALUES (?,?,?,?,?,?,?,?,?,NULL,?,?,?,?,?)""",
        (uid, row["title"], row["description"], row["context_id"],
         row["start_at"], row["end_at"], row["all_day"],
         shift_rule(new_rule, delta),
         shift_exceptions(format_exceptions(ex_after), delta),
         master["uuid"], _root_of(master),
         row["location"], now, now),
    )
    sync_tags(conn, uid, "event", row["description"])
    sync_fts(conn, uid, "event", row["title"], row["description"])
    return dict(conn.execute("SELECT * FROM events WHERE uuid = ?", (uid,)).fetchone())


def _update_all(conn, ref, updates, occ_at, now):
    """Reset semantics: "edit all occurrences" removes all other edits.

    The whole root group collapses back to ONE clean series carrying the
    form's values. One-off override rows are deleted and their exception
    dates lifted, so those occurrences rejoin the regular grid; split
    segments are deleted and the master's split-cap removed. Occurrences
    the user deleted outright (exceptions with no override) stay deleted,
    re-timed onto the new schedule.

    The new series is anchored by the occurrence the user opened: the
    date delta and the new time-of-day apply to the series start, the
    surviving exceptions, and any genuine tail bound (UNTIL) — which is
    taken from the chronologically last segment, since split caps live
    on earlier rows and are exactly the edits being removed.
    """
    root = _root_of(ref)
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM events WHERE COALESCE(root_uuid, uuid) = ?", (root,)).fetchall()]
    recurring = [r for r in rows if r["recurrence"]]

    if not recurring:
        # Defensive: a group with no series left — apply values to every row.
        vals = {k: updates[k] for k in
                ("title", "description", "context_id", "location",
                 "start_at", "end_at") if k in updates}
        if "all_day" in updates:
            vals["all_day"] = int(updates["all_day"])
        for r in rows:
            if not vals:
                break
            set_clause = ", ".join(f"{k} = ?" for k in vals)
            conn.execute(f"UPDATE events SET {set_clause}, modified_at = ? WHERE uuid = ?",
                         list(vals.values()) + [now, r["uuid"]])
            _resync(conn, r["uuid"], vals, r)
        return dict(conn.execute("SELECT * FROM events WHERE uuid = ?",
                                 (ref["uuid"],)).fetchone())

    # Collapse target: the root master when it survives, else the
    # earliest remaining series row.
    target = next((r for r in recurring if r["uuid"] == root), None)
    if target is None:
        target = min(recurring, key=lambda r: r["start_at"] or "")

    # Temporal intent, measured against the occurrence the user opened.
    # Absent a time change, normalize into the target's own frame so
    # exceptions gathered from segments still match after the collapse.
    base = occ_at or ref["start_at"]
    date_delta, new_tod, duration = 0, None, None
    if updates.get("start_at") and base:
        try:
            new_start = datetime.fromisoformat(updates["start_at"])
            date_delta = (new_start.date()
                          - datetime.fromisoformat(base).date()).days
            new_tod = new_start.time()
            if updates.get("end_at"):
                duration = datetime.fromisoformat(updates["end_at"]) - new_start
        except ValueError:
            pass
    if new_tod is None:
        date_delta = 0
        new_tod = datetime.fromisoformat(target["start_at"]).time()

    # Deletions survive the reset; override-covered slots rejoin the grid.
    covered = {r["recurrence_id"] for r in rows if r["recurrence_id"]}
    exdates = set()
    for r in recurring:
        exdates |= parse_exceptions(r["recur_exceptions"]) - covered
    exdates = {retime(datetime.fromisoformat(x), date_delta, new_tod)
               .isoformat(timespec="seconds")
               for x in exdates}

    # The collapsed rule: the form's rule, plus any genuine tail bound
    # (UNTIL/COUNT the widget cannot express) from the last segment.
    last = max(recurring, key=lambda r: r["start_at"] or "")
    form_rule = updates.get("recurrence") or last["recurrence"]
    rule = retime_rule(merge_rule(form_rule, last["recurrence"]),
                       date_delta, new_tod)

    vals = {k: updates[k] for k in
            ("title", "description", "context_id", "location") if k in updates}
    if "all_day" in updates:
        vals["all_day"] = int(updates["all_day"])
    vals["recurrence"] = rule
    vals["recur_exceptions"] = format_exceptions(exdates)
    vals["recurrence_id"] = None
    vals["parent_uuid"] = None
    ns = retime(datetime.fromisoformat(target["start_at"]), date_delta, new_tod)
    vals["start_at"] = ns.isoformat(timespec="seconds")
    if duration is not None:
        vals["end_at"] = (ns + duration).isoformat(timespec="seconds")
    elif target["end_at"]:
        old_dur = (datetime.fromisoformat(target["end_at"])
                   - datetime.fromisoformat(target["start_at"]))
        vals["end_at"] = (ns + old_dur).isoformat(timespec="seconds")

    set_clause = ", ".join(f"{k} = ?" for k in vals)
    conn.execute(f"UPDATE events SET {set_clause}, modified_at = ? WHERE uuid = ?",
                 list(vals.values()) + [now, target["uuid"]])
    _resync(conn, target["uuid"], vals, target)
    for r in rows:
        if r["uuid"] != target["uuid"]:
            _purge(conn, r["uuid"])

    return dict(conn.execute("SELECT * FROM events WHERE uuid = ?",
                             (target["uuid"],)).fetchone())


def _purge(conn, uid: str):
    conn.execute("DELETE FROM events WHERE uuid = ?", (uid,))
    conn.execute("DELETE FROM object_tags WHERE object_uuid = ?", (uid,))
    conn.execute("DELETE FROM search_index WHERE uuid = ?", (uid,))


@router.delete("/{event_uuid}")
def delete_event(event_uuid: str, scope: Optional[str] = None,
                 occurrence_at: Optional[str] = None):
    """Delete an event. For recurring series, `scope` selects the reach:

        (absent)      — delete this stored row only (plain events, overrides)
        'occurrence'  — remove one occurrence (exception date on the rule)
        'future'      — cap this segment before occurrence_at and delete
                        every root-group row from occurrence_at onward
        'all'         — delete every row in the root group
    """
    with db() as conn:
        row = conn.execute("SELECT * FROM events WHERE uuid = ?", (event_uuid,)).fetchone()
        if not row:
            raise HTTPException(404, "Event not found")
        now = datetime.now(timezone.utc).isoformat()

        if scope == "occurrence" and row["recurrence"]:
            if not occurrence_at:
                raise HTTPException(422, "occurrence_at required for scope=occurrence")
            ex = parse_exceptions(row["recur_exceptions"])
            ex.add(occurrence_at)
            conn.execute(
                "UPDATE events SET recur_exceptions = ?, modified_at = ? WHERE uuid = ?",
                (format_exceptions(ex), now, event_uuid))
            return {"excluded": occurrence_at, "uuid": event_uuid}

        if scope == "future" and row["recurrence"]:
            if not occurrence_at:
                raise HTTPException(422, "occurrence_at required for scope=future")
            occ_dt = datetime.fromisoformat(occurrence_at)
            root = row["root_uuid"] or row["uuid"]
            victims = [r for r in conn.execute(
                "SELECT * FROM events WHERE COALESCE(root_uuid, uuid) = ? AND uuid <> ?",
                (root, event_uuid)).fetchall()
                if (r["recurrence_id"] or r["start_at"] or "") >= occurrence_at]
            if occ_dt <= datetime.fromisoformat(row["start_at"]):
                victims.append(row)          # whole segment goes
            else:
                conn.execute(
                    "UPDATE events SET recurrence = ?, modified_at = ? WHERE uuid = ?",
                    (set_until(row["recurrence"], occ_dt - timedelta(seconds=1)),
                     now, event_uuid))
            for v in victims:
                _purge(conn, v["uuid"])
            return {"deleted_from": occurrence_at,
                    "deleted": [v["uuid"] for v in victims]}

        if scope == "all" and (row["recurrence"] or row["parent_uuid"]):
            root = row["root_uuid"] or row["uuid"]
            uids = [r["uuid"] for r in conn.execute(
                "SELECT uuid FROM events WHERE COALESCE(root_uuid, uuid) = ?",
                (root,)).fetchall()]
            for u in uids:
                _purge(conn, u)
            return {"deleted": uids}

        _purge(conn, event_uuid)
        return {"deleted": event_uuid}
