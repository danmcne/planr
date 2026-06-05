# backend/watcher.py
"""
Filesystem watcher: keeps the DB in sync when the user edits notes or journal
entries directly (outside the app).

Watches NOTES_DIR and JOURNAL_DIR for:
  added    → parse frontmatter; assign UUID if missing; write it back; upsert DB
  modified → re-parse; update title + filepath in DB
  deleted  → remove from DB (cascades via FK)

Run as an asyncio background task started in main.py's lifespan.

To avoid processing events caused by the API's own writes, call
ignore() before every file operation the API performs.
"""

import asyncio
import logging
from pathlib import Path
from typing import Set

from watchfiles import awatch, Change

from config import JOURNAL_DIR, NOTES_DIR

log = logging.getLogger("planr.watcher")

# Paths to skip on the next watcher event (populated by the API layer).
# Each path is discarded after one skip to prevent stale ignores.
_ignored: Set[str] = set()


def ignore(*paths) -> None:
    """Tell the watcher to skip the next change event for each path."""
    for p in paths:
        _ignored.add(str(p))


async def watch_directories() -> None:
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    log.info(f"Watching {NOTES_DIR} and {JOURNAL_DIR}")

    async for changes in awatch(str(NOTES_DIR), str(JOURNAL_DIR)):
        for change_type, path_str in changes:
            path = Path(path_str)
            if path.suffix.lower() != ".md":
                continue
            if str(path) in _ignored:
                _ignored.discard(str(path))
                continue
            try:
                await _handle(change_type, path)
            except Exception as exc:
                log.error(f"Watcher error [{path.name}]: {exc}")


async def _handle(change_type: Change, path: Path) -> None:
    import uuid
    import aiosqlite
    from datetime import datetime, timezone

    from config import DB_PATH
    from service_markdown import read, write

    is_journal = path.parent.resolve() == JOURNAL_DIR.resolve()
    obj_type   = "journal" if is_journal else "note"
    now        = datetime.now(timezone.utc).isoformat()

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")

        # ── deleted ──────────────────────────────────────────────────────────
        if change_type == Change.deleted:
            table = "journal_entries" if is_journal else "notes"
            cur = await db.execute(
                f"SELECT id FROM {table} WHERE filepath = ?", (str(path),)
            )
            row = await cur.fetchone()
            if row:
                await db.execute("DELETE FROM objects WHERE id = ?", (row["id"],))
                await db.commit()
                log.info(f"Removed: {path.name}")
            return

        # ── added / modified ─────────────────────────────────────────────────
        meta, content = read(path)
        existing_id   = meta.get("uuid")

        if existing_id:
            cur = await db.execute("SELECT id FROM objects WHERE id = ?", (existing_id,))
            if await cur.fetchone():
                title = str(meta.get("title", path.stem))
                await db.execute(
                    "UPDATE objects SET title=?, updated_at=? WHERE id=?",
                    (title, now, existing_id)
                )
                table = "journal_entries" if is_journal else "notes"
                await db.execute(
                    f"UPDATE {table} SET filepath=? WHERE id=?",
                    (str(path), existing_id)
                )
                await db.commit()
                log.info(f"Updated: {path.name}")
                return

        # New file dropped by the user — assign UUID and write it back
        new_id     = str(uuid.uuid4())
        title      = str(meta.get("title", path.stem))
        entry_date = str(meta.get("date", path.stem[:10] if is_journal else now[:10]))[:10]

        meta["uuid"] = new_id
        if "title" not in meta:
            meta["title"] = title

        ignore(path)   # suppress the write event we're about to cause
        write(path, meta, content)

        await db.execute(
            "INSERT OR IGNORE INTO objects (id,title,type,date,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (new_id, title, obj_type, entry_date, now, now)
        )
        if is_journal:
            await db.execute(
                "INSERT OR IGNORE INTO journal_entries (id,entry_date,filepath) VALUES (?,?,?)",
                (new_id, entry_date, str(path))
            )
        else:
            await db.execute(
                "INSERT OR IGNORE INTO notes (id,filepath) VALUES (?,?)",
                (new_id, str(path))
            )
        await db.execute(
            "INSERT OR IGNORE INTO object_contexts (object_id,context_id) VALUES (?,?)",
            (new_id, "ctx-uncategorized")
        )
        await db.commit()
        log.info(f"Imported: {path.name} → {new_id[:8]}")
