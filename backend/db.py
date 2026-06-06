from pathlib import Path
import aiosqlite
from config import DATA_DIR, DB_PATH

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


async def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    schema = SCHEMA_PATH.read_text()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("PRAGMA journal_mode = WAL")
        await db.executescript(schema)

    # ── Idempotent migrations for databases created before these columns existed ──
    async with aiosqlite.connect(DB_PATH) as db:
        for stmt in [
            "ALTER TABLE events   ADD COLUMN exceptions TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE contexts ADD COLUMN color TEXT NOT NULL DEFAULT 'slate'",
            # default_for: NULL | 'tasks' | 'notes'  (one context can serve as default per type)
            "ALTER TABLE contexts ADD COLUMN default_for TEXT DEFAULT NULL",
        ]:
            try:
                await db.execute(stmt)
            except Exception:
                pass  # column already exists — safe to ignore
        # Ensure correct colours on seeded contexts
        for ctx_id, colour in [
            ("ctx-inbox",         "slate"),
            ("ctx-personal",      "violet"),
            ("ctx-work",          "blue"),
            ("ctx-uncategorized", "teal"),
        ]:
            await db.execute(
                "UPDATE contexts SET color=? WHERE id=? AND (color IS NULL OR color='#888888')",
                (colour, ctx_id),
            )
        # Seed default_for on first run (idempotent — only sets if not already set)
        await db.execute(
            "UPDATE contexts SET default_for='tasks' WHERE id='ctx-inbox' AND default_for IS NULL"
        )
        await db.execute(
            "UPDATE contexts SET default_for='notes' WHERE id='ctx-uncategorized' AND default_for IS NULL"
        )
        # Someday is a task status, not a context — remove if present
        await db.execute("DELETE FROM contexts WHERE id='ctx-someday'")
        await db.commit()


async def get_db():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")
        yield db
