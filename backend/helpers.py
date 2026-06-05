# backend/helpers.py
"""
Shared DB helpers used by all routers.

Previously copy-pasted across router_tasks, router_events, router_notes,
and router_journal. Centralised here so drift can't accumulate.

Usage
─────
from helpers import (
    ContextSummary,
    contexts_of, tags_of,
    validate_contexts, resolve_tags,
    set_contexts, set_tags,
    INBOX_ID, UNCATEGORIZED_ID,
)
"""

from __future__ import annotations

import uuid
from typing import List

import aiosqlite
from fastapi import HTTPException
from pydantic import BaseModel

INBOX_ID         = "ctx-inbox"
UNCATEGORIZED_ID = "ctx-uncategorized"


class ContextSummary(BaseModel):
    id:    str
    name:  str
    color: str


# ── read helpers ──────────────────────────────────────────────────────────────

async def contexts_of(
    obj_id: str,
    db: aiosqlite.Connection,
) -> List[ContextSummary]:
    cur = await db.execute(
        "SELECT c.id, c.name, c.color FROM contexts c "
        "JOIN object_contexts oc ON oc.context_id = c.id WHERE oc.object_id = ?",
        (obj_id,),
    )
    return [ContextSummary(id=r["id"], name=r["name"], color=r["color"])
            for r in await cur.fetchall()]


async def tags_of(obj_id: str, db: aiosqlite.Connection) -> List[str]:
    cur = await db.execute(
        "SELECT tg.name FROM tags tg "
        "JOIN object_tags ot ON ot.tag_id = tg.id WHERE ot.object_id = ?",
        (obj_id,),
    )
    return [r["name"] for r in await cur.fetchall()]


# ── validation helpers ────────────────────────────────────────────────────────

async def validate_contexts(
    ctx_ids: List[str],
    db: aiosqlite.Connection,
    default_ctx: str = INBOX_ID,
) -> List[str]:
    """Validate that all IDs exist; return default when list is empty."""
    if not ctx_ids:
        return [default_ctx]
    ph = ",".join("?" * len(ctx_ids))
    cur = await db.execute(f"SELECT id FROM contexts WHERE id IN ({ph})", ctx_ids)
    found = {r["id"] for r in await cur.fetchall()}
    missing = set(ctx_ids) - found
    if missing:
        raise HTTPException(422, detail=f"Unknown context IDs: {sorted(missing)}")
    return ctx_ids


async def resolve_tags(names: List[str], db: aiosqlite.Connection) -> List[str]:
    """Get or create tags by name (case-folded); return their UUIDs."""
    ids: List[str] = []
    for raw in names:
        name = raw.strip().lower()
        if not name:
            continue
        cur = await db.execute("SELECT id FROM tags WHERE name = ?", (name,))
        row = await cur.fetchone()
        if row:
            ids.append(row["id"])
        else:
            tid = str(uuid.uuid4())
            await db.execute("INSERT INTO tags (id, name) VALUES (?, ?)", (tid, name))
            ids.append(tid)
    return ids


# ── write helpers ─────────────────────────────────────────────────────────────

async def set_contexts(
    obj_id: str,
    ctx_ids: List[str],
    db: aiosqlite.Connection,
) -> None:
    await db.execute("DELETE FROM object_contexts WHERE object_id = ?", (obj_id,))
    for cid in ctx_ids:
        await db.execute(
            "INSERT OR IGNORE INTO object_contexts (object_id, context_id) VALUES (?, ?)",
            (obj_id, cid),
        )


async def set_tags(
    obj_id: str,
    tag_ids: List[str],
    db: aiosqlite.Connection,
) -> None:
    await db.execute("DELETE FROM object_tags WHERE object_id = ?", (obj_id,))
    for tid in tag_ids:
        await db.execute(
            "INSERT OR IGNORE INTO object_tags (object_id, tag_id) VALUES (?, ?)",
            (obj_id, tid),
        )
