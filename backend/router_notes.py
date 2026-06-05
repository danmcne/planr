# backend/notes.py
"""
Notes routes.

Filesystem is canonical for content; DB is canonical for metadata + search.
Every write goes to the .md file first, then updates the DB.
Renaming a note changes its filename to match the new title.

  GET    /api/notes                 list (no content body, for speed)
  GET    /api/notes/{id}            full note with content
  POST   /api/notes                 create → writes .md file
  PATCH  /api/notes/{id}            update → rewrites .md, renames file if title changed
  DELETE /api/notes/{id}            deletes .md file + DB cascade
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, status

from config import NOTES_DIR
from db import get_db
from model_note import ContextSummary, NoteCreate, NoteResponse, NoteUpdate
import service_markdown as md
from service_watcher import ignore
from service_links import sync_links, propagate_rename

router = APIRouter(prefix="/notes", tags=["notes"])

_SEL = """
    SELECT o.id, o.title, o.created_at, o.updated_at, n.filepath
    FROM objects o JOIN notes n ON n.id = o.id
"""


# ── shared helpers ────────────────────────────────────────────────────────────

async def _contexts_of(nid: str, db) -> List[ContextSummary]:
    cur = await db.execute(
        "SELECT c.id, c.name, c.color FROM contexts c "
        "JOIN object_contexts oc ON oc.context_id = c.id WHERE oc.object_id = ?", (nid,)
    )
    return [ContextSummary(id=r["id"], name=r["name"], color=r["color"])
            for r in await cur.fetchall()]


async def _tags_of(nid: str, db) -> List[str]:
    cur = await db.execute(
        "SELECT tg.name FROM tags tg JOIN object_tags ot ON ot.tag_id = tg.id "
        "WHERE ot.object_id = ?", (nid,)
    )
    return [r["name"] for r in await cur.fetchall()]


async def _validate_contexts(ctx_ids: List[str], db) -> List[str]:
    if not ctx_ids:
        return ["ctx-uncategorized"]
    ph = ",".join("?" * len(ctx_ids))
    cur = await db.execute(f"SELECT id FROM contexts WHERE id IN ({ph})", ctx_ids)
    found = {r["id"] for r in await cur.fetchall()}
    missing = set(ctx_ids) - found
    if missing:
        raise HTTPException(422, detail=f"Unknown context IDs: {sorted(missing)}")
    return ctx_ids


async def _resolve_tags(names: List[str], db) -> List[str]:
    ids: List[str] = []
    for raw in names:
        name = raw.strip().lower()
        if not name:
            continue
        cur = await db.execute("SELECT id FROM tags WHERE name = ?", (name,))
        row = await cur.fetchone()
        ids.append(row["id"] if row else str(uuid.uuid4()))
        if not row:
            await db.execute("INSERT INTO tags (id, name) VALUES (?, ?)",
                             (ids[-1], name))
    return ids


async def _set_contexts(nid, ctx_ids, db):
    await db.execute("DELETE FROM object_contexts WHERE object_id = ?", (nid,))
    for cid in ctx_ids:
        await db.execute(
            "INSERT OR IGNORE INTO object_contexts VALUES (?,?)", (nid, cid)
        )


async def _set_tags(nid, tag_ids, db):
    await db.execute("DELETE FROM object_tags WHERE object_id = ?", (nid,))
    for tid in tag_ids:
        await db.execute(
            "INSERT OR IGNORE INTO object_tags VALUES (?,?)", (nid, tid)
        )


async def _fetch_row(note_id: str, db) -> aiosqlite.Row:
    cur = await db.execute(_SEL + "WHERE o.id = ?", (note_id,))
    row = await cur.fetchone()
    if not row:
        raise HTTPException(404, detail="Note not found")
    return row


def _build(row, content: str, contexts, tags) -> NoteResponse:
    return NoteResponse(
        id             = row["id"],
        title          = row["title"],
        filepath       = row["filepath"],
        content        = content,
        created_at     = row["created_at"],
        updated_at     = row["updated_at"],
        contexts       = contexts,
        tags           = tags,
        outgoing_links = md.extract_links(content),
    )


def _meta(note_id, title, created_str, tag_names, ctx_names) -> dict:
    return {
        "uuid":     note_id,
        "title":    title,
        "date":     created_str[:10],
        "tags":     tag_names,
        "contexts": ctx_names,
        "links":    [],
    }


# ── routes ────────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[NoteResponse])
async def list_notes(
    context_id: Optional[str] = None,
    tag:        Optional[str] = None,
    q:          Optional[str] = None,
    limit:      int = Query(50, ge=1, le=200),
    db: aiosqlite.Connection = Depends(get_db),
):
    where, params = ["1=1"], []
    if context_id:
        where.append(
            "o.id IN (SELECT object_id FROM object_contexts WHERE context_id = ?)"
        )
        params.append(context_id)
    if tag:
        where.append(
            "o.id IN (SELECT ot.object_id FROM object_tags ot "
            "JOIN tags tg ON tg.id = ot.tag_id WHERE tg.name = ?)"
        )
        params.append(tag.strip().lower())
    if q:
        where.append("o.title LIKE ?")
        params.append(f"%{q}%")
    params.append(limit)

    cur = await db.execute(
        f"{_SEL} WHERE {' AND '.join(where)} ORDER BY o.updated_at DESC LIMIT ?",
        params
    )
    rows = await cur.fetchall()
    results = []
    for row in rows:
        p = Path(row["filepath"])
        _, body = md.parse(p.read_text(encoding="utf-8") if p.exists() else "")
        contexts = await _contexts_of(row["id"], db)
        tags     = await _tags_of(row["id"], db)
        results.append(_build(row, body, contexts, tags))
    return results


@router.get("/{note_id}", response_model=NoteResponse)
async def get_note(note_id: str, db: aiosqlite.Connection = Depends(get_db)):
    row      = await _fetch_row(note_id, db)
    p        = Path(row["filepath"])
    _, body  = md.parse(p.read_text(encoding="utf-8") if p.exists() else "")
    contexts = await _contexts_of(note_id, db)
    tags     = await _tags_of(note_id, db)
    return _build(row, body, contexts, tags)


@router.post("/", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
async def create_note(payload: NoteCreate, db: aiosqlite.Connection = Depends(get_db)):
    cur = await db.execute("SELECT id FROM objects WHERE title = ?", (payload.title,))
    if await cur.fetchone():
        raise HTTPException(409, detail=f"Title already in use: '{payload.title}'")

    ctx_ids = await _validate_contexts(payload.context_ids, db)
    tag_ids = await _resolve_tags(payload.tag_names, db)

    note_id  = str(uuid.uuid4())
    now      = datetime.now(timezone.utc)
    now_iso  = now.isoformat()
    filepath = NOTES_DIR / md.note_filename(payload.title, now.date(), note_id[:8])

    cur = await db.execute(
        f"SELECT name FROM contexts WHERE id IN ({','.join('?'*len(ctx_ids))})", ctx_ids
    )
    ctx_names = [r["name"] for r in await cur.fetchall()]
    tag_names = [t.strip().lower() for t in payload.tag_names if t.strip()]

    ignore(filepath)
    md.write(filepath, _meta(note_id, payload.title, now_iso, tag_names, ctx_names),
             payload.content)

    try:
        await db.execute(
            "INSERT INTO objects (id,title,type,date,created_at,updated_at) "
            "VALUES (?,?,'note',?,?,?)",
            (note_id, payload.title, now.date().isoformat(), now_iso, now_iso)
        )
        await db.execute(
            "INSERT INTO notes (id,filepath) VALUES (?,?)", (note_id, str(filepath))
        )
        await _set_contexts(note_id, ctx_ids, db)
        await _set_tags(note_id, tag_ids, db)
        await sync_links(note_id, payload.content, db)
        await db.commit()
    except Exception:
        await db.rollback()
        filepath.unlink(missing_ok=True)
        raise

    row      = await _fetch_row(note_id, db)
    contexts = await _contexts_of(note_id, db)
    tags     = await _tags_of(note_id, db)
    return _build(row, payload.content, contexts, tags)


@router.patch("/{note_id}", response_model=NoteResponse)
async def update_note(
    note_id: str,
    payload: NoteUpdate,
    db: aiosqlite.Connection = Depends(get_db),
):
    row      = await _fetch_row(note_id, db)
    old_path = Path(row["filepath"])
    _, old_content = md.parse(old_path.read_text(encoding="utf-8") if old_path.exists() else "")

    new_title   = payload.title   if payload.title   is not None else row["title"]
    new_content = payload.content if payload.content is not None else old_content

    if new_title != row["title"]:
        cur = await db.execute(
            "SELECT id FROM objects WHERE title=? AND id!=?", (new_title, note_id)
        )
        if await cur.fetchone():
            raise HTTPException(409, detail=f"Title already in use: '{new_title}'")

    if payload.context_ids is not None:
        await _set_contexts(note_id, await _validate_contexts(payload.context_ids, db), db)
    if payload.tag_names is not None:
        await _set_tags(note_id, await _resolve_tags(payload.tag_names, db), db)

    # Rebuild frontmatter from current DB state (after any context/tag updates)
    cur = await db.execute(
        "SELECT c.name FROM contexts c JOIN object_contexts oc "
        "ON oc.context_id=c.id WHERE oc.object_id=?", (note_id,)
    )
    ctx_names = [r["name"] for r in await cur.fetchall()]
    cur = await db.execute(
        "SELECT tg.name FROM tags tg JOIN object_tags ot "
        "ON ot.tag_id=tg.id WHERE ot.object_id=?", (note_id,)
    )
    tag_names = [r["name"] for r in await cur.fetchall()]

    created_date = datetime.fromisoformat(row["created_at"]).date()
    new_path     = NOTES_DIR / md.note_filename(new_title, created_date, note_id[:8])
    now_iso      = datetime.now(timezone.utc).isoformat()

    new_meta = _meta(note_id, new_title, row["created_at"], tag_names, ctx_names)

    if new_path != old_path:
        ignore(old_path, new_path)
        md.write(new_path, new_meta, new_content)
        old_path.unlink(missing_ok=True)
        await db.execute("UPDATE notes SET filepath=? WHERE id=?",
                         (str(new_path), note_id))
    else:
        ignore(old_path)
        md.write(old_path, new_meta, new_content)

    if new_title != row["title"]:
        await propagate_rename(note_id, row["title"], new_title, db)
    await db.execute("UPDATE objects SET title=?, updated_at=? WHERE id=?",
                     (new_title, now_iso, note_id))
    await sync_links(note_id, new_content, db)
    await db.commit()

    row      = await _fetch_row(note_id, db)
    contexts = await _contexts_of(note_id, db)
    tags     = await _tags_of(note_id, db)
    return _build(row, new_content, contexts, tags)


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(note_id: str, db: aiosqlite.Connection = Depends(get_db)):
    row = await _fetch_row(note_id, db)
    p   = Path(row["filepath"])
    ignore(p)
    p.unlink(missing_ok=True)
    await db.execute("DELETE FROM objects WHERE id = ?", (note_id,))
    await db.commit()
