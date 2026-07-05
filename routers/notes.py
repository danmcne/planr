"""routers/notes.py"""
import uuid as _uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException

from db import db
from db_utils import sync_tags, sync_fts
from file_sync import write_note, rename_note_file
from models import NoteCreate, NoteUpdate

router = APIRouter(prefix="/api/notes", tags=["notes"])


@router.get("")
def list_notes(context_id: Optional[int] = None):
    with db() as conn:
        clauses, params = [], []
        if context_id:
            clauses.append("n.context_id = ?"); params.append(context_id)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(
            f"""SELECT n.uuid, n.title, n.context_id, n.created_at, n.modified_at,
                       substr(n.content,1,200) AS excerpt,
                       c.full_path AS context_path, c.color AS context_color,
                       rc.color AS root_color
                FROM notes n
                LEFT JOIN contexts c ON n.context_id = c.id
                LEFT JOIN contexts rc ON rc.full_path = CASE
        WHEN instr(c.full_path, '.') > 0 THEN substr(c.full_path, 1, instr(c.full_path, '.') - 1)
        ELSE c.full_path END
                {where} ORDER BY n.modified_at DESC""",
            params,
        ).fetchall()
        return [dict(r) for r in rows]


@router.post("")
def create_note(data: NoteCreate):
    uid = str(_uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    file_path, chash = write_note(uid, data.title, data.content, now)
    with db() as conn:
        conn.execute(
            """INSERT INTO notes
               (uuid,title,content,context_id,file_path,content_hash,created_at,modified_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (uid, data.title, data.content, data.context_id, file_path, chash, now, now),
        )
        sync_tags(conn, uid, "note", data.content)
        sync_fts(conn, uid, "note", data.title, data.content)
        return dict(conn.execute("SELECT * FROM notes WHERE uuid = ?", (uid,)).fetchone())


@router.get("/{note_uuid}")
def get_note(note_uuid: str):
    with db() as conn:
        row = conn.execute(
            """SELECT n.*, c.full_path AS context_path, c.color AS context_color
               FROM notes n LEFT JOIN contexts c ON n.context_id = c.id
               WHERE n.uuid = ?""",
            (note_uuid,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Note not found")
        return dict(row)


@router.put("/{note_uuid}")
def update_note(note_uuid: str, data: NoteUpdate):
    with db() as conn:
        existing = conn.execute("SELECT * FROM notes WHERE uuid = ?", (note_uuid,)).fetchone()
        if not existing:
            raise HTTPException(404, "Note not found")
        now = datetime.now(timezone.utc).isoformat()
        updates = data.model_dump(exclude_none=True)
        new_title   = updates.get("title",   existing["title"])
        new_content = updates.get("content", existing["content"])

        if "title" in updates and updates["title"] != existing["title"]:
            updates["file_path"] = rename_note_file(
                existing["file_path"] or "", note_uuid, new_title, existing["created_at"]
            )
        if "content" in updates:
            fp, chash = write_note(note_uuid, new_title, new_content, existing["created_at"])
            updates["file_path"]    = fp
            updates["content_hash"] = chash

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(
            f"UPDATE notes SET {set_clause}, modified_at = ? WHERE uuid = ?",
            list(updates.values()) + [now, note_uuid],
        )
        sync_tags(conn, note_uuid, "note", new_content)
        sync_fts(conn, note_uuid, "note", new_title, new_content)
        return dict(conn.execute("SELECT * FROM notes WHERE uuid = ?", (note_uuid,)).fetchone())


@router.delete("/{note_uuid}")
def delete_note(note_uuid: str):
    with db() as conn:
        existing = conn.execute("SELECT * FROM notes WHERE uuid = ?", (note_uuid,)).fetchone()
        if not existing:
            raise HTTPException(404, "Note not found")
        if existing["file_path"]:
            try:
                from pathlib import Path
                Path(existing["file_path"]).unlink(missing_ok=True)
            except Exception:
                pass
        conn.execute("DELETE FROM notes WHERE uuid = ?", (note_uuid,))
        conn.execute("DELETE FROM object_tags WHERE object_uuid = ?", (note_uuid,))
        conn.execute("DELETE FROM search_index WHERE uuid = ?", (note_uuid,))
        return {"deleted": note_uuid}
