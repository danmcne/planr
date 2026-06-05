# backend/links.py
"""
Link panel and autocomplete routes.

  GET /api/links/panel/{object_id}      full side-panel data for one object
  GET /api/links/autocomplete?q=        [[Title]] autocomplete (returns ≤20 matches)
"""

from __future__ import annotations

from typing import List, Optional

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query

from db import get_db
from model_links import ContextSummary, ExternalLink, LinkPanel, LinkedObject, TitleMatch
from service_links import get_dangling, title_completions

router = APIRouter(prefix="/links", tags=["links"])


# ── helpers ───────────────────────────────────────────────────────────────────

async def _get_content(object_id: str, obj_type: str, db) -> str:
    """Retrieve the text content of any object (for dangling link detection)."""
    if obj_type in ("note", "journal"):
        table = "notes" if obj_type == "note" else "journal_entries"
        cur = await db.execute(f"SELECT filepath FROM {table} WHERE id = ?", (object_id,))
        row = await cur.fetchone()
        if row:
            from pathlib import Path
            p = Path(row["filepath"])
            if p.exists():
                from service_markdown import parse
                _, body = parse(p.read_text(encoding="utf-8"))
                return body
    elif obj_type in ("task", "event"):
        table = "tasks" if obj_type == "task" else "events"
        cur = await db.execute(
            f"SELECT description FROM {table} WHERE id = ?", (object_id,)
        )
        row = await cur.fetchone()
        if row:
            return row["description"] or ""
    return ""


# ── routes ────────────────────────────────────────────────────────────────────

@router.get("/panel/{object_id}", response_model=LinkPanel)
async def link_panel(object_id: str, db: aiosqlite.Connection = Depends(get_db)):
    """
    Return everything the side panel needs for a given object:
    backlinks, outgoing links, dangling [[titles]], contexts, tags, external links.
    """
    cur = await db.execute(
        "SELECT id, title, type FROM objects WHERE id = ?", (object_id,)
    )
    obj = await cur.fetchone()
    if not obj:
        raise HTTPException(404, detail="Object not found")

    # ── backlinks: who links TO this object? ─────────────────────────────────
    cur = await db.execute(
        "SELECT o.id, o.title, o.type FROM objects o "
        "JOIN links l ON l.source_id = o.id "
        "WHERE l.target_id = ? AND l.link_type = 'internal'",
        (object_id,)
    )
    backlinks = [
        LinkedObject(id=r["id"], title=r["title"], type=r["type"])
        for r in await cur.fetchall()
    ]

    # ── outgoing links: what does this object link TO? ────────────────────────
    cur = await db.execute(
        "SELECT o.id, o.title, o.type FROM objects o "
        "JOIN links l ON l.target_id = o.id "
        "WHERE l.source_id = ? AND l.link_type = 'internal'",
        (object_id,)
    )
    outgoing = [
        LinkedObject(id=r["id"], title=r["title"], type=r["type"])
        for r in await cur.fetchall()
    ]

    # ── dangling links ────────────────────────────────────────────────────────
    content = await _get_content(object_id, obj["type"], db)
    dangling = await get_dangling(object_id, content, db)

    # ── contexts ──────────────────────────────────────────────────────────────
    cur = await db.execute(
        "SELECT c.id, c.name, c.color FROM contexts c "
        "JOIN object_contexts oc ON oc.context_id = c.id WHERE oc.object_id = ?",
        (object_id,)
    )
    contexts = [
        ContextSummary(id=r["id"], name=r["name"], color=r["color"])
        for r in await cur.fetchall()
    ]

    # ── tags ──────────────────────────────────────────────────────────────────
    cur = await db.execute(
        "SELECT tg.name FROM tags tg "
        "JOIN object_tags ot ON ot.tag_id = tg.id WHERE ot.object_id = ?",
        (object_id,)
    )
    tags = [r["name"] for r in await cur.fetchall()]

    # ── external links ────────────────────────────────────────────────────────
    cur = await db.execute(
        "SELECT id, target_url FROM links "
        "WHERE source_id = ? AND link_type = 'external'",
        (object_id,)
    )
    external = [
        ExternalLink(id=r["id"], url=r["target_url"])
        for r in await cur.fetchall()
    ]

    return LinkPanel(
        object_id      = object_id,
        object_title   = obj["title"],
        object_type    = obj["type"],
        backlinks      = backlinks,
        outgoing_links = outgoing,
        dangling_links = dangling,
        contexts       = contexts,
        tags           = tags,
        external_links = external,
    )


@router.get("/autocomplete", response_model=List[TitleMatch])
async def autocomplete(
    q:     str = Query(..., min_length=1, description="Partial title to match"),
    limit: int = Query(20, ge=1, le=50),
    db: aiosqlite.Connection = Depends(get_db),
):
    """
    Return objects whose title contains q (case-insensitive).
    Prefix matches are ranked first.

    Frontend usage: as the user types [[T..., query this endpoint and show
    completions like "note:Meeting notes" or "task:Buy milk".
    """
    matches = await title_completions(q, db, limit)
    return [TitleMatch(id=m["id"], title=m["title"], type=m["type"]) for m in matches]
