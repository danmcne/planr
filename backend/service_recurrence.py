"""
Recurrence expansion.

Given a master event row and a date range, yields OccurrenceResponse objects
for every occurrence (real or virtual) in that range, with stored overrides
applied.

Virtual occurrence IDs use the format  "{master_id}::{YYYY-MM-DD}"
so the router can distinguish them from real UUIDs and route edits correctly.

RRULE format: iCal RFC 5545 strings, e.g.:
  "FREQ=DAILY"
  "FREQ=WEEKLY;BYDAY=MO,WE,FR"
  "FREQ=MONTHLY;BYMONTHDAY=1"
  "FREQ=YEARLY"
  "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO"
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from dateutil import rrule as rrulelib
from dateutil.parser import isoparse

from model_event import ContextSummary, OccurrenceResponse


# ─── helpers ─────────────────────────────────────────────────────────────────

def _dt(s: str) -> datetime:
    dt = isoparse(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _date(s: Optional[str]) -> Optional[date]:
    return date.fromisoformat(s) if s else None


def _shift(orig_start: datetime, orig_end: datetime, new_date: date) -> Tuple[datetime, datetime]:
    """Shift start/end to new_date, preserving time-of-day and duration."""
    dur = orig_end - orig_start
    new_start = orig_start.replace(year=new_date.year, month=new_date.month, day=new_date.day)
    return new_start, new_start + dur


def parse_virtual_id(event_id: str) -> Tuple[str, Optional[date]]:
    """Return (master_id, original_date) — original_date is None for real UUIDs."""
    if "::" in event_id:
        master_id, date_str = event_id.split("::", 1)
        return master_id, date.fromisoformat(date_str)
    return event_id, None


# ─── response builders ────────────────────────────────────────────────────────

def _from_row(
    row: dict,
    start_dt: datetime,
    end_dt: datetime,
    is_override: bool,
    is_virtual: bool,
    contexts: List[ContextSummary],
    tags: List[str],
) -> OccurrenceResponse:
    return OccurrenceResponse(
        id              = row["id"],
        title           = row["title"],
        start_datetime  = start_dt,
        end_datetime    = end_dt,
        all_day         = bool(row.get("all_day", 0)),
        location        = row.get("location"),
        description     = row.get("description"),
        status          = row["status"],
        rrule           = row.get("rrule"),
        rrule_until     = _date(row.get("rrule_until")),
        is_recurring    = bool(row.get("rrule")),
        is_override     = is_override,
        is_virtual      = is_virtual,
        parent_event_id = row.get("parent_event_id"),
        root_event_id   = row.get("root_event_id"),
        original_date   = _date(row.get("original_date")),
        created_at      = row["created_at"],
        updated_at      = row["updated_at"],
        contexts        = contexts,
        tags            = tags,
    )


def _virtual(
    master: dict,
    occ_date: date,
    start_dt: datetime,
    end_dt: datetime,
    contexts: List[ContextSummary],
    tags: List[str],
) -> OccurrenceResponse:
    return OccurrenceResponse(
        id              = f"{master['id']}::{occ_date.isoformat()}",
        title           = master["title"],
        start_datetime  = start_dt,
        end_datetime    = end_dt,
        all_day         = bool(master.get("all_day", 0)),
        location        = master.get("location"),
        description     = master.get("description"),
        status          = master["status"],
        rrule           = master.get("rrule"),
        rrule_until     = _date(master.get("rrule_until")),
        is_recurring    = True,
        is_override     = False,
        is_virtual      = True,
        parent_event_id = master["id"],
        root_event_id   = master["id"],
        original_date   = occ_date,
        created_at      = master["created_at"],
        updated_at      = master["updated_at"],
        contexts        = contexts,
        tags            = tags,
    )


# ─── core expansion ──────────────────────────────────────────────────────────

def expand_master(
    master: dict,
    range_start: date,
    range_end: date,
    overrides: Dict[str, dict],        # {original_date_iso: override_row}
    contexts: List[ContextSummary],
    tags: List[str],
) -> List[OccurrenceResponse]:
    """
    Expand one master event into occurrences for [range_start, range_end].
    Stored overrides replace their corresponding virtual slots.
    Dates listed in master["exceptions"] are skipped entirely — they were
    deleted by the user via delete_event(edit_mode=this).
    """
    import json as _json
    start_dt  = _dt(master["start_datetime"])
    end_dt    = _dt(master["end_datetime"])
    until     = _date(master.get("rrule_until"))
    exceptions: set = set(_json.loads(master.get("exceptions") or "[]"))
    results: List[OccurrenceResponse] = []

    if not master.get("rrule"):
        # One-off event: include if its date falls in range
        if range_start <= start_dt.date() <= range_end:
            results.append(_from_row(
                master, start_dt, end_dt,
                is_override=False, is_virtual=False,
                contexts=contexts, tags=tags,
            ))
        return results

    # Recurring: expand RRULE within the window
    try:
        rule = rrulelib.rrulestr(master["rrule"], dtstart=start_dt, ignoretz=False)
    except Exception:
        return results   # malformed RRULE — skip silently

    window_start = datetime(range_start.year, range_start.month, range_start.day,
                            tzinfo=timezone.utc)
    window_end   = datetime(range_end.year, range_end.month, range_end.day,
                            23, 59, 59, tzinfo=timezone.utc)

    for occ_dt in rule.between(window_start, window_end, inc=True):
        occ_date = occ_dt.date()
        if until and occ_date > until:
            break

        date_str = occ_date.isoformat()

        # Skip dates the user explicitly deleted (stored in master["exceptions"])
        if date_str in exceptions:
            continue

        if date_str in overrides:
            ov = overrides[date_str]
            ov_start = _dt(ov["start_datetime"])
            ov_end   = _dt(ov["end_datetime"])
            results.append(_from_row(
                ov, ov_start, ov_end,
                is_override=True, is_virtual=False,
                contexts=contexts, tags=tags,
            ))
        else:
            v_start, v_end = _shift(start_dt, end_dt, occ_date)
            results.append(_virtual(master, occ_date, v_start, v_end, contexts, tags))

    return results
