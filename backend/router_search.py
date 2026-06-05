# backend/router_search.py
"""
Global search route.

  GET /api/search?q=&types=task,event,note,journal&limit=20

Searches object titles first (fast), then task/event descriptions.
Note and journal content search happens via the watcher-maintained DB
(title search covers most use cases; content search is a phase 5+ item).
"""

from typing import List, Optional

import aiosqlite
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from db import get_db

router = APIRouter(prefix='/search', tags=['search'])


class SearchResult(BaseModel):
    id:      str
    title:   str
    type:    str
    snippet: Optional[str] = None    # excerpt showing matched text (descriptions only)


@router.get('/', response_model=List[SearchResult])
async def search(
    q:      str = Query(..., min_length=1),
    types:  Optional[str] = Query(None, description='Comma-separated: task,event,note,journal'),
    limit:  int = Query(20, ge=1, le=100),
    db: aiosqlite.Connection = Depends(get_db),
):
    like = f'%{q}%'
    allowed = set(types.split(',')) if types else {'task', 'event', 'note', 'journal'}
    type_ph = ','.join('?' * len(allowed))

    # ── title search across all matching types ────────────────────────────────
    cur = await db.execute(
        f"SELECT id, title, type FROM objects "
        f"WHERE title LIKE ? COLLATE NOCASE AND type IN ({type_ph}) "
        f"ORDER BY updated_at DESC LIMIT ?",
        (like, *allowed, limit)
    )
    results = [
        SearchResult(id=r['id'], title=r['title'], type=r['type'])
        for r in await cur.fetchall()
    ]
    found = {r.id for r in results}
    remaining = limit - len(results)

    # ── description search (tasks + events) ───────────────────────────────────
    for table, otype in (('tasks', 'task'), ('events', 'event')):
        if remaining <= 0 or otype not in allowed:
            continue
        exc = ','.join('?' * len(found)) if found else 'SELECT NULL WHERE 1=0'
        cur = await db.execute(
            f"SELECT o.id, o.title, o.type, t.description "
            f"FROM objects o JOIN {table} t ON t.id = o.id "
            f"WHERE t.description LIKE ? COLLATE NOCASE "
            f"  AND o.id NOT IN ({exc}) "
            f"LIMIT ?",
            (like, *found, remaining)
        )
        for r in await cur.fetchall():
            desc = r['description'] or ''
            idx  = desc.lower().find(q.lower())
            snip = ('…' + desc[max(0, idx - 30):idx + 60].strip() + '…') if idx >= 0 else None
            results.append(SearchResult(id=r['id'], title=r['title'],
                                         type=r['type'], snippet=snip))
            found.add(r['id'])
            remaining -= 1

    return results[:limit]
