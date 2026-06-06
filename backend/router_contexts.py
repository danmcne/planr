"""
Context routes.

  GET    /api/contexts           list all
  POST   /api/contexts           create
  PATCH  /api/contexts/{id}      rename / recolor / reparent
  DELETE /api/contexts/{id}      delete (blocked if system or last remaining)
"""

from __future__ import annotations

import uuid
from typing import List

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, status

from db import get_db
from model_context import ContextCreate, ContextResponse, ContextUpdate

router = APIRouter(prefix="/contexts", tags=["contexts"])


async def _enrich(row: aiosqlite.Row, db: aiosqlite.Connection) -> ContextResponse:
    cur = await db.execute(
        "SELECT COUNT(*) as n FROM contexts WHERE parent_id = ?", (row["id"],)
    )
    cnt = (await cur.fetchone())["n"]
    return ContextResponse(
        id=row["id"],
        name=row["name"],
        parent_id=row["parent_id"],
        color=row["color"],
        is_system=bool(row["is_system"]),
        subcontext_count=cnt,
        default_for=row["default_for"] if "default_for" in row.keys() else None,
    )


async def _get_or_404(context_id: str, db: aiosqlite.Connection) -> aiosqlite.Row:
    cur = await db.execute("SELECT * FROM contexts WHERE id = ?", (context_id,))
    row = await cur.fetchone()
    if not row:
        raise HTTPException(404, detail="Context not found")
    return row


@router.get("/", response_model=List[ContextResponse])
async def list_contexts(db: aiosqlite.Connection = Depends(get_db)):
    cur = await db.execute("SELECT * FROM contexts ORDER BY name")
    return [await _enrich(r, db) for r in await cur.fetchall()]


@router.post("/", response_model=ContextResponse, status_code=status.HTTP_201_CREATED)
async def create_context(payload: ContextCreate, db: aiosqlite.Connection = Depends(get_db)):
    cur = await db.execute("SELECT id FROM contexts WHERE name = ?", (payload.name,))
    if await cur.fetchone():
        raise HTTPException(409, detail=f"Name already in use: '{payload.name}'")

    if payload.parent_id:
        cur = await db.execute("SELECT id FROM contexts WHERE id = ?", (payload.parent_id,))
        if not await cur.fetchone():
            raise HTTPException(422, detail="parent_id not found")

    ctx_id = f"ctx-{str(uuid.uuid4())[:8]}"
    await db.execute(
        "INSERT INTO contexts (id, name, parent_id, color, is_system) VALUES (?, ?, ?, ?, 0)",
        (ctx_id, payload.name, payload.parent_id, payload.color)
    )
    await db.commit()

    cur = await db.execute("SELECT * FROM contexts WHERE id = ?", (ctx_id,))
    return await _enrich(await cur.fetchone(), db)


@router.patch("/{context_id}", response_model=ContextResponse)
async def update_context(
    context_id: str,
    payload: ContextUpdate,
    db: aiosqlite.Connection = Depends(get_db),
):
    row = await _get_or_404(context_id, db)
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        return await _enrich(row, db)

    if "name" in updates:
        cur = await db.execute(
            "SELECT id FROM contexts WHERE name = ? AND id != ?",
            (updates["name"], context_id)
        )
        if await cur.fetchone():
            raise HTTPException(409, detail=f"Name already in use: '{updates['name']}'")

    cols = ", ".join(f"{k} = ?" for k in updates)
    await db.execute(
        f"UPDATE contexts SET {cols} WHERE id = ?", (*updates.values(), context_id)
    )
    await db.commit()

    cur = await db.execute("SELECT * FROM contexts WHERE id = ?", (context_id,))
    return await _enrich(await cur.fetchone(), db)


@router.post("/{context_id}/set-default", response_model=ContextResponse)
async def set_default_context(
    context_id: str,
    db: aiosqlite.Connection = Depends(get_db),
    for_type: str = "tasks",   # query param: 'tasks' or 'notes'
):
    """Make this context the default for new tasks (or notes/journal).
    Clears any previous default for that type first.
    """
    if for_type not in ("tasks", "notes"):
        raise HTTPException(422, detail="for_type must be 'tasks' or 'notes'")
    await _get_or_404(context_id, db)
    # Clear existing default for this type
    await db.execute(
        "UPDATE contexts SET default_for = NULL WHERE default_for = ?", (for_type,)
    )
    await db.execute(
        "UPDATE contexts SET default_for = ? WHERE id = ?", (for_type, context_id)
    )
    await db.commit()
    cur = await db.execute("SELECT * FROM contexts WHERE id = ?", (context_id,))
    return await _enrich(await cur.fetchone(), db)


@router.delete("/{context_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_context(context_id: str, db: aiosqlite.Connection = Depends(get_db)):
    row = await _get_or_404(context_id, db)

    if row["is_system"]:
        raise HTTPException(403, detail="System contexts cannot be deleted")

    # Re-home any objects that will be left contextless after this delete.
    # Tasks/events go to Inbox; notes/journal go to Uncategorized.
    cur = await db.execute(
        """SELECT o.id, o.type FROM objects o
           JOIN object_contexts oc ON oc.object_id = o.id
           WHERE oc.context_id = ?
             AND NOT EXISTS (
               SELECT 1 FROM object_contexts oc2
               WHERE oc2.object_id = o.id AND oc2.context_id != ?
             )""",
        (context_id, context_id),
    )
    orphans = await cur.fetchall()
    for obj in orphans:
        # Use configured default context for the type, fall back to system defaults
        is_note_type = obj["type"] in ("note", "journal")
        cur2 = await db.execute(
            "SELECT id FROM contexts WHERE default_for = ?",
            ("notes" if is_note_type else "tasks",),
        )
        dflt_row = await cur2.fetchone()
        fallback = dflt_row["id"] if dflt_row else (
            "ctx-uncategorized" if is_note_type else "ctx-inbox"
        )
        await db.execute(
            "INSERT OR IGNORE INTO object_contexts (object_id, context_id) VALUES (?, ?)",
            (obj["id"], fallback),
        )

    await db.execute("DELETE FROM contexts WHERE id = ?", (context_id,))
    await db.commit()
