"""routers/calendar.py — calendar data endpoints (day / week / month).

Multi-day event semantics
─────────────────────────
An event has ONE start datetime and ONE end datetime.  For display:

  * all_day = 1                → "spanning": all-day bar across every date.
  * timed, single date         → timed block on the grid.
  * timed, multiple dates      → segmented:
        first day   → timed block  [start time → end of day]   (continues →)
        middle days → all-day bar                              (if any)
        last day    → timed block  [start of day → end time]   (→ continues)

A timed event ending exactly at 00:00 is treated as ending at 24:00 of the
previous day (e.g. Mon 21:00 → Tue 00:00 is a Monday-only event).

All dates in/out of this module are ISO `YYYY-MM-DD`; datetimes ISO 8601.
"""
from calendar import monthrange
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException

from db import db
from recurrence import expand_all

router = APIRouter(prefix="/api/calendar", tags=["calendar"])

# Events overlapping [range_end_param, range_start_param] (inclusive dates).
_OVERLAP_SQL = """
    SELECT e.*, c.full_path AS context_path, c.color AS context_color,
           rc.color AS root_color
    FROM events e
    LEFT JOIN contexts c ON e.context_id = c.id
    LEFT JOIN contexts rc ON rc.full_path = CASE
        WHEN instr(c.full_path, '.') > 0 THEN substr(c.full_path, 1, instr(c.full_path, '.') - 1)
        ELSE c.full_path END
    WHERE e.start_at IS NOT NULL
      AND ( (date(e.start_at) <= ? AND date(COALESCE(e.end_at, e.start_at)) >= ?)
            OR (e.recurrence <> '' AND date(e.start_at) <= ?) )
    ORDER BY e.all_day DESC, e.start_at ASC
"""

_TASKS_SQL = """
    SELECT t.uuid, t.title, t.due_at, t.importance, t.status, t.priority_score,
           c.full_path AS context_path, c.color AS context_color,
           rc.color AS root_color
    FROM tasks t
    LEFT JOIN contexts c ON t.context_id = c.id
    LEFT JOIN contexts rc ON rc.full_path = CASE
        WHEN instr(c.full_path, '.') > 0 THEN substr(c.full_path, 1, instr(c.full_path, '.') - 1)
        ELSE c.full_path END
    WHERE t.due_at IS NOT NULL AND date(t.due_at) BETWEEN ? AND ?
      AND status NOT IN ('done', 'someday')
    ORDER BY priority_score DESC
"""


def _parse_date(s: str, field: str) -> date:
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        raise HTTPException(422, f"{field} must be an ISO date (YYYY-MM-DD)")


def _effective_dates(row) -> tuple[date, date]:
    """Start/end dates, folding a 00:00 end time back onto the previous day."""
    s = date.fromisoformat(row["start_at"][:10])
    if not row["end_at"]:
        return s, s
    e = date.fromisoformat(row["end_at"][:10])
    end_time = row["end_at"][11:19] or "00:00:00"
    if e > s and not row["all_day"] and end_time in ("00:00", "00:00:00"):
        e = e - timedelta(days=1)
    return s, max(s, e)


def segment_event(row) -> list[dict]:
    """Break an event into display segments.

    Returns dicts of two kinds:
      {"kind": "span",  "span_start": date, "span_end": date}
      {"kind": "timed", "day": date, "seg_start_at": str, "seg_end_at": str,
       "cont_before": bool, "cont_after": bool}
    Every segment also carries event_meta: start/end dates and total_days.
    """
    s, e = _effective_dates(row)
    total = (e - s).days + 1
    meta = {"start_date": s.isoformat(), "end_date": e.isoformat(), "total_days": total}

    if row["all_day"]:
        return [{"kind": "span", "span_start": s, "span_end": e, **meta}]

    if s == e:  # single-day timed
        seg_end = row["end_at"]
        # An event ending at 00:00 the next day was folded onto this day:
        # its visible segment runs to the end of the day.
        if seg_end and seg_end[:10] != s.isoformat():
            seg_end = f"{s.isoformat()}T23:59:59"
        return [{"kind": "timed", "day": s,
                 "seg_start_at": row["start_at"], "seg_end_at": seg_end,
                 "cont_before": False, "cont_after": False, **meta}]

    segs = [{"kind": "timed", "day": s,
             "seg_start_at": row["start_at"],
             "seg_end_at": f"{s.isoformat()}T23:59:59",
             "cont_before": False, "cont_after": True, **meta}]
    if total > 2:  # middle days
        segs.append({"kind": "span",
                     "span_start": s + timedelta(days=1),
                     "span_end": e - timedelta(days=1), **meta})
    end_at = row["end_at"] if row["end_at"][11:19] not in ("00:00:00",) \
        else f"{e.isoformat()}T23:59:59"
    segs.append({"kind": "timed", "day": e,
                 "seg_start_at": f"{e.isoformat()}T00:00:00",
                 "seg_end_at": end_at,
                 "cont_before": True, "cont_after": False, **meta})
    return segs


