"""routers/contexts.py"""
from typing import Optional

from fastapi import APIRouter, HTTPException

from db import db
from models import ContextCreate, ContextUpdate

router = APIRouter(prefix="/api/contexts", tags=["contexts"])


def _build_path(conn, name: str, parent_id: Optional[int]) -> str:
    slug = name.lower().replace(" ", "_")
    if not parent_id:
        return slug
    parent = conn.execute(
        "SELECT full_path FROM contexts WHERE id = ?", (parent_id,)
    ).fetchone()
    return f"{parent['full_path']}.{slug}" if parent else slug


def _next_sort_order(conn, parent_id: Optional[int]) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(sort_order), -1) FROM contexts WHERE parent_id IS ?",
        (parent_id,),
    ).fetchone()
    return (row[0] or 0) + 1


@router.get("")
def list_contexts():
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM contexts ORDER BY full_path ASC"
        ).fetchall()
        return [dict(r) for r in rows]


@router.post("")
def create_context(data: ContextCreate):
    with db() as conn:
        full_path = _build_path(conn, data.name, data.parent_id)
        if conn.execute(
            "SELECT id FROM contexts WHERE full_path = ?", (full_path,)
        ).fetchone():
            raise HTTPException(409, "Context path already exists")
        sort_order = data.sort_order if data.sort_order else _next_sort_order(conn, data.parent_id)
        conn.execute(
            "INSERT INTO contexts (name, parent_id, full_path, color, sort_order) VALUES (?,?,?,?,?)",
            (data.name, data.parent_id, full_path, data.color, sort_order),
        )
        cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        return dict(conn.execute("SELECT * FROM contexts WHERE id = ?", (cid,)).fetchone())


@router.put("/{ctx_id}")
def update_context(ctx_id: int, data: ContextUpdate):
    with db() as conn:
        existing = conn.execute("SELECT * FROM contexts WHERE id = ?", (ctx_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "Context not found")
        updates = data.model_dump(exclude_none=True)
        if not updates:
            return dict(existing)

        if "name" in updates:
            new_path = _build_path(conn, updates["name"], existing["parent_id"])
            old_path = existing["full_path"]
            updates["full_path"] = new_path
            # cascade rename to children
            children = conn.execute(
                "SELECT id, full_path FROM contexts WHERE full_path LIKE ?",
                (old_path + ".%",),
            ).fetchall()
            for child in children:
                conn.execute(
                    "UPDATE contexts SET full_path = ? WHERE id = ?",
                    (child["full_path"].replace(old_path, new_path, 1), child["id"]),
                )

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(
            f"UPDATE contexts SET {set_clause} WHERE id = ?",
            list(updates.values()) + [ctx_id],
        )
        return dict(conn.execute("SELECT * FROM contexts WHERE id = ?", (ctx_id,)).fetchone())


@router.delete("/{ctx_id}")
def delete_context(ctx_id: int):
    with db() as conn:
        if not conn.execute("SELECT id FROM contexts WHERE id = ?", (ctx_id,)).fetchone():
            raise HTTPException(404, "Context not found")
        if conn.execute(
            "SELECT id FROM contexts WHERE parent_id = ?", (ctx_id,)
        ).fetchone():
            raise HTTPException(400, "Cannot delete a context that has children")
        for tbl in ("tasks", "events", "notes", "journal_entries"):
            conn.execute(f"UPDATE {tbl} SET context_id = NULL WHERE context_id = ?", (ctx_id,))
        conn.execute("DELETE FROM contexts WHERE id = ?", (ctx_id,))
        return {"deleted": ctx_id}
