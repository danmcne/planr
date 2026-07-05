"""Unit tests for recurrence.py — run with the project venv:

    .venv/bin/python tests/test_recurrence.py
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from recurrence import expand, rrule_text  # noqa: E402

PASS = 0


def check(name, cond):
    global PASS
    assert cond, f"FAIL: {name}"
    PASS += 1
    print(f"  ok  {name}")


def ev(start, end=None, rec=""):
    return {"uuid": "m1", "title": "t", "all_day": 0,
            "start_at": start, "end_at": end, "recurrence": rec}


def starts(rows):
    return [r["start_at"] for r in rows]


# ── rule normalization ────────────────────────────────────────────────────────
check("legacy week:1 → RRULE", rrule_text("week:1") == "FREQ=WEEKLY;INTERVAL=1")
check("legacy month:3 → RRULE", rrule_text("month:3") == "FREQ=MONTHLY;INTERVAL=3")
check("RRULE passthrough", rrule_text("FREQ=MONTHLY;BYDAY=2TU") == "FREQ=MONTHLY;BYDAY=2TU")
check("RRULE: prefix stripped", rrule_text("RRULE:FREQ=DAILY") == "FREQ=DAILY")
check("empty → None", rrule_text("") is None)
check("garbage → None", rrule_text("blorp:7") is None)

# ── the reported bug: weekly Tue 15:00–16:00 must actually recur ─────────────
# 2026-07-07 is a Tuesday.
e = ev("2026-07-07T15:00:00", "2026-07-07T16:00:00", "FREQ=WEEKLY")
occ = expand(e, date(2026, 7, 1), date(2026, 7, 31))
check("weekly: 4 Tuesdays in July window",
      starts(occ) == ["2026-07-07T15:00:00", "2026-07-14T15:00:00",
                      "2026-07-21T15:00:00", "2026-07-28T15:00:00"])
check("weekly: duration preserved", occ[1]["end_at"] == "2026-07-14T16:00:00")
check("weekly: flagged as occurrences",
      all(r["is_occurrence"] == 1 for r in occ))
check("weekly: master uuid retained", all(r["uuid"] == "m1" for r in occ))
check("weekly: master_start_at carried",
      all(r["master_start_at"] == "2026-07-07T15:00:00" for r in occ))

# legacy stored value from ≤1.3.0 must behave identically
e = ev("2026-07-07T15:00:00", "2026-07-07T16:00:00", "week:1")
check("legacy weekly expands the same",
      len(expand(e, date(2026, 7, 1), date(2026, 7, 31))) == 4)

# biweekly
e = ev("2026-07-07T15:00:00", "2026-07-07T16:00:00", "FREQ=WEEKLY;INTERVAL=2")
check("biweekly: alternating Tuesdays",
      starts(expand(e, date(2026, 7, 1), date(2026, 7, 31)))
      == ["2026-07-07T15:00:00", "2026-07-21T15:00:00"])

# ── Nth weekday of the month ─────────────────────────────────────────────────
# 2026-07-14 is the second Tuesday of July.
e = ev("2026-07-14T09:00:00", "2026-07-14T10:00:00", "FREQ=MONTHLY;BYDAY=2TU")
occ = expand(e, date(2026, 7, 1), date(2026, 10, 31))
check("2nd Tuesday: Jul→Oct",
      starts(occ) == ["2026-07-14T09:00:00", "2026-08-11T09:00:00",
                      "2026-09-08T09:00:00", "2026-10-13T09:00:00"])

# last Friday of the month (2026-07-31 is a Friday)
e = ev("2026-07-31T18:00:00", "2026-07-31T19:00:00", "FREQ=MONTHLY;BYDAY=-1FR")
check("last Friday: Jul→Sep",
      starts(expand(e, date(2026, 7, 1), date(2026, 9, 30)))
      == ["2026-07-31T18:00:00", "2026-08-28T18:00:00", "2026-09-25T18:00:00"])

# 5th Tuesday exists only in some months (Sep 2026 and Dec 2026, not Oct/Nov)
e = ev("2026-09-29T09:00:00", "2026-09-29T10:00:00", "FREQ=MONTHLY;BYDAY=5TU")
check("5th Tuesday skips months without one",
      starts(expand(e, date(2026, 9, 1), date(2026, 12, 31)))
      == ["2026-09-29T09:00:00", "2026-12-29T09:00:00"])

# day-31 monthly: planr semantics clamp to the last day (not RFC skip)
e = ev("2026-07-31T09:00:00", "2026-07-31T10:00:00", "FREQ=MONTHLY")
check("day-31 monthly clamps to Sep 30 rather than skipping",
      starts(expand(e, date(2026, 7, 1), date(2026, 10, 31)))
      == ["2026-07-31T09:00:00", "2026-08-31T09:00:00",
          "2026-09-30T09:00:00", "2026-10-31T09:00:00"])

# ── yearly on Nth weekday of a month ─────────────────────────────────────────
# 2026-03-15 is the third Sunday of March.
e = ev("2026-03-15T12:00:00", "2026-03-15T14:00:00",
       "FREQ=YEARLY;BYMONTH=3;BYDAY=3SU")
check("3rd Sunday of March, three years",
      starts(expand(e, date(2026, 1, 1), date(2028, 12, 31)))
      == ["2026-03-15T12:00:00", "2027-03-21T12:00:00", "2028-03-19T12:00:00"])

# ── windowing ────────────────────────────────────────────────────────────────
e = ev("2026-07-07T15:00:00", "2026-07-07T16:00:00", "FREQ=WEEKLY")
check("window before first occurrence → empty",
      expand(e, date(2026, 6, 1), date(2026, 6, 30)) == [])
check("window far in the future still expands",
      len(expand(e, date(2027, 7, 1), date(2027, 7, 31))) in (4, 5))

# multi-day recurring event straddling the window start is kept
e = ev("2026-07-06T20:00:00", "2026-07-08T10:00:00", "FREQ=WEEKLY")  # Mon→Wed
occ = expand(e, date(2026, 7, 14), date(2026, 7, 14))  # window = the Tuesday
check("straddling occurrence caught via duration pad",
      starts(occ) == ["2026-07-13T20:00:00"])

# all-day recurring
e = {"uuid": "m2", "title": "t", "all_day": 1,
     "start_at": "2026-07-07T00:00:00", "end_at": "2026-07-07T23:59:59",
     "recurrence": "FREQ=WEEKLY"}
occ = expand(e, date(2026, 7, 1), date(2026, 7, 31))
check("all-day weekly: 4 occurrences, same-day spans",
      len(occ) == 4 and all(r["start_at"][:10] == r["end_at"][:10] for r in occ))

# ── pass-through and degradation ─────────────────────────────────────────────
e = ev("2026-07-07T15:00:00", "2026-07-07T16:00:00", "")
check("non-recurring passes through unchanged",
      expand(e, date(2026, 7, 1), date(2026, 7, 31)) == [e])
e = ev("2026-07-07T15:00:00", "2026-07-07T16:00:00", "FREQ=NONSENSE")
check("malformed rule degrades to pass-through (no crash)",
      expand(e, date(2026, 7, 1), date(2026, 7, 31)) == [e])
e = ev(None, None, "FREQ=WEEKLY")
check("recurring without start_at passes through",
      expand(e, date(2026, 7, 1), date(2026, 7, 31)) == [e])

# COUNT honoured
e = ev("2026-07-07T15:00:00", "2026-07-07T16:00:00", "FREQ=WEEKLY;COUNT=2")
check("COUNT=2 stops the series",
      len(expand(e, date(2026, 7, 1), date(2026, 8, 31))) == 2)
# UNTIL honoured
e = ev("2026-07-07T15:00:00", "2026-07-07T16:00:00",
       "FREQ=WEEKLY;UNTIL=20260715T000000")
check("UNTIL stops the series",
      len(expand(e, date(2026, 7, 1), date(2026, 8, 31))) == 2)

# ── clamped day-of-month (the new UI-emitted form) ───────────────────────────
# "Day 31 if it exists, else the last day of the month."
e = ev("2026-07-31T09:00:00", "2026-07-31T10:00:00",
       "FREQ=MONTHLY;BYMONTHDAY=28,29,30,31;BYSETPOS=-1")
check("day-31 clamp: Jul 31, Aug 31, Sep 30, Oct 31, Nov 30",
      starts(expand(e, date(2026, 7, 1), date(2026, 11, 30)))
      == ["2026-07-31T09:00:00", "2026-08-31T09:00:00", "2026-09-30T09:00:00",
          "2026-10-31T09:00:00", "2026-11-30T09:00:00"])
check("day-31 clamp: February falls on the 28th",
      starts(expand(e, date(2027, 2, 1), date(2027, 2, 28)))
      == ["2027-02-28T09:00:00"])
check("day-31 clamp: leap February falls on the 29th",
      starts(expand(e, date(2028, 2, 1), date(2028, 2, 29)))
      == ["2028-02-29T09:00:00"])

e = ev("2026-06-30T09:00:00", "2026-06-30T10:00:00",
       "FREQ=MONTHLY;BYMONTHDAY=28,29,30;BYSETPOS=-1")
check("day-30 clamp stays on 30 in long months, 28 in Feb",
      starts(expand(e, date(2026, 6, 1), date(2027, 2, 28)))[:3]
      == ["2026-06-30T09:00:00", "2026-07-30T09:00:00", "2026-08-30T09:00:00"]
      and starts(expand(e, date(2027, 2, 1), date(2027, 2, 28)))
      == ["2027-02-28T09:00:00"])

# Yearly Feb 29 clamp: leap years on the 29th, otherwise the 28th.
e = ev("2028-02-29T12:00:00", "2028-02-29T13:00:00",
       "FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=28,29;BYSETPOS=-1")
check("Feb-29 yearly clamp across leap boundary",
      starts(expand(e, date(2028, 1, 1), date(2030, 12, 31)))
      == ["2028-02-29T12:00:00", "2029-02-28T12:00:00", "2030-02-28T12:00:00"])

# ── exception dates (deleted / overridden occurrences) ───────────────────────
e = ev("2026-07-07T15:00:00", "2026-07-07T16:00:00", "FREQ=WEEKLY")
e["recur_exceptions"] = "2026-07-14T15:00:00,2026-07-28T15:00:00"
check("exception dates are skipped",
      starts(expand(e, date(2026, 7, 1), date(2026, 7, 31)))
      == ["2026-07-07T15:00:00", "2026-07-21T15:00:00"])

# ── rule manipulation helpers ────────────────────────────────────────────────
from recurrence import (merge_rule, set_until, shift_rule, shift_exceptions,
                        rules_equal_structurally)
from datetime import datetime as _dt, timedelta as _td

check("merge preserves old UNTIL when new rule lacks one",
      merge_rule("FREQ=WEEKLY;INTERVAL=2", "FREQ=WEEKLY;UNTIL=20260801T000000")
      == "FREQ=WEEKLY;INTERVAL=2;UNTIL=20260801T000000")
check("merge respects a new UNTIL",
      merge_rule("FREQ=WEEKLY;UNTIL=20261231T000000", "FREQ=WEEKLY;UNTIL=20260801T000000")
      == "FREQ=WEEKLY;UNTIL=20261231T000000")
check("empty new rule means stop repeating",
      merge_rule("", "FREQ=WEEKLY;UNTIL=20260801T000000") == "")
check("merge accepts legacy old rule",
      merge_rule("FREQ=MONTHLY;BYDAY=2TU", "week:1") == "FREQ=MONTHLY;BYDAY=2TU")

check("set_until caps and drops COUNT",
      set_until("FREQ=WEEKLY;COUNT=10", _dt(2026, 8, 1, 14, 59, 59))
      == "FREQ=WEEKLY;UNTIL=20260801T145959")
check("shift_rule moves UNTIL with the series",
      shift_rule("FREQ=WEEKLY;UNTIL=20260801T150000", _td(hours=1))
      == "FREQ=WEEKLY;UNTIL=20260801T160000")
check("shift_exceptions moves exdates with the series",
      shift_exceptions("2026-07-14T15:00:00", _td(minutes=30))
      == "2026-07-14T15:30:00")
check("structural equality ignores bounds",
      rules_equal_structurally("FREQ=WEEKLY;UNTIL=20260801T000000", "FREQ=WEEKLY")
      and not rules_equal_structurally("FREQ=WEEKLY", "FREQ=WEEKLY;INTERVAL=2")
      and rules_equal_structurally("week:1", "FREQ=WEEKLY;INTERVAL=1"))

# ── clamp is the DEFAULT for plain day-of-month rules (1.6.0) ────────────────
# The user-reported case: legacy "month:1" starting July 31 must land on
# Sep 30 and Feb 28 — without re-saving the event.
e = ev("2026-07-31T19:00:00", "2026-07-31T20:00:00", "month:1")
occ = starts(expand(e, date(2026, 7, 1), date(2027, 2, 28)))
check("legacy month:1 on day 31 clamps by default",
      "2026-09-30T19:00:00" in occ and "2027-02-28T19:00:00" in occ
      and "2026-08-31T19:00:00" in occ)
e = ev("2026-07-31T19:00:00", "2026-07-31T20:00:00", "FREQ=MONTHLY")
check("plain FREQ=MONTHLY on day 31 clamps by default",
      "2026-09-30T19:00:00" in
      starts(expand(e, date(2026, 9, 1), date(2026, 9, 30))))
e = ev("2028-02-29T12:00:00", "2028-02-29T13:00:00", "FREQ=YEARLY")
check("plain FREQ=YEARLY on Feb 29 clamps by default",
      starts(expand(e, date(2029, 1, 1), date(2029, 12, 31)))
      == ["2029-02-28T12:00:00"])
e = ev("2026-07-31T09:00:00", "2026-07-31T10:00:00", "FREQ=MONTHLY;BYDAY=-1FR")
check("explicit BYDAY rules are not rewritten",
      starts(expand(e, date(2026, 8, 1), date(2026, 8, 31)))
      == ["2026-08-28T09:00:00"])
e = ev("2026-07-14T09:00:00", "2026-07-14T10:00:00", "FREQ=MONTHLY")
check("plain monthly on a safe day stays plain (Feb 14 exists)",
      starts(expand(e, date(2027, 2, 1), date(2027, 2, 28)))
      == ["2027-02-14T09:00:00"])

# ── multi-weekday weekly (1.6.0) ─────────────────────────────────────────────
# Tuesday start, repeats Tuesday and Thursday.
e = ev("2026-07-07T15:00:00", "2026-07-07T16:00:00", "FREQ=WEEKLY;BYDAY=TU,TH")
check("weekly Tue+Thu: both days each week",
      starts(expand(e, date(2026, 7, 6), date(2026, 7, 19)))
      == ["2026-07-07T15:00:00", "2026-07-09T15:00:00",
          "2026-07-14T15:00:00", "2026-07-16T15:00:00"])
e = ev("2026-07-06T07:00:00", "2026-07-06T08:00:00", "FREQ=WEEKLY;BYDAY=MO,WE,FR")
check("weekly MWF",
      [t[:10] for t in starts(expand(e, date(2026, 7, 6), date(2026, 7, 12)))]
      == ["2026-07-06", "2026-07-08", "2026-07-10"])
e = ev("2026-07-07T15:00:00", "2026-07-07T16:00:00",
       "FREQ=WEEKLY;INTERVAL=2;BYDAY=TU,TH")
check("biweekly Tue+Thu keeps week pairing",
      [t[:10] for t in starts(expand(e, date(2026, 7, 6), date(2026, 7, 26)))]
      == ["2026-07-07", "2026-07-09", "2026-07-21", "2026-07-23"])

# ── unify-retime helpers (edit-all v2) ───────────────────────────────────────
from recurrence import retime, retime_rule, retime_exceptions
from datetime import time as _time

check("retime: new time-of-day, date preserved",
      retime(_dt(2026, 7, 14, 16, 0), 0, _time(15, 30))
      == _dt(2026, 7, 14, 15, 30))
check("retime: date delta applies",
      retime(_dt(2026, 7, 14, 16, 0), 1, _time(15, 30))
      == _dt(2026, 7, 15, 15, 30))
check("retime_rule: UNTIL tracks the new time (later)",
      retime_rule("FREQ=WEEKLY;UNTIL=20260728T145959", 0, _time(15, 30))
      == "FREQ=WEEKLY;UNTIL=20260728T152959")
check("retime_rule: UNTIL tracks the new time (earlier — no resurrection)",
      retime_rule("FREQ=WEEKLY;UNTIL=20260728T145959", 0, _time(8, 0))
      == "FREQ=WEEKLY;UNTIL=20260728T075959")
check("retime_exceptions unifies exdate times",
      retime_exceptions("2026-07-14T15:00:00,2026-07-21T15:00:00", 0, _time(8, 0))
      == "2026-07-14T08:00:00,2026-07-21T08:00:00")

print(f"\nAll {PASS} recurrence unit tests passed.")
