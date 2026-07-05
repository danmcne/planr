"""Import/export round-trip tests: export from server A, import into a
fresh server B, verify equivalence; re-import proves duplicate skipping.

    .venv/bin/python tests/test_transfer_http.py
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORTS = (8981, 8982)


def server(port):
    tmp = tempfile.mkdtemp(prefix=f"planr-tx{port}-")
    env = dict(os.environ, PLANR_DB=f"{tmp}/t.db",
               PLANR_NOTES_DIR=f"{tmp}/n", PLANR_JOURNAL_DIR=f"{tmp}/j")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--port", str(port)],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc


def req(port, method, path, body=None):
    r = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", method=method,
        headers={"Content-Type": "application/json"},
        data=json.dumps(body).encode() if body else None)
    with urllib.request.urlopen(r, timeout=5) as resp:
        return json.loads(resp.read())


def get_bytes(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
        return r.read()


def post_file(port, path, filename, data: bytes, fields=None):
    boundary = uuid.uuid4().hex
    body = io.BytesIO()
    for k, v in (fields or {}).items():
        body.write((f"--{boundary}\r\nContent-Disposition: form-data; "
                    f"name=\"{k}\"\r\n\r\n{v}\r\n").encode())
    body.write((f"--{boundary}\r\nContent-Disposition: form-data; "
                f"name=\"file\"; filename=\"{filename}\"\r\n"
                f"Content-Type: application/octet-stream\r\n\r\n").encode())
    body.write(data)
    body.write(f"\r\n--{boundary}--\r\n".encode())
    r = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", method="POST", data=body.getvalue(),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(r, timeout=10) as resp:
        return json.loads(resp.read())


def wait(port):
    for _ in range(50):
        try:
            req(port, "GET", "/api/contexts"); return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError(f"server {port} did not start")


def day(port, ds):
    return req(port, "GET", f"/api/calendar/day?date_str={ds}")["timed_events"]


def ensure_context(port, name):
    """planr seeds default contexts; create-or-fetch by full path."""
    for c in req(port, "GET", "/api/contexts"):
        if c["full_path"] == name:
            return c
    return req(port, "POST", "/api/contexts", {"name": name})


def main():
    A, B = (server(p) for p in PORTS)
    try:
        for p in PORTS:
            wait(p)
        n = 0
        def check(name, cond):
            nonlocal n
            assert cond, f"FAIL: {name}"
            n += 1; print(f"  ok  {name}")

        pa, pb = PORTS

        # ── seed server A ────────────────────────────────────────────────
        work = ensure_context(pa, "work")
        m = req(pa, "POST", "/api/events", {
            "title": "PT", "start_at": "2026-07-07T15:00:00",
            "end_at": "2026-07-07T16:00:00", "recurrence": "FREQ=WEEKLY",
            "context_id": work["id"]})
        # override Jul 14 + delete Jul 21
        req(pa, "PUT", f"/api/events/{m['uuid']}", {
            "title": "PT (moved)", "start_at": "2026-07-14T17:00:00",
            "end_at": "2026-07-14T18:00:00",
            "scope": "occurrence", "occurrence_at": "2026-07-14T15:00:00"})
        req(pa, "DELETE",
            f"/api/events/{m['uuid']}?scope=occurrence"
            f"&occurrence_at=2026-07-21T15%3A00%3A00")
        req(pa, "POST", "/api/events", {
            "title": "Standalone; with, escapes\nand a second line",
            "start_at": "2026-07-09T11:00:00", "end_at": "2026-07-09T12:00:00"})
        req(pa, "POST", "/api/tasks", {"title": "Send invoice",
            "importance": "high", "effort": "low",
            "due_at": "2026-07-10T00:00:00", "recurrence": "week:1:moveable",
            "context_id": work["id"]})
        req(pa, "POST", "/api/tasks", {"title": "Done thing", "status": "done"})
        req(pa, "POST", "/api/journal", {"content": "plain day",
                                         "entry_date": "2026-07-01"})
        req(pa, "POST", "/api/journal", {"title": "Trip notes",
            "content": "titled entry", "entry_date": "2026-07-02"})
        req(pa, "POST", "/api/notes", {"title": "SVD ideas",
                                       "content": "sigma only"})
        req(pa, "POST", "/api/notes", {"title": "Property theory",
                                       "content": "res nullius"})

        # ── calendar export shape ────────────────────────────────────────
        ics = get_bytes(pa, "/api/transfer/export/calendar.ics?what=both"
                        ).decode()
        check("ICS: master carries RRULE", "RRULE:FREQ=WEEKLY" in ics)
        check("ICS: override is a RECURRENCE-ID component sharing the UID",
              ics.count(f"UID:{m['uuid']}@planr") == 2
              and "RECURRENCE-ID:20260714T150000" in ics)
        check("ICS: deleted occurrence is an EXDATE; overridden one is not",
              "EXDATE:20260721T150000" in ics
              and "EXDATE:20260714T150000" not in ics)
        check("ICS: text escaping applied",
              "Standalone\\; with\\, escapes\\nand a second line" in ics)
        check("ICS: task exports as VTODO with DUE, PRIORITY, X-PLANR",
              "BEGIN:VTODO" in ics and "DUE:20260710T000000" in ics
              and "PRIORITY:3" in ics and "X-PLANR-EFFORT:low" in ics
              and "STATUS:COMPLETED" in ics)
        check("ICS: CATEGORIES carries the context path",
              "CATEGORIES:work" in ics)

        evonly = get_bytes(pa, "/api/transfer/export/calendar.ics?what=events"
                           ).decode()
        check("what=events omits VTODOs", "BEGIN:VTODO" not in evonly)
        ctxed = get_bytes(
            pa, f"/api/transfer/export/calendar.ics?what=both"
                f"&context_id={work['id']}").decode()
        check("context filter keeps only the subtree",
              "SUMMARY:PT" in ctxed and "SUMMARY:Standalone" not in ctxed
              and "SUMMARY:Send invoice" in ctxed
              and "SUMMARY:Done thing" not in ctxed)

        # ── import into fresh server B ───────────────────────────────────
        ensure_context(pb, "work")  # for CATEGORIES matching
        r = post_file(pb, "/api/transfer/import/ics", "cal.ics", ics.encode(),
                      {"match_categories": "true"})
        check("import counts: 3 events (master+override+plain), 2 tasks",
              r["imported_events"] == 3 and r["imported_tasks"] == 2
              and r["skipped"] == 0)
        check("B: series recurs (Jul 28 present)",
              any(e["title"] == "PT" for e in day(pb, "2026-07-28")))
        evs = [e for e in day(pb, "2026-07-14") if "PT" in e["title"]]
        check("B: override reassembled at its moved time",
              len(evs) == 1 and evs[0]["title"] == "PT (moved)"
              and evs[0]["seg_start_at"] == "2026-07-14T17:00:00")
        check("B: deleted occurrence stayed deleted",
              not [e for e in day(pb, "2026-07-21") if "PT" in e["title"]])
        tsks = req(pb, "GET", "/api/tasks")
        inv = next(t for t in tsks if t["title"] == "Send invoice")
        check("B: task round-trips with recurrence type, effort, context",
              inv["recurrence"] == "week:1:moveable" and inv["effort"] == "low"
              and inv["importance"] == "high"
              and (inv.get("context_path") or "") == "work")
        check("B: escaped text unescaped on import",
              any(t["title"] if False else
                  e["title"] == "Standalone; with, escapes\nand a second line"
                  for e in day(pb, "2026-07-09")))

        r = post_file(pb, "/api/transfer/import/ics", "cal.ics", ics.encode(),
                      {"match_categories": "true"})
        check("re-import skips everything",
              r["imported_events"] == 0 and r["imported_tasks"] == 0
              and r["skipped"] >= 5)

        # ── journal round-trip ───────────────────────────────────────────
        jz = get_bytes(pa, "/api/transfer/export/journal.zip")
        names = zipfile.ZipFile(io.BytesIO(jz)).namelist()
        check("journal zip contains both entries", len(names) == 2)
        r = post_file(pb, "/api/transfer/import/journal", "j.zip", jz)
        check("journal import: 2 in, 0 skipped",
              r["imported"] == 2 and r["skipped"] == 0)
        entries = req(pb, "GET", "/api/journal?limit=10")
        dates = {e["entry_date"]: e["title"] for e in entries}
        check("journal dates and titles preserved",
              dates.get("2026-07-01") in ("", "2026-07-01")
              and dates.get("2026-07-02") == "Trip notes")
        r = post_file(pb, "/api/transfer/import/journal", "j.zip", jz)
        check("journal re-import skips both",
              r["imported"] == 0 and r["skipped"] == 2)

        # a foreign journal file: no frontmatter, dirty name → date from zip
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            zi = zipfile.ZipInfo("random-notes.md",
                                 date_time=(2026, 6, 15, 9, 0, 0))
            z.writestr(zi, "imported foreign content")
        r = post_file(pb, "/api/transfer/import/journal", "f.zip",
                      buf.getvalue())
        entries = req(pb, "GET", "/api/journal?limit=20")
        check("foreign journal file dated from the archive",
              r["imported"] == 1
              and any(e["entry_date"] == "2026-06-15" for e in entries))

        # ── notes round-trip ─────────────────────────────────────────────
        nz = get_bytes(pa, "/api/transfer/export/notes.zip")
        r = post_file(pb, "/api/transfer/import/notes", "n.zip", nz)
        check("notes import: 2 in, 0 skipped",
              r["imported"] == 2 and r["skipped"] == 0)
        titles = {x["title"] for x in req(pb, "GET", "/api/notes")}
        check("note titles preserved",
              {"SVD ideas", "Property theory"} <= titles)
        r = post_file(pb, "/api/transfer/import/notes", "n.zip", nz)
        check("notes re-import skips both",
              r["imported"] == 0 and r["skipped"] == 2)

        # foreign note: dirty filename cleaned; title collision suffixed
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("my_cool--note.md", "foreign body")
            z.writestr("SVD-ideas-2026-01-01-deadbeef.md", "different content")
        r = post_file(pb, "/api/transfer/import/notes", "f.zip", buf.getvalue())
        titles = {x["title"] for x in req(pb, "GET", "/api/notes")}
        check("dirty filename cleaned to a title", "my cool note" in titles)
        check("title collision with different content gets a suffix",
              r["imported"] == 2 and "SVD ideas (imported)" in titles)

        print(f"\nAll {n} transfer round-trip tests passed.")
    finally:
        A.terminate(); B.terminate()
        A.wait(timeout=5); B.wait(timeout=5)


if __name__ == "__main__":
    main()
