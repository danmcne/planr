"""recurrence.py — expansion of recurring events over a date range.

Rule storage (events.recurrence)
────────────────────────────────
RFC 5545 RRULE text, without the leading "RRULE:" (accepted if present):

    FREQ=WEEKLY                       weekly on start_at's weekday
    FREQ=WEEKLY;INTERVAL=2            every 2 weeks
    FREQ=MONTHLY                      monthly on start_at's day-of-month
    FREQ=MONTHLY;BYDAY=2TU            monthly on the second Tuesday
    FREQ=MONTHLY;BYDAY=-1FR           monthly on the last Friday
    FREQ=YEARLY;BYMONTH=3;BYDAY=3SU   yearly on the third Sunday of March

The legacy compact form "unit:n" (e.g. "week:1") written by planr ≤ 1.3.0
is still accepted and translated on read — existing rows keep working.

Semantics
─────────
* DTSTART is the event's start_at; the first occurrence is the event itself.
* Occurrences preserve the event's duration (end_at − start_at) and its
  wall-clock time (naive local datetimes throughout, so a 15:00 event stays
  at 15:00 across DST changes — calendar behaviour, not instant behaviour).
* planr semantics for day-of-month rules on the 29th–31st: a plain
  FREQ=MONTHLY (no BYDAY/BYMONTHDAY) starting on such a day CLAMPS — in
  months lacking that day, the occurrence falls on the month's last day.
  Likewise FREQ=YEARLY starting on February 29 falls on Feb 28 outside
  leap years. (The RFC default would silently skip those months; planr
  rewrites such rules to the explicit BYMONTHDAY=…;BYSETPOS=-1 clamp form
  at expansion time, so legacy rows behave correctly without re-saving.)
* UNTIL= and COUNT= inside the rule are honoured (the UI does not emit them
  yet, but hand-entered or imported rules work).
"""
from datetime import date, datetime, time, timedelta
from typing import Optional

from dateutil.rrule import rrulestr

_LEGACY_FREQ = {"day": "DAILY", "week": "WEEKLY", "month": "MONTHLY", "year": "YEARLY"}
_MAX_OCCURRENCES = 1000  # hard cap per event per query window


def rrule_text(recurrence: Optional[str]) -> Optional[str]:
    """Normalize a stored recurrence value to RRULE text, or None if absent
    or unrecognizable (unrecognizable rules degrade to non-recurring)."""
    if not recurrence:
        return None
    rec = recurrence.strip()
    if rec.upper().startswith("RRULE:"):
        rec = rec[6:]
    if "FREQ=" in rec.upper():
        return rec
    parts = rec.split(":")  # legacy "unit:n(:type)"
    freq = _LEGACY_FREQ.get(parts[0])
    if not freq:
        return None
    try:
        interval = max(1, int(parts[1])) if len(parts) > 1 and parts[1] else 1
    except ValueError:
        interval = 1
    return f"FREQ={freq};INTERVAL={interval}"


