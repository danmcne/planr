# backend/journal.py
"""
Journal routes. One entry per calendar day.

  GET    /api/journal                   list (chronological, no content body)
  GET    /api/journal/date/{YYYY-MM-DD} get by date
  GET    /api/journal/{id}              get by UUID
  POST   /api/journal                   create entry for a given date
  PATCH  /api/journal/{id}              update content / title / tags / contexts
  DELETE /api/journal/{id}              delete .md file + DB cascade
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import List, Optional

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, status

from config import JOURNAL_DIR
from db import get_db
from model_journal import ContextSummary, JournalCreate, JournalResponse, JournalUpdate
import service_markdown as md
from service_watcher import ignore
from service_links import sync_links, propagate_rename

router = APIRouter(prefix="/journal", tags=["journal"])

_SEL = """
    SELECT o.id, o.title, o.created_at, o.updated_at,
           j.entry_date, j.filepath
    FROM objects o JOIN journal_entries j ON j.id = o.id
"""


# ── helpers ───────────────────────────────────────────────────────────────────

async def _contexts_of(jid: str, db) -> List[ContextSummary]:
    cur = await db.execute(
        "SELECT c.id, c.name, c.color FROM contexts c "
        "JOIN object_contexts oc ON oc.context_id = c.id WHERE oc.object_id = ?", (jid,)
    )
    return [ContextSummary(id=r["id"], name=r["name"], color=r["color"])
            for r in await cur.fetchall()]


async def _tags_of(jid: str, db) -> List[str]:
    cur = await db.execute(
        "SELECT tg.name FROM tags tg JOIN object_tags ot ON ot.tag_id = tg.id "
        "WHERE ot.object_id = ?", (jid,)
    )
    return [r["name"] for r in await cur.fetchall()]


async def _validate_contexts(ctx_ids, db):
    if not ctx_ids:
        return ["ctx-uncategorized"]
    ph = ",".join("?" * len(ctx_ids))
    cur = await db.execute(f"SELECT id FROM contexts WHERE id IN ({ph})", ctx_ids)
    found = {r["id"] for r in await cur.fetchall()}
    missing = set(ctx_ids) - found
    if missing:
        raise HTTPException(422, detail=f"Unknown context IDs: {sorted(missing)}")
    return ctx_ids


async def _resolve_tags(names, db):
    ids: List[str] = []
    for raw in names:
        name = raw.strip().lower()
        if not name:
            continue
        cur = await db.execute("SELECT id FROM tags WHERE name = ?", (name,))
        row = await cur.fetchone()
        ids.append(row["id"] if row else str(uuid.uuid4()))
        if not row:
            await db.execute("INSERT INTO tags (id, name) VALUES (?,?)", (ids[-1], name))
    return ids


async def _set_contexts(jid, ctx_ids, db):
    await db.execute("DELETE FROM object_contexts WHERE object_id = ?", (jid,))
    for cid in ctx_ids:
        await db.execute(
            "INSERT OR IGNORE INTO object_contexts VALUES (?,?)", (jid, cid)
        )


async def _set_tags(jid, tag_ids, db):
    await db.execute("DELETE FROM object_tags WHERE object_id = ?", (jid,))
    for tid in tag_ids:
        await db.execute(
            "INSERT OR IGNORE INTO object_tags VALUES (?,?)", (jid, tid)
        )


async def _fetch_row(jid: str, db) -> aiosqlite.Row:
    cur = await db.execute(_SEL + "WHERE o.id = ?", (jid,))
    row = await cur.fetchone()
    if not row:
        raise HTTPException(404, detail="Journal entry not found")
    return row


def _build(row, content: str, contexts, tags) -> JournalResponse:
    return JournalResponse(
        id             = row["id"],
        entry_date     = date.fromisoformat(row["entry_date"]),
        title          = row["title"] or None,
        filepath       = row["filepath"],
        content        = content,
        created_at     = row["created_at"],
        updated_at     = row["updated_at"],
        contexts       = contexts,
        tags           = tags,
        outgoing_links = md.extract_links(content),
    )


def _make_meta(jid, entry_date_str, title, tag_names, ctx_names) -> dict:
    m = {
        "uuid":     jid,
        "date":     entry_date_str,
        "tags":     tag_names,
        "contexts": ctx_names,
        "links":    [],
    }
    if title:
        m["title"] = title
    return m


# ── routes ────────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[JournalResponse])
async def list_journal(
    year:  Optional[int] = None,
    month: Optional[int] = None,
    limit: int = Query(31, ge=1, le=366),
    db: aiosqlite.Connection = Depends(get_db),
):
    where, params = ["1=1"], []
    if year and month:
        where.append("j.entry_date LIKE ?")
        params.append(f"{year}-{month:02d}-%")
    elif year:
        where.append("j.entry_date LIKE ?")
        params.append(f"{year}-%")
    params.append(limit)

    cur = await db.execute(
        f"{_SEL} WHERE {' AND '.join(where)} ORDER BY j.entry_date DESC LIMIT ?",
        params
    )
    rows = await cur.fetchall()
    results = []
    for row in rows:
        p = Path(row["filepath"])
        _, body = md.parse(p.read_text(encoding="utf-8") if p.exists() else "")
        results.append(_build(row, body,
                              await _contexts_of(row["id"], db),
                              await _tags_of(row["id"], db)))
    return results


@router.get("/date/{entry_date}", response_model=JournalResponse)
async def get_by_date(entry_date: date, db: aiosqlite.Connection = Depends(get_db)):
    cur = await db.execute(_SEL + "WHERE j.entry_date = ?", (entry_date.isoformat(),))
    row = await cur.fetchone()
    if not row:
        raise HTTPException(404, detail=f"No journal entry for {entry_date}")
    p = Path(row["filepath"])
    _, body = md.parse(p.read_text(encoding="utf-8") if p.exists() else "")
    return _build(row, body,
                  await _contexts_of(row["id"], db),
                  await _tags_of(row["id"], db))


@router.get("/{journal_id}", response_model=JournalResponse)
async def get_journal(journal_id: str, db: aiosqlite.Connection = Depends(get_db)):
    row = await _fetch_row(journal_id, db)
    p   = Path(row["filepath"])
    _, body = md.parse(p.read_text(encoding="utf-8") if p.exists() else "")
    return _build(row, body,
                  await _contexts_of(journal_id, db),
                  await _tags_of(journal_id, db))


@router.post("/", response_model=JournalResponse, status_code=status.HTTP_201_CREATED)
async def create_journal(payload: JournalCreate, db: aiosqlite.Connection = Depends(get_db)):
    cur = await db.execute(
        "SELECT id FROM journal_entries WHERE entry_date = ?",
        (payload.entry_date.isoformat(),)
    )
    if await cur.fetchone():
        raise HTTPException(409, detail=f"Entry already exists for {payload.entry_date}")

    ctx_ids = await _validate_contexts(payload.context_ids, db)
    tag_ids = await _resolve_tags(payload.tag_names, db)

    jid      = str(uuid.uuid4())
    now      = datetime.now(timezone.utc)
    now_iso  = now.isoformat()
    filepath = JOURNAL_DIR / md.journal_filename(payload.entry_date, payload.title)

    # objects.title is "Journal YYYY-MM-DD [— optional title]"
    obj_title = f"Journal {payload.entry_date}"
    if payload.title:
        obj_title += f" \u2014 {payload.title}"

    cur = await db.execute("SELECT id FROM objects WHERE title = ?", (obj_title,))
    if await cur.fetchone():
        raise HTTPException(409, detail=f"Object title conflict: '{obj_title}'")

    cur = await db.execute(
        f"SELECT name FROM contexts WHERE id IN ({','.join('?'*len(ctx_ids))})", ctx_ids
    )
    ctx_names = [r["name"] for r in await cur.fetchall()]
    tag_names = [t.strip().lower() for t in payload.tag_names if t.strip()]

    ignore(filepath)
    md.write(filepath,
             _make_meta(jid, payload.entry_date.isoformat(), payload.title,
                        tag_names, ctx_names),
             payload.content)

    try:
        await db.execute(
            "INSERT INTO objects (id,title,type,date,created_at,updated_at) "
            "VALUES (?,?,'journal',?,?,?)",
            (jid, obj_title, payload.entry_date.isoformat(), now_iso, now_iso)
        )
        await db.execute(
            "INSERT INTO journal_entries (id,entry_date,filepath) VALUES (?,?,?)",
            (jid, payload.entry_date.isoformat(), str(filepath))
        )
        await _set_contexts(jid, ctx_ids, db)
        await _set_tags(jid, tag_ids, db)
        await sync_links(jid, payload.content, db)
        await db.commit()
    except Exception:
        await db.rollback()
        filepath.unlink(missing_ok=True)
        raise

    row = await _fetch_row(jid, db)
    return _build(row, payload.content,
                  await _contexts_of(jid, db),
                  await _tags_of(jid, db))


@router.patch("/{journal_id}", response_model=JournalResponse)
async def update_journal(
    journal_id: str,
    payload: JournalUpdate,
    db: aiosqlite.Connection = Depends(get_db),
):
    row      = await _fetch_row(journal_id, db)
    old_path = Path(row["filepath"])
    # Save original file bytes for restoration if the DB update fails.
    old_file_text = old_path.read_text(encoding="utf-8") if old_path.exists() else ""
    _, old_content = md.parse(old_file_text) if old_file_text else ({}, "")

    new_content = payload.content if payload.content is not None else old_content
    new_title   = payload.title   if payload.title   is not None else (row["title"] or None)

    if payload.context_ids is not None:
        await _set_contexts(journal_id,
                            await _validate_contexts(payload.context_ids, db), db)
    if payload.tag_names is not None:
        await _set_tags(journal_id, await _resolve_tags(payload.tag_names, db), db)

    cur = await db.execute(
        "SELECT c.name FROM contexts c JOIN object_contexts oc "
        "ON oc.context_id=c.id WHERE oc.object_id=?", (journal_id,)
    )
    ctx_names = [r["name"] for r in await cur.fetchall()]
    cur = await db.execute(
        "SELECT tg.name FROM tags tg JOIN object_tags ot "
        "ON ot.tag_id=tg.id WHERE ot.object_id=?", (journal_id,)
    )
    tag_names = [r["name"] for r in await cur.fetchall()]

    entry_date = date.fromisoformat(row["entry_date"])
    new_path   = JOURNAL_DIR / md.journal_filename(entry_date, new_title)
    now_iso    = datetime.now(timezone.utc).isoformat()

    new_meta   = _make_meta(journal_id, row["entry_date"], new_title, tag_names, ctx_names)
    obj_title  = f"Journal {entry_date}" + (f" \u2014 {new_title}" if new_title else "")

    file_written  = False
    file_replaced = False
    try:
        if new_path != old_path:
            ignore(old_path, new_path)
            md.write(new_path, new_meta, new_content)
            file_written = True
            old_path.unlink(missing_ok=True)
            file_replaced = True
            await db.execute("UPDATE journal_entries SET filepath=? WHERE id=?",
                             (str(new_path), journal_id))
        else:
            ignore(old_path)
            md.write(old_path, new_meta, new_content)
            file_written = True

        old_obj_title = row["title"]
        if obj_title != old_obj_title:
            await propagate_rename(journal_id, old_obj_title, obj_title, db)
        await db.execute("UPDATE objects SET title=?, updated_at=? WHERE id=?",
                         (obj_title, now_iso, journal_id))
        await sync_links(journal_id, new_content, db)
        await db.commit()
    except Exception:
        await db.rollback()
        if file_written and old_file_text:
            try:
                if file_replaced:
                    ignore(old_path, new_path)
                    old_path.write_text(old_file_text, encoding="utf-8")
                    new_path.unlink(missing_ok=True)
                else:
                    ignore(old_path)
                    old_path.write_text(old_file_text, encoding="utf-8")
            except Exception:
                pass
        raise

    row = await _fetch_row(journal_id, db)
    return _build(row, new_content,
                  await _contexts_of(journal_id, db),
                  await _tags_of(journal_id, db))


@router.delete("/{journal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_journal(journal_id: str, db: aiosqlite.Connection = Depends(get_db)):
    row = await _fetch_row(journal_id, db)
    p   = Path(row["filepath"])
    ignore(p)
    p.unlink(missing_ok=True)
    await db.execute("DELETE FROM objects WHERE id = ?", (journal_id,))
    await db.commit()
