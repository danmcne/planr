# backend/links.py
"""
Link management for Planr.

Three public functions — call them from any router that writes content:

  sync_links(source_id, content, db)
      Extract [[Title]] refs from content, resolve to UUIDs, rebuild
      the links table rows for this source.  Call after every content write.

  propagate_rename(object_id, old_title, new_title, db)
      Replace [[old_title]] with [[new_title]] everywhere it appears:
        · notes/.md and journal/.md files (filesystem write)
        · tasks.description and events.description (DB update)
      Call before committing any title change.  Returns the number of
      objects whose content was updated.

  title_completions(partial, db, limit)
      Return objects whose title contains `partial` (case-insensitive).
      Used for [[T...]] autocomplete in the frontend editor.
"""

from __future__ import annotations

import uuid
import re
from pathlib import Path
from typing import List, Tuple

import aiosqlite

from service_markdown import extract_links as _extract_links

_URL_RE = re.compile(
    r'https?://[^\s\)\]\'"<>]+'
)

# Typed link prefix: [[task:Title]], [[event:Title]], [[note:Title]], [[journal:Title]]
# web: and file: are external — not object titles.
_TYPED_PREFIX_RE = re.compile(r'^(task|event|note|journal):(.+)$', re.IGNORECASE)


def _resolve_link_title(raw: str):
    """Strip optional type:title prefix for internal link resolution.

    Returns the bare title to search in the objects table, or None when the
    prefix marks an external reference (web:, file:) that should not be
    stored as an internal link.
    """
    if raw.lower().startswith(('web:', 'file:')):
        return None
    m = _TYPED_PREFIX_RE.match(raw)
    return m.group(2) if m else raw


# ── public API ────────────────────────────────────────────────────────────────

async def sync_links(source_id: str, content: str, db: aiosqlite.Connection) -> None:
    """
    Rebuild internal links originating from source_id.

    Strategy: delete all existing internal links from this source,
    then re-insert resolved ones.  This keeps the table accurate
    without needing a UNIQUE constraint on (source_id, target_id).

    Typed links ([[task:X]], [[note:X]] …) have their prefix stripped before
    the title lookup so they resolve to the correct object.
    """
    titles = set(_extract_links(content))   # deduplicated

    await db.execute(
        "DELETE FROM links WHERE source_id = ? AND link_type = 'internal'",
        (source_id,)
    )

    for raw_title in titles:
        lookup_title = _resolve_link_title(raw_title)
        if lookup_title is None:
            continue  # web: / file: — handled as external below
        cur = await db.execute("SELECT id FROM objects WHERE title = ?", (lookup_title,))
        row = await cur.fetchone()
        if row:
            await db.execute(
                "INSERT INTO links (id, source_id, target_id, link_type) "
                "VALUES (?, ?, ?, 'internal')",
                (str(uuid.uuid4()), source_id, row["id"])
            )
        # Unresolvable titles (dangling) are intentionally not stored;
        # they are computed on-demand by the panel endpoint.

    # Also capture plain-URL external links
    await db.execute(
        "DELETE FROM links WHERE source_id = ? AND link_type = 'external'",
        (source_id,)
    )
    for url in set(_URL_RE.findall(content)):
        await db.execute(
            "INSERT INTO links (id, source_id, target_url, link_type) "
            "VALUES (?, ?, ?, 'external')",
            (str(uuid.uuid4()), source_id, url)
        )


async def propagate_rename(
    object_id: str,
    old_title: str,
    new_title: str,
    db: aiosqlite.Connection,
) -> int:
    """
    Replace [[old_title]] with [[new_title]] in every object whose content
    links to object_id.  Uses the links table (UUID-keyed) to locate sources.

    Returns the number of source objects updated.
    """
    old_ref = f"[[{old_title}]]"
    new_ref = f"[[{new_title}]]"

    if old_ref == new_ref:
        return 0

    # Find all objects that currently link to this one
    cur = await db.execute(
        "SELECT DISTINCT source_id FROM links "
        "WHERE target_id = ? AND link_type = 'internal'",
        (object_id,)
    )
    source_ids = [r["source_id"] for r in await cur.fetchall()]

    updated = 0
    for sid in source_ids:
        cur = await db.execute("SELECT type FROM objects WHERE id = ?", (sid,))
        obj = await cur.fetchone()
        if not obj:
            continue

        if obj["type"] in ("note", "journal"):
            updated += await _rename_in_file(sid, obj["type"], old_ref, new_ref, db)
        elif obj["type"] == "task":
            updated += await _rename_in_db_field(sid, "tasks", "description",
                                                  old_ref, new_ref, db)
        elif obj["type"] == "event":
            updated += await _rename_in_db_field(sid, "events", "description",
                                                  old_ref, new_ref, db)

    return updated


async def title_completions(
    partial: str,
    db: aiosqlite.Connection,
    limit: int = 20,
) -> List[dict]:
    """
    Return objects whose title contains `partial` (case-insensitive).
    Sorted: exact prefix matches first, then substring matches.
    """
    like = f"%{partial}%"
    cur = await db.execute(
        "SELECT id, title, type FROM objects "
        "WHERE title LIKE ? COLLATE NOCASE "
        "ORDER BY "
        "  CASE WHEN title LIKE ? COLLATE NOCASE THEN 0 ELSE 1 END, "
        "  title COLLATE NOCASE "
        "LIMIT ?",
        (like, f"{partial}%", limit)
    )
    return [{"id": r["id"], "title": r["title"], "type": r["type"]}
            for r in await cur.fetchall()]


async def get_dangling(source_id: str, content: str, db: aiosqlite.Connection) -> List[str]:
    """
    Return [[titles]] that appear in content but don't resolve to any object.
    Used by the panel endpoint.  Typed prefixes (task:, event:, …) are stripped
    before the lookup, matching the same logic as sync_links.
    """
    dangling = []
    for raw_title in set(_extract_links(content)):
        lookup_title = _resolve_link_title(raw_title)
        if lookup_title is None:
            continue  # external reference, skip
        cur = await db.execute("SELECT id FROM objects WHERE title = ?", (lookup_title,))
        if not await cur.fetchone():
            dangling.append(raw_title)
    return sorted(dangling)


# ── private helpers ───────────────────────────────────────────────────────────

async def _rename_in_file(
    source_id: str,
    obj_type: str,
    old_ref: str,
    new_ref: str,
    db: aiosqlite.Connection,
) -> int:
    table = "notes" if obj_type == "note" else "journal_entries"
    cur = await db.execute(f"SELECT filepath FROM {table} WHERE id = ?", (source_id,))
    row = await cur.fetchone()
    if not row:
        return 0

    path = Path(row["filepath"])
    if not path.exists():
        return 0

    text = path.read_text(encoding="utf-8")
    if old_ref not in text:
        return 0

    from service_watcher import ignore
    ignore(path)
    path.write_text(text.replace(old_ref, new_ref), encoding="utf-8")
    return 1


async def _rename_in_db_field(
    source_id: str,
    table: str,
    column: str,
    old_ref: str,
    new_ref: str,
    db: aiosqlite.Connection,
) -> int:
    cur = await db.execute(
        f"SELECT {column} FROM {table} WHERE id = ?", (source_id,)
    )
    row = await cur.fetchone()
    if not row or not row[column] or old_ref not in row[column]:
        return 0

    await db.execute(
        f"UPDATE {table} SET {column} = ? WHERE id = ?",
        (row[column].replace(old_ref, new_ref), source_id)
    )
    return 1
