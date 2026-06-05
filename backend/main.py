# backend/main.py
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from db import init_db
import router_compat
import router_tasks, router_contexts, router_events, router_notes, router_journal, router_links, router_ics, router_tags, router_search

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    from service_watcher import watch_directories
    watcher_task = asyncio.create_task(watch_directories())
    yield
    watcher_task.cancel()
    try:
        await watcher_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Planr API", version="0.5.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    # Same-origin requests (frontend served by FastAPI on port 8000) need no CORS.
    # This entry only matters when running the Vite dev server on 5173 alongside
    # the backend — production deployments can leave it as-is or add 127.0.0.1:8000.
    allow_origins=["http://localhost:5173", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# compat adapter must be FIRST so /api/events/day/{d} beats /api/events/{id}
# and /api/tasks/today beats /api/tasks/{id}, etc.
app.include_router(router_compat.router)
app.include_router(router_tasks.router,    prefix="/api")
app.include_router(router_contexts.router, prefix="/api")
app.include_router(router_events.router,   prefix="/api")
app.include_router(router_notes.router,    prefix="/api")
app.include_router(router_journal.router,  prefix="/api")
app.include_router(router_links.router,    prefix="/api")
app.include_router(router_ics.router,      prefix="/api")
app.include_router(router_tags.router,     prefix="/api")
app.include_router(router_search.router,   prefix="/api")


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.5.0"}


# ── Serve frontend static files ───────────────────────────────────────────────
# Plain HTML/CSS/JS — no build step required.
# Drop files in frontend/ and restart the service; they're live immediately.
# API routes defined above always take priority over these catch-all routes.

_FRONTEND = Path(__file__).parent.parent / "frontend"

if (_FRONTEND / "index.html").exists():
    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_static(full_path: str):
        candidate = _FRONTEND / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_FRONTEND / "index.html")
else:
    @app.get("/", include_in_schema=False)
    async def no_frontend():
        return {"hint": "Place frontend files in the frontend/ directory next to backend/"}