def _span_payload(row, seg, clamp_start: date, clamp_end: date) -> dict:
    """A spanning bar clamped to [clamp_start, clamp_end]."""
    cs, ce = max(seg["span_start"], clamp_start), min(seg["span_end"], clamp_end)
    d = dict(row)
    d.update(
        start_date=seg["start_date"], end_date=seg["end_date"],
        total_days=seg["total_days"],
        col_start=(cs - clamp_start).days,
        col_span=(ce - cs).days + 1,
        # arrows point at any part of the event outside the bar itself
        continues_before=seg["start_date"] < cs.isoformat(),
        continues_after=seg["end_date"] > ce.isoformat(),
    )
    return d


def _timed_payload(row, seg) -> dict:
    d = dict(row)
    d.update(
        seg_start_at=seg["seg_start_at"], seg_end_at=seg["seg_end_at"],
        cont_before=seg["cont_before"], cont_after=seg["cont_after"],
        start_date=seg["start_date"], end_date=seg["end_date"],
        total_days=seg["total_days"],
    )
    return d


@router.get("/day")
def day_data(date_str: str):
    day = _parse_date(date_str, "date_str")
    with db() as conn:
        rows = conn.execute(_OVERLAP_SQL, (date_str, date_str, date_str)).fetchall()
        tasks = conn.execute(_TASKS_SQL, (date_str, date_str)).fetchall()

    all_day, timed = [], []
    for r in expand_all(rows, day, day):
        for seg in segment_event(r):
            if seg["kind"] == "span":
                if seg["span_start"] <= day <= seg["span_end"]:
                    d = _span_payload(r, seg, day, day)
                    d["day_index"] = (day - date.fromisoformat(seg["start_date"])).days + 1
                    all_day.append(d)
            elif seg["day"] == day:
                timed.append(_timed_payload(r, seg))

    return {"date": date_str, "all_day_events": all_day, "timed_events": timed,
            "due_tasks": [dict(t) for t in tasks]}


@router.get("/week")
def week_data(start_date: str):
    start = _parse_date(start_date, "start_date")
    end = start + timedelta(days=6)
    end_str = end.isoformat()

    with db() as conn:
        event_rows = conn.execute(_OVERLAP_SQL, (end_str, start_date, end_str)).fetchall()
        task_rows = conn.execute(_TASKS_SQL, (start_date, end_str)).fetchall()

    days = [(start + timedelta(days=i)).isoformat() for i in range(7)]
    timed_by_day = {d: [] for d in days}
    spanning = []

    for r in expand_all(event_rows, start, end):
        for seg in segment_event(r):
            if seg["kind"] == "span":
                if seg["span_start"] <= end and seg["span_end"] >= start:
                    spanning.append(_span_payload(r, seg, start, end))
            else:
                k = seg["day"].isoformat()
                if k in timed_by_day:
                    timed_by_day[k].append(_timed_payload(r, seg))

    tasks_by_day: dict = {}
    for r in task_rows:
        tasks_by_day.setdefault(r["due_at"][:10], []).append(dict(r))

    return {
        "start_date": start_date, "end_date": end_str, "days": days,
        "spanning_events": spanning,
        "timed_by_day": timed_by_day,
        "tasks_by_day": tasks_by_day,
    }


@router.get("/month")
def month_data(year: int, month: int):
    if not (1 <= month <= 12) or not (1970 <= year <= 2999):
        raise HTTPException(422, "year/month out of range")
    _, last_day = monthrange(year, month)
    first, last = date(year, month, 1), date(year, month, last_day)
    start_str, end_str = first.isoformat(), last.isoformat()

    with db() as conn:
        event_rows = conn.execute(_OVERLAP_SQL, (end_str, start_str, end_str)).fetchall()
        task_rows = conn.execute(
            """SELECT t.uuid, t.title, t.due_at, t.importance, t.status,
                      c.full_path AS context_path
               FROM tasks t
               LEFT JOIN contexts c ON t.context_id = c.id
               WHERE t.due_at IS NOT NULL AND date(t.due_at) BETWEEN ? AND ?
                 AND t.status NOT IN ('done', 'someday')""",
            (start_str, end_str),
        ).fetchall()

    events_by_day: dict = {}
    for r in expand_all(event_rows, first, last):
        s, e = _effective_dates(r)
        multiday = bool(r["all_day"]) or s != e
        cur, fin = max(s, first), min(e, last)
        while cur <= fin:
            ev = dict(r)
            ev["spanning"] = multiday
            ev["is_start"] = cur == s
            ev["is_end"] = cur == e
            events_by_day.setdefault(cur.isoformat(), []).append(ev)
            cur += timedelta(days=1)

    for evs in events_by_day.values():
        evs.sort(key=lambda ev: (not ev["spanning"], ev["start_at"] or ""))

    tasks_by_day: dict = {}
    for r in task_rows:
        tasks_by_day.setdefault(r["due_at"][:10], []).append(dict(r))

    return {
        "year": year, "month": month,
        "start_date": start_str, "end_date": end_str,
        "events_by_day": events_by_day,
        "tasks_by_day": tasks_by_day,
    }
