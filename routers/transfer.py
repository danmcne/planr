"""routers/transfer.py — import/export.

Export
──────
* Calendar → .ics: events, tasks, or both, optionally restricted to a
  context subtree. Recurring series export faithfully: RRULE (legacy
  rules translated, day-of-month clamping made explicit), EXDATE for
  deleted occurrences, and RECURRENCE-ID components (sharing the
  master's UID) for one-off overrides. Split segments export as their
  own UIDs — the standard iCal shape for "this and future" edits.
* Journal / Notes → .zip of the canonical Markdown files (frontmatter
  included, so planr's own exports round-trip losslessly).

Import
──────
* .ics: VEVENTs and VTODOs. Components sharing a UID are reassembled:
  the base becomes the master, RECURRENCE-ID components become override
  rows under it. Times are taken as literal wall-clock (TZ ignored).
  Context: optionally match CATEGORIES/X-PLANR-CONTEXT against existing
  context paths, else everything lands in one chosen context (or none).
  Duplicates (same title + same start/due) are skipped.
* Journal .zip: entry date from planr frontmatter/filename, else the
  file's date inside the archive. Duplicates skipped by uuid or by
  (date, content); an untitled import colliding with an existing
  untitled entry that day becomes a titled entry.
* Notes .zip: title from frontmatter, else the cleaned filename (planr's
  own "-YYYY-MM-DD-shortuuid" suffix stripped). Duplicates skipped by
  uuid or (title, content); same title with different content imports
  with an "(imported)" suffix.
"""
import io
import re
import uuid as _uuid
import zipfile
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from db import db
from db_utils import sync_fts, sync_tags
from file_sync import JOURNAL_DIR, NOTES_DIR, content_hash, strip_frontmatter
from ics_io import build_calendar, parse_calendar
from models import JournalCreate, NoteCreate
from recurrence import clamp_rule, parse_exceptions, rrule_text
from routers.journal import create_entry
from routers.notes import create_note

router = APIRouter(prefix="/api/transfer", tags=["transfer"])


# ── helpers ───────────────────────────────────────────────────────────────────

def _context_paths(conn):
    return {r["id"]: r["full_path"]
            for r in conn.execute("SELECT id, full_path FROM contexts")}


def _in_subtree(path: Optional[str], root: str) -> bool:
    return bool(path) and (path == root or path.startswith(root + "."))


