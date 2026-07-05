"""End-to-end tests for recurring-series edit scopes against a live server.

    .venv/bin/python tests/test_scopes_http.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8972
BASE = f"http://127.0.0.1:{PORT}"


def req(method, path, body=None):
    r = urllib.request.Request(BASE + path, method=method,
                               headers={"Content-Type": "application/json"},
                               data=json.dumps(body).encode() if body else None)
    with urllib.request.urlopen(r, timeout=5) as resp:
        return json.loads(resp.read())


def day(ds):
    return req("GET", f"/api/calendar/day?date_str={ds}")["timed_events"]


def on_day(ds, title=None):
    evs = day(ds)
    return [e for e in evs if title is None or e["title"] == title]


def main():
    tmp = tempfile.mkdtemp(prefix="planr-test-")
    env = dict(os.environ,
               PLANR_DB=f"{tmp}/test.db",
               PLANR_NOTES_DIR=f"{tmp}/notes",
               PLANR_JOURNAL_DIR=f"{tmp}/journal")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--port", str(PORT)],
        cwd=ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                req("GET", "/api/contexts"); break
            except Exception:
                time.sleep(0.2)
        else:
            raise RuntimeError("server did not start")

        n = 0
        def check(name, cond):
            nonlocal n
            assert cond, f"FAIL: {name}"
            n += 1; print(f"  ok  {name}")

        # Weekly Tue 15:00–16:00, series starts 2026-07-07.
        master = req("POST", "/api/events", {
            "title": "PT session", "start_at": "2026-07-07T15:00:00",
            "end_at": "2026-07-07T16:00:00", "recurrence": "FREQ=WEEKLY"})
        mid = master["uuid"]

        # ── scope=occurrence: override Jul 21 ────────────────────────────
        ov = req("PUT", f"/api/events/{mid}", {
            "title": "Special session",
            "start_at": "2026-07-21T16:00:00", "end_at": "2026-07-21T17:00:00",
            "scope": "occurrence", "occurrence_at": "2026-07-21T15:00:00"})
        check("override row created under the root",
              ov["uuid"] != mid and ov["root_uuid"] == mid
              and ov["parent_uuid"] == mid
              and ov["recurrence_id"] == "2026-07-21T15:00:00")
        evs = on_day("2026-07-21")
        check("Jul 21 shows only the override, at its new time",
              len(evs) == 1 and evs[0]["title"] == "Special session"
              and evs[0]["seg_start_at"] == "2026-07-21T16:00:00")
        check("neighbouring occurrences untouched",
              on_day("2026-07-14", "PT session") and on_day("2026-07-28", "PT session"))

        # ── scope=future: split at Jul 28, move to 17:00 ─────────────────
        seg = req("PUT", f"/api/events/{mid}", {
            "title": "Later session",
            "start_at": "2026-07-28T17:00:00", "end_at": "2026-07-28T18:00:00",
            "recurrence": "FREQ=WEEKLY",
            "scope": "future", "occurrence_at": "2026-07-28T15:00:00"})
        sid = seg["uuid"]
        check("new segment row created under the same root",
              sid != mid and seg["root_uuid"] == mid and seg["parent_uuid"] == mid)
        m = req("GET", f"/api/events/{mid}")
        check("master capped with UNTIL before the split",
              "UNTIL=20260728T145959" in m["recurrence"])
        check("before the split: old time/title",
              on_day("2026-07-14", "PT session")[0]["seg_start_at"] == "2026-07-14T15:00:00")
        evs = on_day("2026-07-28")
        check("at the split: new time/title, no duplicate from the master",
              len(evs) == 1 and evs[0]["title"] == "Later session"
              and evs[0]["seg_start_at"] == "2026-07-28T17:00:00")
        check("after the split: segment recurs weekly",
              on_day("2026-08-04", "Later session")[0]["seg_start_at"]
              == "2026-08-04T17:00:00")
        check("override survives the split", on_day("2026-07-21", "Special session"))

        # ── scope=all: RESET — collapses the group to one clean series ──
        # "Edit all occurrences" removes all other edits: the one-off
        # override is deleted (its slot rejoins the grid), the segment is
        # deleted and the master's split-cap lifted; the form's values
        # and rule govern the single surviving series.
        def exists(uuid):
            try:
                req("GET", f"/api/events/{uuid}")
                return True
            except urllib.error.HTTPError:
                return False

        req("PUT", f"/api/events/{mid}", {
            "title": "Renamed",
            "start_at": "2026-07-14T15:30:00", "end_at": "2026-07-14T16:30:00",
            "recurrence": "FREQ=WEEKLY",
            "scope": "all", "occurrence_at": "2026-07-14T15:00:00"})
        check("master occurrences renamed and re-timed",
              on_day("2026-07-14", "Renamed")[0]["seg_start_at"]
              == "2026-07-14T15:30:00")
        evs = on_day("2026-07-21")
        check("one-off override removed: its slot rejoins the grid",
              len(evs) == 1 and evs[0]["title"] == "Renamed"
              and evs[0]["seg_start_at"] == "2026-07-21T15:30:00"
              and evs[0]["uuid"] == mid)
        check("override and segment rows purged",
              not exists(ov["uuid"]) and not exists(sid))
        m = req("GET", f"/api/events/{mid}")
        check("split-cap lifted: one uncapped rule remains",
              m["recurrence"] == "FREQ=WEEKLY")
        check("series continues past the former split, unified",
              on_day("2026-08-04", "Renamed")[0]["seg_start_at"]
              == "2026-08-04T15:30:00"
              and len(on_day("2026-07-28")) == 1)

        # ── deleted-outright occurrences SURVIVE the reset ───────────────
        qs = urllib.parse.urlencode({"scope": "occurrence",
                                     "occurrence_at": "2026-09-08T15:30:00"})
        req("DELETE", f"/api/events/{mid}?{qs}")
        req("PUT", f"/api/events/{mid}", {
            "title": "Renamed twice",
            "start_at": "2026-07-14T15:30:00", "end_at": "2026-07-14T16:30:00",
            "recurrence": "FREQ=WEEKLY",
            "scope": "all", "occurrence_at": "2026-07-14T15:30:00"})
        check("outright deletion survives a later edit-all",
              not on_day("2026-09-08")
              and bool(on_day("2026-09-01", "Renamed twice")))

        # ── scope=all with a structural rule change ──────────────────────
        req("PUT", f"/api/events/{mid}", {
            "title": "Renamed twice",
            "start_at": "2026-07-14T15:30:00", "end_at": "2026-07-14T16:30:00",
            "recurrence": "FREQ=WEEKLY;INTERVAL=2",
            "scope": "all", "occurrence_at": "2026-07-14T15:30:00"})
        check("rule change applies to the single series from its dtstart",
              bool(on_day("2026-07-07")) and not on_day("2026-07-14")
              and bool(on_day("2026-07-21")) and not on_day("2026-07-28")
              and bool(on_day("2026-08-04")))

        # ── scoped deletes (biweekly slots: Jul 7, 21, Aug 4, 18, Sep 1, 15, 29) ──
        qs = urllib.parse.urlencode({"scope": "occurrence",
                                     "occurrence_at": "2026-08-18T15:30:00"})
        req("DELETE", f"/api/events/{mid}?{qs}")
        check("delete one occurrence: Aug 18 gone, Sep 1 stays",
              not on_day("2026-08-18") and bool(on_day("2026-09-01")))

        qs = urllib.parse.urlencode({"scope": "future",
                                     "occurrence_at": "2026-09-15T15:30:00"})
        req("DELETE", f"/api/events/{mid}?{qs}")
        check("delete this-and-future: Sep 1 stays, Sep 15 and later gone",
              bool(on_day("2026-09-01")) and not on_day("2026-09-15")
              and not on_day("2026-09-29"))

        qs = urllib.parse.urlencode({"scope": "all"})
        deleted = req("DELETE", f"/api/events/{mid}?{qs}")
        check("delete all: the (single) remaining row removed",
              len(deleted["deleted"]) == 1
              and not on_day("2026-07-07") and not on_day("2026-07-21")
              and not on_day("2026-09-01"))

        # ── the reported case, verbatim: monthly on the 5th, a one-off
        # moved to the 4th, then edit-all changing the 5th to the 7th —
        # EVERYTHING must land on the 7th, including the former one-off ──
        mm = req("POST", "/api/events", {
            "title": "Rent review", "start_at": "2026-08-05T10:00:00",
            "end_at": "2026-08-05T10:30:00", "recurrence": "FREQ=MONTHLY"})
        req("PUT", f"/api/events/{mm['uuid']}", {
            "title": "Rent review", "start_at": "2026-09-04T10:00:00",
            "end_at": "2026-09-04T10:30:00",
            "scope": "occurrence", "occurrence_at": "2026-09-05T10:00:00"})
        check("fixture: one-off sits on the 4th",
              bool(on_day("2026-09-04", "Rent review"))
              and not on_day("2026-09-05", "Rent review"))
        req("PUT", f"/api/events/{mm['uuid']}", {
            "title": "Rent review", "start_at": "2026-10-07T10:00:00",
            "end_at": "2026-10-07T10:30:00", "recurrence": "FREQ=MONTHLY",
            "scope": "all", "occurrence_at": "2026-10-05T10:00:00"})
        check("reported case: every month now on the 7th",
              bool(on_day("2026-08-07", "Rent review"))
              and bool(on_day("2026-10-07", "Rent review"))
              and bool(on_day("2026-11-07", "Rent review")))
        check("reported case: the former one-off is on the 7th too — "
              "not shifted by a delta",
              bool(on_day("2026-09-07", "Rent review"))
              and not on_day("2026-09-04", "Rent review")
              and not on_day("2026-09-06", "Rent review"))
        check("reported case: nothing left on the old pattern",
              not on_day("2026-08-05", "Rent review")
              and not on_day("2026-10-05", "Rent review"))

        # ── clamp rule end-to-end ────────────────────────────────────────
        req("POST", "/api/events", {
            "title": "Rent", "start_at": "2026-07-31T09:00:00",
            "end_at": "2026-07-31T09:30:00",
            "recurrence": "FREQ=MONTHLY;BYMONTHDAY=28,29,30,31;BYSETPOS=-1"})
        check("day-31 clamp: September occurrence on the 30th",
              bool(on_day("2026-09-30", "Rent")) and not on_day("2026-09-29", "Rent"))
        m2 = req("GET", "/api/calendar/month?year=2027&month=2")
        check("day-31 clamp: February occurrence on the 28th",
              any(e["title"] == "Rent" for e in
                  m2["events_by_day"].get("2027-02-28", [])))

        print(f"\nAll {n} scope integration tests passed.")
    finally:
        proc.terminate()
        proc.wait(timeout=5)


if __name__ == "__main__":
    main()
