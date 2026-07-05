"""End-to-end recurrence test against a live server on a temp database.

    .venv/bin/python tests/test_recurrence_http.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8971
BASE = f"http://127.0.0.1:{PORT}"


def req(method, path, body=None):
    r = urllib.request.Request(BASE + path, method=method,
                               headers={"Content-Type": "application/json"},
                               data=json.dumps(body).encode() if body else None)
    with urllib.request.urlopen(r, timeout=5) as resp:
        return json.loads(resp.read())


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

        # ── the reported bug, end to end ─────────────────────────────────
        # Weekly Tuesday 15:00–16:00 (2026-07-07 is a Tuesday).
        ev = req("POST", "/api/events", {
            "title": "PT session", "start_at": "2026-07-07T15:00:00",
            "end_at": "2026-07-07T16:00:00", "recurrence": "FREQ=WEEKLY"})
        uid = ev["uuid"]

        # Day view, two weeks later: the occurrence must be there.
        d = req("GET", "/api/calendar/day?date_str=2026-07-21")
        hits = [e for e in d["timed_events"] if e["uuid"] == uid]
        check("day view shows a later weekly occurrence", len(hits) == 1)
        check("occurrence has shifted times",
              hits[0]["seg_start_at"] == "2026-07-21T15:00:00"
              and hits[0]["seg_end_at"] == "2026-07-21T16:00:00")
        check("occurrence flagged for the frontend",
              hits[0].get("is_occurrence") == 1
              and hits[0]["master_start_at"] == "2026-07-07T15:00:00")

        # Day view on a Wednesday: nothing.
        d = req("GET", "/api/calendar/day?date_str=2026-07-22")
        check("no occurrence on a non-matching day",
              not [e for e in d["timed_events"] if e["uuid"] == uid])

        # Week view (Mon 2026-07-20): exactly one occurrence, on the Tuesday.
        w = req("GET", "/api/calendar/week?start_date=2026-07-20")
        tue = [e for e in w["timed_by_day"]["2026-07-21"] if e["uuid"] == uid]
        others = sum(1 for day, evs in w["timed_by_day"].items()
                     for e in evs if e["uuid"] == uid and day != "2026-07-21")
        check("week view: one occurrence, on Tuesday only",
              len(tue) == 1 and others == 0)

        # Month view: four Tuesdays in July 2026.
        m = req("GET", "/api/calendar/month?year=2026&month=7")
        days = sorted(day for day, evs in m["events_by_day"].items()
                      if any(e["uuid"] == uid for e in evs))
        check("month view: all four July Tuesdays",
              days == ["2026-07-07", "2026-07-14", "2026-07-21", "2026-07-28"])

        # ── Nth weekday of the month ─────────────────────────────────────
        ev2 = req("POST", "/api/events", {
            "title": "Board", "start_at": "2026-07-14T09:00:00",
            "end_at": "2026-07-14T10:00:00",
            "recurrence": "FREQ=MONTHLY;BYDAY=2TU"})
        m = req("GET", "/api/calendar/month?year=2026&month=8")
        days = [day for day, evs in m["events_by_day"].items()
                if any(e["uuid"] == ev2["uuid"] for e in evs)]
        check("2nd Tuesday lands on Aug 11", days == ["2026-08-11"])

        # ── legacy stored format from ≤1.3.0 keeps working ───────────────
        ev3 = req("POST", "/api/events", {
            "title": "Legacy", "start_at": "2026-07-07T08:00:00",
            "end_at": "2026-07-07T08:30:00", "recurrence": "week:1"})
        d = req("GET", "/api/calendar/day?date_str=2026-07-14")
        check("legacy 'week:1' event recurs",
              any(e["uuid"] == ev3["uuid"] for e in d["timed_events"]))

        # ── GET /api/events with a range (Review page path) ──────────────
        lst = req("GET", "/api/events?start=2026-07-20&end=2026-07-26")
        check("list endpoint expands into the range",
              sum(1 for e in lst if e["uuid"] == uid) == 1)

        # ── non-recurring events unaffected ──────────────────────────────
        ev4 = req("POST", "/api/events", {
            "title": "Once", "start_at": "2026-07-21T11:00:00",
            "end_at": "2026-07-21T12:00:00"})
        d = req("GET", "/api/calendar/day?date_str=2026-07-21")
        one = [e for e in d["timed_events"] if e["uuid"] == ev4["uuid"]]
        check("one-off event appears once, unflagged",
              len(one) == 1 and not one[0].get("is_occurrence"))
        d = req("GET", "/api/calendar/day?date_str=2026-07-28")
        check("one-off event does not recur",
              not [e for e in d["timed_events"] if e["uuid"] == ev4["uuid"]])

        # ── 1.6.0: the reported day-31 case, exactly as filed ────────────
        # Monthly event starting 31 July MUST appear on 30 September.
        ev5 = req("POST", "/api/events", {
            "title": "test", "start_at": "2026-07-31T19:00:00",
            "end_at": "2026-07-31T20:00:00", "recurrence": "month:1"})
        d = req("GET", "/api/calendar/day?date_str=2026-09-30")
        check("day-31 legacy monthly appears on Sep 30",
              any(e["uuid"] == ev5["uuid"] for e in d["timed_events"]))
        m = req("GET", "/api/calendar/month?year=2027&month=2")
        check("…and on Feb 28",
              any(e["uuid"] == ev5["uuid"]
                  for e in m["events_by_day"].get("2027-02-28", [])))

        # ── 1.6.0: multi-weekday weekly ──────────────────────────────────
        ev6 = req("POST", "/api/events", {
            "title": "Gym", "start_at": "2026-07-07T18:00:00",
            "end_at": "2026-07-07T19:00:00",
            "recurrence": "FREQ=WEEKLY;BYDAY=TU,TH"})
        w = req("GET", "/api/calendar/week?start_date=2026-07-13")
        hit_days = sorted(day for day, evs in w["timed_by_day"].items()
                          if any(e["uuid"] == ev6["uuid"] for e in evs))
        check("Tue+Thu weekly hits exactly Tue and Thu",
              hit_days == ["2026-07-14", "2026-07-16"])

        # ── 1.6.0: static files must revalidate (no stale-JS strandings) ──
        sr = urllib.request.urlopen(f"{BASE}/static/js/shared.js", timeout=5)
        check("static files served with Cache-Control: no-cache",
              sr.headers.get("Cache-Control") == "no-cache")
        import re
        versions = set()
        for p in (list(Path(ROOT, "templates").glob("*.html"))
                  + list(Path(ROOT, "static/js").glob("*.js"))):
            versions |= set(re.findall(r"\?v=(\d+)", p.read_text()))
        check("all cache-bust versions agree (no stragglers)",
              len(versions) == 1)
        check("the stylesheet link is versioned",
              re.search(r'style\.css\?v=\d+',
                        Path(ROOT, "templates/base.html").read_text()))

        print(f"\nAll {n} HTTP integration tests passed.")
    finally:
        proc.terminate()
        proc.wait(timeout=5)


if __name__ == "__main__":
    main()
