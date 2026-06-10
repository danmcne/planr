"""routers/search.py — FTS5 search with context/date/status filters"""
from typing import Optional

from fastapi import APIRouter

from db import db

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("")
def search(
    q: str = "",
    obj_type: Optional[str] = None,
    context_id: Optional[int] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 40,
):
    with db() as conn:
        results = []

        if q.strip():
            # FTS5 text search. Quote the query as a phrase: bare "-", ":" etc.
            # are FTS operators and would raise a syntax error (e.g. "2026-06").
            fts_q = '"' + q.strip().replace('"', '""') + '"*'
            fts_clauses = ["search_index MATCH ?"]
            fts_params  = [fts_q]
            if obj_type:
                fts_clauses.append("si.type = ?"); fts_params.append(obj_type)
            where = " AND ".join(fts_clauses)
            rows = conn.execute(
                f"""SELECT si.uuid, si.type, si.title,
                           snippet(search_index,3,'<mark>','</mark>','…',24) AS snippet,
                           rank
                    FROM search_index si
                    WHERE {where}
                    ORDER BY rank LIMIT ?""",
                fts_params + [limit],
            ).fetchall()
            results = [dict(r) for r in rows]

            # Date-like query (e.g. "2026", "2026-06", "2026-06-12") — also
            # match date fields, which FTS does not index.
            if q.strip()[0].isdigit():
                dq = q.strip() + "%"
                date_specs = [
                    ("task",    "tasks",           "title", "due_at"),
                    ("event",   "events",          "title", "start_at"),
                    ("journal", "journal_entries",
                     "COALESCE(NULLIF(title,''), entry_date)", "entry_date"),
                ]
                seen = {r["uuid"] for r in results}
                for type_name, table, title_col, date_col in date_specs:
                    if obj_type and obj_type != type_name:
                        continue
                    rows = conn.execute(
                        f"SELECT uuid, '{type_name}' AS type, {title_col} AS title, "
                        f"substr({date_col},1,10) AS snippet, 0 AS rank "
                        f"FROM {table} WHERE {date_col} LIKE ? "
                        f"ORDER BY {date_col} DESC LIMIT ?",
                        (dq, limit),
                    ).fetchall()
                    results.extend(dict(r) for r in rows if r["uuid"] not in seen)
        else:
            # No text query — fall through to filter-only search
            if not any([obj_type, context_id, status, date_from, date_to]):
                return []
            # Return recent objects matching filters
            for tbl, type_name in [("tasks","task"),("events","event"),
                                    ("notes","note"),("journal_entries","journal")]:
                if obj_type and obj_type != type_name:
                    continue
                rows = conn.execute(
                    f"SELECT uuid, '{type_name}' AS type, title, '' AS snippet, 0 AS rank "
                    f"FROM {tbl} ORDER BY modified_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                results.extend(dict(r) for r in rows)

        # Enrich and filter
        enriched = []
        for r in results:
            extra = {}
            ctx_match = True

            if r["type"] == "task":
                row = conn.execute(
                    "SELECT status,due_at,importance,priority_score,context_id FROM tasks WHERE uuid=?",
                    (r["uuid"],),
                ).fetchone()
                if row:
                    extra = dict(row)
                    if status and extra.get("status") != status:
                        continue
                    if context_id and extra.get("context_id") != context_id:
                        continue
                    if date_from and extra.get("due_at") and extra["due_at"][:10] < date_from:
                        continue
                    if date_to and extra.get("due_at") and extra["due_at"][:10] > date_to:
                        continue

            elif r["type"] == "event":
                row = conn.execute(
                    "SELECT start_at,context_id FROM events WHERE uuid=?", (r["uuid"],)
                ).fetchone()
                if row:
                    extra = dict(row)
                    if context_id and extra.get("context_id") != context_id:
                        continue
                    if date_from and extra.get("start_at") and extra["start_at"][:10] < date_from:
                        continue
                    if date_to and extra.get("start_at") and extra["start_at"][:10] > date_to:
                        continue

            elif r["type"] == "note":
                row = conn.execute(
                    "SELECT modified_at,context_id FROM notes WHERE uuid=?", (r["uuid"],)
                ).fetchone()
                if row:
                    extra = dict(row)
                    if context_id and extra.get("context_id") != context_id:
                        continue

            elif r["type"] == "journal":
                row = conn.execute(
                    "SELECT entry_date,context_id FROM journal_entries WHERE uuid=?", (r["uuid"],)
                ).fetchone()
                if row:
                    extra = dict(row)
                    if context_id and extra.get("context_id") != context_id:
                        continue
                    if date_from and extra["entry_date"] < date_from:
                        continue
                    if date_to and extra["entry_date"] > date_to:
                        continue

            enriched.append({**r, **extra})

        return enriched[:limit]


@router.get("/tags")
def list_tags(limit: int = 60):
    with db() as conn:
        rows = conn.execute(
            "SELECT name,usage_count,last_used_at FROM tags ORDER BY usage_count DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
