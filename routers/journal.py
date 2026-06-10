"""routers/journal.py"""
import uuid as _uuid
from datetime import datetime, timezone, date
from typing import Optional

from fastapi import APIRouter, HTTPException

from db import db
from db_utils import sync_tags, sync_fts
from file_sync import write_journal
from models import JournalCreate, JournalUpdate

router = APIRouter(prefix="/api/journal", tags=["journal"])


@router.get("")
def list_entries(year: Optional[int] = None, month: Optional[int] = None, limit: int = 60):
    with db() as conn:
        clauses, params = [], []
        if year:
            clauses.append("strftime('%Y', entry_date) = ?"); params.append(str(year))
        if month:
            clauses.append("strftime('%m', entry_date) = ?"); params.append(f"{month:02d}")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(
            f"""SELECT uuid, title, entry_date, created_at, modified_at,
                       substr(content,1,200) AS excerpt
                FROM journal_entries {where}
                ORDER BY entry_date DESC LIMIT ?""",
            params + [limit],
        ).fetchall()
        return [dict(r) for r in rows]


@router.get("/today")
def get_or_create_today():
    today = date.today().isoformat()
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM journal_entries WHERE entry_date = ?", (today,)
        ).fetchone()
        if row:
            return dict(row)
        uid = str(_uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        fp, chash = write_journal(uid, "", "", today, now)
        conn.execute(
            """INSERT INTO journal_entries
               (uuid,title,content,entry_date,file_path,content_hash,created_at,modified_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (uid, "", "", today, fp, chash, now, now),
        )
        return dict(conn.execute(
            "SELECT * FROM journal_entries WHERE uuid = ?", (uid,)
        ).fetchone())


@router.get("/{entry_uuid}")
def get_entry(entry_uuid: str):
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM journal_entries WHERE uuid = ?", (entry_uuid,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Journal entry not found")
        return dict(row)


@router.post("")
def create_entry(data: JournalCreate):
    uid        = str(_uuid.uuid4())
    now        = datetime.now(timezone.utc).isoformat()
    entry_date = data.entry_date or date.today().isoformat()
    fp, chash  = write_journal(uid, data.title, data.content, entry_date, now)
    with db() as conn:
        conn.execute(
            """INSERT INTO journal_entries
               (uuid,title,content,context_id,entry_date,file_path,content_hash,created_at,modified_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (uid, data.title, data.content, data.context_id, entry_date, fp, chash, now, now),
        )
        sync_tags(conn, uid, "journal", data.content)
        sync_fts(conn, uid, "journal", data.title or entry_date, data.content)
        return dict(conn.execute(
            "SELECT * FROM journal_entries WHERE uuid = ?", (uid,)
        ).fetchone())


@router.put("/{entry_uuid}")
def update_entry(entry_uuid: str, data: JournalUpdate):
    with db() as conn:
        existing = conn.execute(
            "SELECT * FROM journal_entries WHERE uuid = ?", (entry_uuid,)
        ).fetchone()
        if not existing:
            raise HTTPException(404, "Journal entry not found")
        now         = datetime.now(timezone.utc).isoformat()
        updates     = data.model_dump(exclude_none=True)
        new_title   = updates.get("title",   existing["title"])
        new_content = updates.get("content", existing["content"])
        fp, chash   = write_journal(
            entry_uuid, new_title, new_content,
            existing["entry_date"], existing["created_at"]
        )
        updates["file_path"]    = fp
        updates["content_hash"] = chash
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(
            f"UPDATE journal_entries SET {set_clause}, modified_at = ? WHERE uuid = ?",
            list(updates.values()) + [now, entry_uuid],
        )
        sync_tags(conn, entry_uuid, "journal", new_content)
        sync_fts(conn, entry_uuid, "journal",
                 new_title or existing["entry_date"], new_content)
        return dict(conn.execute(
            "SELECT * FROM journal_entries WHERE uuid = ?", (entry_uuid,)
        ).fetchone())


@router.delete("/{entry_uuid}")
def delete_entry(entry_uuid: str):
    with db() as conn:
        existing = conn.execute(
            "SELECT * FROM journal_entries WHERE uuid = ?", (entry_uuid,)
        ).fetchone()
        if not existing:
            raise HTTPException(404, "Journal entry not found")
        if existing["file_path"]:
            try:
                from pathlib import Path
                Path(existing["file_path"]).unlink(missing_ok=True)
            except Exception:
                pass
        conn.execute("DELETE FROM journal_entries WHERE uuid = ?", (entry_uuid,))
        conn.execute("DELETE FROM object_tags WHERE object_uuid = ?", (entry_uuid,))
        conn.execute("DELETE FROM search_index WHERE uuid = ?", (entry_uuid,))
        return {"deleted": entry_uuid}
