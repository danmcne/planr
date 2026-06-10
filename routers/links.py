"""routers/links.py"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException

from db import db
from models import LinkCreate

router = APIRouter(prefix="/api/links", tags=["links"])


@router.get("")
def get_links(source_uuid: Optional[str] = None, target_uuid: Optional[str] = None):
    if not source_uuid and not target_uuid:
        raise HTTPException(400, "Provide source_uuid or target_uuid")
    with db() as conn:
        if source_uuid:
            rows = conn.execute(
                "SELECT * FROM links WHERE source_uuid = ?", (source_uuid,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM links WHERE target_uuid = ?", (target_uuid,)
            ).fetchall()
        return [dict(r) for r in rows]


@router.post("")
def create_link(data: LinkCreate):
    with db() as conn:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO links
               (source_uuid,source_type,target_uuid,target_type,target_ref,
                link_type,display_text,created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (data.source_uuid, data.source_type, data.target_uuid,
             data.target_type, data.target_ref, data.link_type,
             data.display_text, now),
        )
        lid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        return dict(conn.execute("SELECT * FROM links WHERE id = ?", (lid,)).fetchone())


@router.delete("/{link_id}")
def delete_link(link_id: int):
    with db() as conn:
        if not conn.execute("SELECT id FROM links WHERE id = ?", (link_id,)).fetchone():
            raise HTTPException(404, "Link not found")
        conn.execute("DELETE FROM links WHERE id = ?", (link_id,))
        return {"deleted": link_id}


@router.get("/targets")
def link_targets(q: str = "", object_type: str = "", limit: int = 10):
    """All linkable objects — used by wiki-link autocomplete.

    If the query starts with a digit (e.g. "[[2026" or "[[2026-06"), date
    fields are searched as well: journal entry_date, event start, task due.
    """
    with db() as conn:
        like = f"%{q}%" if q else "%"
        date_like = f"{q}%" if q and q[0].isdigit() else None
        results = []

        specs = [
            ("task",    "tasks",           "title",  "due_at"),
            ("event",   "events",          "title",  "start_at"),
            ("note",    "notes",           "title",  "created_at"),
            ("journal", "journal_entries",
             "COALESCE(NULLIF(title,''), entry_date)", "entry_date"),
        ]
        for type_name, table, title_col, date_col in specs:
            if object_type and object_type != type_name:
                continue
            extra = "AND status != 'done'" if table == "tasks" else ""
            where = f"{title_col} LIKE ?"
            params: list = [like]
            if date_like:
                where = f"({where} OR {date_col} LIKE ?)"
                params.append(date_like)
            rows = conn.execute(
                f"SELECT uuid, '{type_name}' AS type, {title_col} AS title, "
                f"substr({date_col},1,10) AS date "
                f"FROM {table} WHERE {where} {extra} "
                f"ORDER BY modified_at DESC LIMIT ?",
                params + [limit],
            ).fetchall()
            results.extend(dict(r) for r in rows)

        return results


@router.get("/resolve/{short_uuid}")
def resolve_link(short_uuid: str):
    with db() as conn:
        for table, type_name in (
            ("tasks",           "task"),
            ("events",          "event"),
            ("notes",           "note"),
            ("journal_entries", "journal"),
        ):
            row = conn.execute(
                f"SELECT uuid, title FROM {table} WHERE uuid LIKE ?",
                (short_uuid + "%",),
            ).fetchone()
            if row:
                return {"uuid": row["uuid"], "type": type_name, "title": row["title"]}
    raise HTTPException(404, "Object not found")
