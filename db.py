"""
db.py — SQLite database setup for planr
"""
import sqlite3
import os
from pathlib import Path
from contextlib import contextmanager

DB_PATH = os.environ.get("PLANR_DB", str(Path.home() / ".planr" / "planr.db"))

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

@contextmanager
def db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

SCHEMA = """
CREATE TABLE IF NOT EXISTS contexts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    parent_id  INTEGER REFERENCES contexts(id) ON DELETE SET NULL,
    full_path  TEXT UNIQUE NOT NULL,
    color      TEXT NOT NULL DEFAULT '#6B7280',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tasks (
    uuid          TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    context_id    INTEGER REFERENCES contexts(id) ON DELETE SET NULL,
    status        TEXT NOT NULL DEFAULT 'inbox',
    importance    TEXT NOT NULL DEFAULT 'normal',
    effort        TEXT NOT NULL DEFAULT 'medium',
    user_urgency  REAL NOT NULL DEFAULT 0,
    due_at        TEXT,
    scheduled_at  TEXT,
    recurrence    TEXT NOT NULL DEFAULT '',
    recurrence_type TEXT NOT NULL DEFAULT 'fixed',
    parent_uuid   TEXT REFERENCES tasks(uuid) ON DELETE SET NULL,
    root_uuid     TEXT,
    location      TEXT NOT NULL DEFAULT '',
    priority_score REAL NOT NULL DEFAULT 0,
    deferred_until TEXT,
    defer_count   INTEGER NOT NULL DEFAULT 0,
    last_active_at TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    modified_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS events (
    uuid        TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    context_id  INTEGER REFERENCES contexts(id) ON DELETE SET NULL,
    start_at    TEXT,
    end_at      TEXT,
    all_day     INTEGER NOT NULL DEFAULT 0,
    recurrence  TEXT NOT NULL DEFAULT '',
    parent_uuid TEXT REFERENCES events(uuid) ON DELETE SET NULL,
    root_uuid   TEXT,
    location    TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    modified_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS notes (
    uuid         TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    content      TEXT NOT NULL DEFAULT '',
    context_id   INTEGER REFERENCES contexts(id) ON DELETE SET NULL,
    file_path    TEXT,
    content_hash TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    modified_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS journal_entries (
    uuid         TEXT PRIMARY KEY,
    title        TEXT NOT NULL DEFAULT '',
    content      TEXT NOT NULL DEFAULT '',
    context_id   INTEGER REFERENCES contexts(id) ON DELETE SET NULL,
    entry_date   TEXT NOT NULL,
    file_path    TEXT,
    content_hash TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    modified_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tags (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT UNIQUE NOT NULL,
    usage_count  INTEGER NOT NULL DEFAULT 0,
    last_used_at TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS object_tags (
    object_uuid TEXT NOT NULL,
    tag_id      INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    object_type TEXT NOT NULL,
    PRIMARY KEY (object_uuid, tag_id)
);

CREATE TABLE IF NOT EXISTS links (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source_uuid  TEXT NOT NULL,
    source_type  TEXT NOT NULL,
    target_uuid  TEXT,
    target_type  TEXT NOT NULL DEFAULT 'internal',
    target_ref   TEXT,
    link_type    TEXT NOT NULL DEFAULT 'related_to',
    display_text TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS saved_searches (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    query_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
    uuid UNINDEXED,
    type,
    title,
    content,
    tokenize='porter unicode61'
);

CREATE INDEX IF NOT EXISTS idx_tasks_status    ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_context   ON tasks(context_id);
CREATE INDEX IF NOT EXISTS idx_tasks_due       ON tasks(due_at);
CREATE INDEX IF NOT EXISTS idx_tasks_priority  ON tasks(priority_score DESC);
CREATE INDEX IF NOT EXISTS idx_events_start    ON events(start_at);
CREATE INDEX IF NOT EXISTS idx_journal_date    ON journal_entries(entry_date);
CREATE INDEX IF NOT EXISTS idx_links_source    ON links(source_uuid);
CREATE INDEX IF NOT EXISTS idx_links_target    ON links(target_uuid);
"""

DEFAULT_CONTEXTS = [
    (1, 'Inbox',         None, 'inbox',         '#6B7280'),
    (2, 'Personal',      None, 'personal',      '#10B981'),
    (3, 'Work',          None, 'work',           '#3B82F6'),
    (4, 'Uncategorized', None, 'uncategorized', '#8B5CF6'),
]

def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.executescript(SCHEMA)
        # Migration: add sort_order if this is an existing DB
        cols = {r[1] for r in conn.execute("PRAGMA table_info(contexts)").fetchall()}
        if "sort_order" not in cols:
            conn.execute("ALTER TABLE contexts ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
        if conn.execute("SELECT COUNT(*) FROM contexts").fetchone()[0] == 0:
            for cid, name, parent, path, color in DEFAULT_CONTEXTS:
                conn.execute(
                    "INSERT OR IGNORE INTO contexts (id, name, parent_id, full_path, color, sort_order) VALUES (?,?,?,?,?,?)",
                    (cid, name, parent, path, color, cid - 1)
                )
