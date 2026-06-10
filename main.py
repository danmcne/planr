"""
main.py — planr v1.2.1
"""
import re
import uuid as _uuid
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from db import db, init_db
from db_utils import sync_fts
from models import QuickCapture, OpenPath
from priority import compute_priority_score
from routers import tasks, events, notes, journal, contexts, links, search, calendar

app = FastAPI(title="planr", docs_url="/api/docs")
BASE_DIR  = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

for router in (tasks.router, events.router, notes.router, journal.router,
               contexts.router, links.router, search.router, calendar.router):
    app.include_router(router)

@app.on_event("startup")
async def startup():
    init_db()

# ── View routes ───────────────────────────────────────────────────────────────

@app.get("/", response_class=RedirectResponse)
async def root():
    return RedirectResponse("/day")

@app.get("/contexts", response_class=HTMLResponse)
async def contexts_view(request: Request):
    return templates.TemplateResponse(request, "contexts.html")

@app.get("/day",     response_class=HTMLResponse)
async def day_view(request: Request):
    return templates.TemplateResponse(request, "day.html")

@app.get("/week",    response_class=HTMLResponse)
async def week_view(request: Request):
    return templates.TemplateResponse(request, "week.html")

@app.get("/month",   response_class=HTMLResponse)
async def month_view(request: Request):
    return templates.TemplateResponse(request, "month.html")

# In case any /calendar bookmarks exist from v1.2.0
@app.get("/calendar", response_class=RedirectResponse)
async def calendar_redirect(request: Request):
    view = request.query_params.get("view", "day")
    page = view if view in ("day", "week", "month") else "day"
    q = f"?date={request.query_params['date']}" if "date" in request.query_params else ""
    return RedirectResponse(f"/{page}{q}")

@app.get("/tasks",   response_class=HTMLResponse)
async def tasks_view(request: Request):
    return templates.TemplateResponse(request, "tasks.html")

@app.get("/journal", response_class=HTMLResponse)
async def journal_view(request: Request):
    return templates.TemplateResponse(request, "journal.html")

@app.get("/notes",   response_class=HTMLResponse)
async def notes_view(request: Request):
    return templates.TemplateResponse(request, "notes.html")

@app.get("/review",  response_class=HTMLResponse)
async def review_view(request: Request):
    return templates.TemplateResponse(request, "review.html")

@app.get("/search",  response_class=HTMLResponse)
async def search_view(request: Request):
    return templates.TemplateResponse(request, "search.html")

# ── Quick capture parser ──────────────────────────────────────────────────────
# Syntax: title +context !importance ~effort ^date #tag
# ">" prefix creates an event instead of a task.

def _parse_capture(text: str) -> dict:
    result = dict(title="", context_path=None, importance="normal",
                  effort="medium", due_at=None, is_event=False, is_all_day=False, tags=[])

    if text.startswith(">"):
        result["is_event"] = True
        text = text[1:].strip()

    # +context  (was @context in v1.0.x)
    m = re.search(r"(?<!\S)\+([\w.]+)", text)
    if m:
        result["context_path"] = m.group(1).lower()
        text = text[:m.start()] + text[m.end():]

    m = re.search(r"!(low|normal|high|critical)\b", text, re.I)
    if m:
        result["importance"] = m.group(1).lower()
        text = text[:m.start()] + text[m.end():]

    m = re.search(r"~(low|medium|high)\b", text, re.I)
    if m:
        result["effort"] = m.group(1).lower()
        text = text[:m.start()] + text[m.end():]

    m = re.search(r"\^(\S+)", text)
    if m:
        raw = m.group(1)
        try:
            from dateutil.parser import parse as dp
            parsed_dt = dp(raw)
            # Bare date (no time component in the string)?
            bare_date = re.match(r"^\d{4}-\d{2}-\d{2}$|^\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}$", raw)
            if bare_date:
                result["is_all_day"] = True
                if result["is_event"]:
                    result["due_at"] = parsed_dt.strftime("%Y-%m-%dT00:00:00")
                else:
                    result["due_at"] = parsed_dt.strftime("%Y-%m-%dT23:59:00")
            else:
                result["due_at"] = parsed_dt.isoformat()
        except Exception:
            pass
        text = text[:m.start()] + text[m.end():]

    result["tags"] = re.findall(r"#(\w+)", text)
    text = re.sub(r"#\w+\s*", "", text)
    result["title"] = " ".join(text.split()).strip()
    return result