def _ctx_filter_sql(conn, context_id):
    """Returns (predicate, root_path). Predicate tests a row's context path."""
    if not context_id:
        return (lambda p: True), None
    row = conn.execute("SELECT full_path FROM contexts WHERE id = ?",
                       (context_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Context not found")
    root = row["full_path"]
    return (lambda p: _in_subtree(p, root)), root


# ── export: calendar ──────────────────────────────────────────────────────────

@router.get("/export/calendar.ics")
def export_calendar(what: str = "both", context_id: Optional[int] = None):
    if what not in ("events", "tasks", "both"):
        raise HTTPException(422, "what must be events | tasks | both")
    with db() as conn:
        keep, _ = _ctx_filter_sql(conn, context_id)
        event_rows, todo_rows = [], []

        if what in ("events", "both"):
            rows = [dict(r) for r in conn.execute(
                """SELECT e.*, c.full_path AS context_path
                   FROM events e LEFT JOIN contexts c ON e.context_id = c.id
                   WHERE e.start_at IS NOT NULL""").fetchall()]
            rows = [r for r in rows if keep(r.get("context_path"))]
            # Occurrences covered by an override export as RECURRENCE-ID
            # components, not EXDATEs (iCal semantics: the override replaces).
            covered = {}  # master uuid -> set of override recurrence_ids
            for r in rows:
                if r.get("recurrence_id") and r.get("parent_uuid"):
                    covered.setdefault(r["parent_uuid"], set()).add(r["recurrence_id"])
            for r in rows:
                if r.get("recurrence"):
                    rec = rrule_text(r["recurrence"])
                    try:
                        rec = clamp_rule(rec, datetime.fromisoformat(r["start_at"]))
                    except (ValueError, TypeError):
                        pass
                    r["export_rrule"] = rec
                    r["export_exdates"] = sorted(
                        parse_exceptions(r.get("recur_exceptions"))
                        - covered.get(r["uuid"], set()))
                if r.get("recurrence_id") and r.get("parent_uuid"):
                    r["export_uid"] = f"{r['parent_uuid']}@planr"
                event_rows.append(r)

        if what in ("tasks", "both"):
            rows = [dict(r) for r in conn.execute(
                """SELECT t.*, c.full_path AS context_path
                   FROM tasks t LEFT JOIN contexts c ON t.context_id = c.id"""
            ).fetchall()]
            for t in rows:
                if not keep(t.get("context_path")):
                    continue
                if t.get("recurrence"):
                    parts = t["recurrence"].split(":")
                    t["export_rrule"] = rrule_text(t["recurrence"])
                    if len(parts) > 2:
                        t["recur_type"] = parts[2]
                todo_rows.append(t)

    ics = build_calendar(event_rows, todo_rows)
    return Response(ics, media_type="text/calendar", headers={
        "Content-Disposition": 'attachment; filename="planr-calendar.ics"'})


# ── export: journal / notes zips ──────────────────────────────────────────────

def _zip_dir(dir_path, arc_prefix):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        if dir_path.exists():
            for fp in sorted(dir_path.glob("*.md")):
                z.write(fp, arcname=f"{arc_prefix}/{fp.name}")
    buf.seek(0)
    return buf.read()


@router.get("/export/journal.zip")
def export_journal():
    return Response(_zip_dir(JOURNAL_DIR, "journal"), media_type="application/zip",
                    headers={"Content-Disposition":
                             'attachment; filename="planr-journal.zip"'})


@router.get("/export/notes.zip")
def export_notes():
    return Response(_zip_dir(NOTES_DIR, "notes"), media_type="application/zip",
                    headers={"Content-Disposition":
                             'attachment; filename="planr-notes.zip"'})


# ── import: calendar ──────────────────────────────────────────────────────────

@router.post("/import/ics")
async def import_ics(file: UploadFile = File(...),
                     context_id: Optional[int] = Form(None),
                     match_categories: bool = Form(False)):
    text = (await file.read()).decode("utf-8", errors="replace")
    parsed = parse_calendar(text)
    now = datetime.now(timezone.utc).isoformat()
    imported_events = imported_tasks = skipped = 0

    with db() as conn:
        by_path = {}
        if match_categories:
            by_path = {p.lower(): cid for cid, p in _context_paths(conn).items()}

        def ctx_for(comp):
            if match_categories and comp.get("categories"):
                cid = by_path.get(comp["categories"].lower())
                if cid:
                    return cid
            return context_id

        def event_exists(title, start):
            return conn.execute(
                "SELECT 1 FROM events WHERE title = ? AND start_at = ?",
                (title, start)).fetchone() is not None

        def insert_event(comp, recurrence="", exdates=(), parent=None,
                         root=None, rec_id=None):
            uid = str(_uuid.uuid4())
            conn.execute(
                """INSERT INTO events
                   (uuid,title,description,context_id,start_at,end_at,all_day,
                    recurrence,recur_exceptions,recurrence_id,parent_uuid,
                    root_uuid,location,created_at,modified_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (uid, comp["title"], comp.get("description", ""), ctx_for(comp),
                 comp["start_at"], comp.get("end_at"),
                 int(bool(comp.get("all_day"))), recurrence,
                 ",".join(sorted(exdates)), rec_id, parent, root or uid,
                 comp.get("location", ""), now, now))
            sync_tags(conn, uid, "event", comp.get("description", ""))
            sync_fts(conn, uid, "event", comp["title"], comp.get("description", ""))
            return uid

        # Reassemble series: base component per UID + its overrides.
        groups: dict = {}
        for comp in parsed["events"]:
            groups.setdefault(comp.get("uid") or str(_uuid.uuid4()), []).append(comp)

        for uid, comps in groups.items():
            base = next((c for c in comps if not c.get("recurrence_id")), None)
            overrides = [c for c in comps if c.get("recurrence_id")]
            if base is None:               # orphan overrides → plain events
                for c in overrides:
                    if event_exists(c["title"], c["start_at"]):
                        skipped += 1
                    else:
                        insert_event(c); imported_events += 1
                continue
            if event_exists(base["title"], base["start_at"]):
                skipped += 1 + len(overrides)
                continue
            exdates = set(base.get("exdates") or [])
            exdates |= {c["recurrence_id"] for c in overrides}
            master_uuid = insert_event(base, recurrence=base.get("rrule", ""),
                                       exdates=exdates)
            imported_events += 1
            for c in overrides:
                insert_event(c, parent=master_uuid, root=master_uuid,
                             rec_id=c["recurrence_id"])
                imported_events += 1

        _LEGACY = {"DAILY": "day", "WEEKLY": "week",
                   "MONTHLY": "month", "YEARLY": "year"}
        for t in parsed["todos"]:
            due = t.get("due_at")
            if conn.execute("SELECT 1 FROM tasks WHERE title = ? AND "
                            "COALESCE(due_at,'') = COALESCE(?,'')",
                            (t["title"], due)).fetchone():
                skipped += 1
                continue
            recurrence = ""
            if t.get("rrule"):
                parts = dict(kv.split("=", 1) for kv in t["rrule"].split(";")
                             if "=" in kv)
                unit = _LEGACY.get(parts.get("FREQ", "").upper())
                if unit:
                    recurrence = (f"{unit}:{parts.get('INTERVAL', '1')}:"
                                  f"{t.get('recur_type', 'fixed')}")
            status = t.get("planr_status") or (
                "done" if t.get("ics_status") == "COMPLETED" else "inbox")
            uid = str(_uuid.uuid4())
            conn.execute(
                """INSERT INTO tasks (uuid,title,description,context_id,status,
                       importance,effort,due_at,recurrence,created_at,modified_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (uid, t["title"], t.get("description", ""), ctx_for(t), status,
                 t.get("importance", "normal"), t.get("effort") or "medium",
                 due, recurrence, now, now))
            sync_tags(conn, uid, "task", t.get("description", ""))
            sync_fts(conn, uid, "task", t["title"], t.get("description", ""))
            imported_tasks += 1

    return {"imported_events": imported_events,
            "imported_tasks": imported_tasks, "skipped": skipped}


# ── import: journal / notes zips ──────────────────────────────────────────────

def _zip_md_members(data: bytes):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".md"):
                continue
            yield info, z.read(info).decode("utf-8", errors="replace")


@router.post("/import/journal")
async def import_journal(file: UploadFile = File(...)):
    data = await file.read()
    imported = skipped = 0
    try:
        members = list(_zip_md_members(data))
    except zipfile.BadZipFile:
        raise HTTPException(422, "Not a zip archive")
    with db() as conn:
        existing_uuids = {r["uuid"] for r in
                          conn.execute("SELECT uuid FROM journal_entries")}
        by_date = {}
        for r in conn.execute(
                "SELECT entry_date, title, content_hash FROM journal_entries"):
            by_date.setdefault(r["entry_date"], []).append(r)
    for info, raw in members:
        meta, body = strip_frontmatter(raw)
        if meta.get("uuid") in existing_uuids:
            skipped += 1
            continue
        base = info.filename.rsplit("/", 1)[-1]
        m = re.match(r"^(\d{4}-\d{2}-\d{2})", base)
        entry_date = (m.group(1) if m
                      else (meta.get("created", "")[:10]
                            if re.match(r"^\d{4}-\d{2}-\d{2}$",
                                        meta.get("created", "")[:10])
                            else "%04d-%02d-%02d" % info.date_time[:3]))
        title = meta.get("title", "")
        if title == entry_date:            # planr writes the date as the
            title = ""                     # frontmatter title of untitled entries
        chash = content_hash(body)
        same_day = by_date.get(entry_date, [])
        if any(r["content_hash"] == chash for r in same_day):
            skipped += 1
            continue
        if not title and any((r["title"] or "") in ("", entry_date)
                             for r in same_day):
            title = "Imported"             # keep the day's untitled slot unique
        row = create_entry(JournalCreate(title=title, content=body,
                                         entry_date=entry_date))
        by_date.setdefault(entry_date, []).append(
            {"title": title, "content_hash": row["content_hash"]})
        imported += 1
    return {"imported": imported, "skipped": skipped}


_PLANR_NOTE_SUFFIX = re.compile(r"-\d{4}-\d{2}-\d{2}-[0-9a-f]{8}$")


@router.post("/import/notes")
async def import_notes(file: UploadFile = File(...)):
    data = await file.read()
    imported = skipped = 0
    try:
        members = list(_zip_md_members(data))
    except zipfile.BadZipFile:
        raise HTTPException(422, "Not a zip archive")
    with db() as conn:
        existing_uuids = {r["uuid"] for r in conn.execute("SELECT uuid FROM notes")}
        by_title = {}
        for r in conn.execute("SELECT title, content_hash FROM notes"):
            by_title.setdefault(r["title"], set()).add(r["content_hash"])
    for info, raw in members:
        meta, body = strip_frontmatter(raw)
        if meta.get("uuid") in existing_uuids:
            skipped += 1
            continue
        title = meta.get("title", "").strip()
        if not title:
            stem = info.filename.rsplit("/", 1)[-1][:-3]
            stem = _PLANR_NOTE_SUFFIX.sub("", stem)
            title = re.sub(r"[-_]+", " ", stem).strip() or "Imported note"
        chash = content_hash(body)
        if chash in by_title.get(title, set()):
            skipped += 1
            continue
        if title in by_title:              # same title, different content
            candidate, k = f"{title} (imported)", 2
            while candidate in by_title:
                candidate = f"{title} (imported {k})"; k += 1
            title = candidate
        row = create_note(NoteCreate(title=title, content=body))
        by_title.setdefault(title, set()).add(row["content_hash"])
        imported += 1
    return {"imported": imported, "skipped": skipped}