def expand(row: dict, range_start: date, range_end: date) -> list[dict]:
    """Expand one event row into occurrence rows overlapping
    [range_start, range_end] (inclusive dates).

    Non-recurring rows pass through unchanged as a 1-element list.
    Recurring rows are replaced by their occurrences in the window (possibly
    an empty list). Each occurrence keeps the master's uuid and carries:

        is_occurrence    1  (every expansion-generated row)
        master_start_at  the series' stored start_at

    so the frontend can tell displayed occurrences from stored rows and
    always edit the master. Any parse failure degrades to pass-through —
    a malformed rule must never take a calendar view down.
    """
    rec = rrule_text(row.get("recurrence"))
    if not rec or not row.get("start_at"):
        return [row]
    try:
        dtstart = datetime.fromisoformat(row["start_at"])
        rec = clamp_rule(rec, dtstart)
        rule = rrulestr(rec, dtstart=dtstart)
    except (ValueError, TypeError):
        return [row]

    duration: Optional[timedelta] = None
    if row.get("end_at"):
        try:
            duration = datetime.fromisoformat(row["end_at"]) - dtstart
        except (ValueError, TypeError):
            duration = None

    # An occurrence overlaps the window iff it starts on/before the window's
    # end and ends on/after the window's start — widen the lower bound by
    # the duration so multi-day occurrences straddling the start are kept.
    pad = duration if duration and duration > timedelta(0) else timedelta(0)
    lo = datetime.combine(range_start, time.min) - pad
    hi = datetime.combine(range_end, time.max)

    exdates = parse_exceptions(row.get("recur_exceptions"))

    out: list[dict] = []
    for occ in rule.between(lo, hi, inc=True):
        if occ.isoformat(timespec="seconds") in exdates:
            continue
        d = dict(row)
        d["start_at"] = occ.isoformat(timespec="seconds")
        if duration is not None:
            d["end_at"] = (occ + duration).isoformat(timespec="seconds")
        d["is_occurrence"] = 1
        d["master_start_at"] = row["start_at"]
        out.append(d)
        if len(out) >= _MAX_OCCURRENCES:
            break
    return out


def expand_all(rows, range_start: date, range_end: date) -> list[dict]:
    """Expand a fetched row set and restore the previous SQL ordering
    (all-day first, then by start time)."""
    out: list[dict] = []
    for r in rows:
        out.extend(expand(dict(r), range_start, range_end))
    out.sort(key=lambda d: (-int(d.get("all_day") or 0), d.get("start_at") or ""))
    return out


# ── Rule / exception manipulation (used by the scoped edit endpoints) ─────────

def parse_exceptions(text) -> set:
    """Comma-separated ISO datetimes → set (whitespace-tolerant)."""
    if not text:
        return set()
    return {t.strip() for t in text.split(",") if t.strip()}


def format_exceptions(exdates) -> str:
    return ",".join(sorted(exdates))


def _rule_parts(rule: str) -> dict:
    parts = {}
    for kv in (rule or "").replace("RRULE:", "").split(";"):
        if "=" in kv:
            k, v = kv.split("=", 1)
            parts[k.strip().upper()] = v.strip()
    return parts


def _join_parts(parts: dict) -> str:
    order = ["FREQ", "INTERVAL", "BYMONTH", "BYMONTHDAY", "BYDAY",
             "BYSETPOS", "COUNT", "UNTIL"]
    keys = [k for k in order if k in parts] +            [k for k in parts if k not in order]
    return ";".join(f"{k}={parts[k]}" for k in keys)


def merge_rule(new_rule: str, old_rule: str) -> str:
    """Adopt the structural parts of new_rule, preserving old_rule's series
    bounds (UNTIL / COUNT) unless new_rule sets its own. This is what makes
    'edit all' safe on a previously split segment: re-emitting the rule from
    the editor must not erase the segment's UNTIL and resurrect occurrences
    past the split. An empty new_rule means "stop repeating" and wins."""
    if not (new_rule or "").strip():
        return ""
    new_p = _rule_parts(rrule_text(new_rule) or new_rule)
    old_p = _rule_parts(rrule_text(old_rule) or old_rule)
    for bound in ("UNTIL", "COUNT"):
        if bound in old_p and bound not in new_p:
            new_p[bound] = old_p[bound]
    return _join_parts(new_p)


def set_until(rule: str, until: datetime) -> str:
    """Cap a rule at `until` (inclusive), dropping any COUNT."""
    parts = _rule_parts(rrule_text(rule) or rule)
    parts.pop("COUNT", None)
    parts["UNTIL"] = until.strftime("%Y%m%dT%H%M%S")
    return _join_parts(parts)


def shift_rule(rule: str, delta: timedelta) -> str:
    """Shift a rule's UNTIL bound by delta (when the whole series moves)."""
    if not rule or not delta:
        return rule
    parts = _rule_parts(rule)
    if "UNTIL" in parts:
        try:
            u = datetime.strptime(parts["UNTIL"], "%Y%m%dT%H%M%S")
            parts["UNTIL"] = (u + delta).strftime("%Y%m%dT%H%M%S")
        except ValueError:
            pass
    return _join_parts(parts)