def _resolve_or_create_context(conn, path: str) -> Optional[int]:
    if not path:
        return None
    row = conn.execute(
        "SELECT id FROM contexts WHERE LOWER(full_path) = ?", (path,)
    ).fetchone()
    if row:
        return row["id"]
    parts = path.split(".")
    parent_id, built = None, ""
    for part in parts:
        built = f"{built}.{part}" if built else part
        row = conn.execute("SELECT id FROM contexts WHERE full_path = ?", (built,)).fetchone()
        if row:
            parent_id = row["id"]
        else:
            conn.execute(
                "INSERT INTO contexts (name, parent_id, full_path, color) VALUES (?,?,?,?)",
                (part, parent_id, built, "#6B7280"),
            )
            parent_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    return parent_id


@app.post("/api/capture")
async def quick_capture(data: QuickCapture):
    parsed = _parse_capture(data.text)
    if not parsed["title"]:
        return {"success": False, "error": "No title found"}

    with db() as conn:
        context_id = _resolve_or_create_context(conn, parsed["context_path"])
        # Fall back to Inbox if no context specified
        if context_id is None:
            inbox = conn.execute("SELECT id FROM contexts WHERE full_path = 'inbox'").fetchone()
            if inbox:
                context_id = inbox["id"]

        now = datetime.now(timezone.utc).isoformat()
        uid = str(_uuid.uuid4())

        if parsed["is_event"]:
            conn.execute(
                """INSERT INTO events
                   (uuid,title,context_id,start_at,all_day,root_uuid,created_at,modified_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (uid, parsed["title"], context_id,
                 parsed["due_at"], int(parsed["is_all_day"]),
                 uid, now, now),
            )
            sync_fts(conn, uid, "event", parsed["title"], "")
            return {"success": True, "type": "event", "uuid": uid, "title": parsed["title"]}

        score = compute_priority_score(
            status="inbox", importance=parsed["importance"],
            effort=parsed["effort"], user_urgency=0.0,
            due_at=parsed["due_at"], created_at=now, last_active_at=None,
        )
        conn.execute(
            """INSERT INTO tasks
               (uuid,title,context_id,status,importance,effort,due_at,
                root_uuid,priority_score,created_at,modified_at)
               VALUES (?,?,?,'inbox',?,?,?,?,?,?,?)""",
            (uid, parsed["title"], context_id,
             parsed["importance"], parsed["effort"], parsed["due_at"],
             uid, score, now, now),
        )
        for tag in parsed["tags"]:
            conn.execute(
                """INSERT INTO tags (name,usage_count,last_used_at)
                   VALUES (?,1,datetime('now'))
                   ON CONFLICT(name) DO UPDATE SET
                       usage_count=usage_count+1,last_used_at=datetime('now')""",
                (tag,),
            )
            tid = conn.execute("SELECT id FROM tags WHERE name=?", (tag,)).fetchone()["id"]
            conn.execute(
                "INSERT OR IGNORE INTO object_tags (object_uuid,tag_id,object_type) VALUES (?,?,'task')",
                (uid, tid),
            )
        sync_fts(conn, uid, "task", parsed["title"], "")
        return {"success": True, "type": "task", "uuid": uid, "title": parsed["title"]}


@app.get("/api/debug/stats")
async def debug_stats():
    with db() as conn:
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("tasks","events","notes","journal_entries","contexts","tags","links")}


# ── Open local files for [[file:Title</path>]] links ─────────────────────────
# planr is a self-hosted, localhost-only app: browsers refuse to open file://
# URLs from an http page, so the server hands the path to the desktop instead.

@app.post("/api/open")
async def open_path(data: OpenPath):
    import shutil
    import subprocess
    p = Path(data.path).expanduser()
    if not p.exists():
        return {"success": False, "error": f"Path does not exist: {p}"}
    opener = shutil.which("xdg-open") or shutil.which("open")
    if not opener:
        return {"success": False, "error": "No system opener (xdg-open) found"}
    try:
        subprocess.Popen([opener, str(p)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"success": True}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