def shift_exceptions(text: str, delta: timedelta) -> str:
    """Shift every exception date by delta (when the whole series moves)."""
    if not text or not delta:
        return text or ""
    out = set()
    for t in parse_exceptions(text):
        try:
            out.add((datetime.fromisoformat(t) + delta).isoformat(timespec="seconds"))
        except ValueError:
            out.add(t)
    return format_exceptions(out)


def rules_equal_structurally(a: str, b: str) -> bool:
    """True when two rules describe the same recurrence pattern, ignoring
    series bounds (UNTIL / COUNT). Used to decide whether an 'edit all'
    actually changed the rule: the editor re-emits the rule on every save,
    so only a *structural* difference should propagate across segments —
    a title edit must not flatten a future segment's different pattern."""
    def strip(r):
        p = _rule_parts(rrule_text(r) or r or "")
        p.pop("UNTIL", None)
        p.pop("COUNT", None)
        return p
    return strip(a) == strip(b)


def clamp_rule(rec: str, dtstart: datetime) -> str:
    """Rewrite a plain day-of-month rule whose anchor day doesn't exist in
    every period into the explicit clamp form ("that day if it exists,
    else the last day"). Rules that already specify BYDAY/BYMONTHDAY/
    BYSETPOS are left untouched — they said what they meant."""
    parts = _rule_parts(rec)
    if any(k in parts for k in ("BYDAY", "BYMONTHDAY", "BYSETPOS")):
        return rec
    freq, day = parts.get("FREQ", "").upper(), dtstart.day
    if freq == "MONTHLY" and day >= 29:
        parts["BYMONTHDAY"] = ",".join(str(k) for k in range(28, day + 1))
        parts["BYSETPOS"] = "-1"
        return _join_parts(parts)
    if freq == "YEARLY" and dtstart.month == 2 and day == 29:
        parts.setdefault("BYMONTH", "2")
        parts["BYMONTHDAY"] = "28,29"
        parts["BYSETPOS"] = "-1"
        return _join_parts(parts)
    return rec


# ── Unify-retime helpers (edit-all v2: 1.8.0) ─────────────────────────────────
#
# "Edit all occurrences" unifies the series: every row adopts the new
# time-of-day and duration, keeping its own date (shifted by any date
# delta). These helpers re-time the bookkeeping that carries times.

def retime(dt: datetime, date_delta_days: int, new_tod: time) -> datetime:
    return datetime.combine(dt.date() + timedelta(days=date_delta_days), new_tod)


def retime_exceptions(text: str, date_delta_days: int, new_tod: time) -> str:
    if not text:
        return ""
    out = set()
    for t in parse_exceptions(text):
        try:
            out.add(retime(datetime.fromisoformat(t), date_delta_days, new_tod)
                    .isoformat(timespec="seconds"))
        except ValueError:
            out.add(t)
    return format_exceptions(out)


def retime_rule(rule: str, date_delta_days: int, new_tod: time) -> str:
    """Re-time a rule's UNTIL bound. The cap 'one second before the split
    occurrence' must track the series' new wall-clock time, otherwise
    moving a series earlier would let a capped segment re-emit its split
    date (duplicating the successor's first occurrence)."""
    if not rule:
        return rule
    parts = _rule_parts(rule)
    if "UNTIL" in parts:
        try:
            u = datetime.strptime(parts["UNTIL"], "%Y%m%dT%H%M%S")
            split = (u + timedelta(seconds=1))       # the excluded occurrence
            parts["UNTIL"] = (retime(split, date_delta_days, new_tod)
                              - timedelta(seconds=1)).strftime("%Y%m%dT%H%M%S")
        except ValueError:
            pass
    return _join_parts(parts)
