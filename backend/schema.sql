-- Phase 1 schema — SQLite
-- Covers: tasks, contexts, tags, links, priority profiles
-- Events, notes, and journal tables are added in later phases.
--
-- Design: class-table inheritance
--   Every entity (task / event / note / journal) owns a row in `objects`.
--   Type-specific tables (tasks, …) share the same primary key via FK.
--   This makes [[Title]] → UUID resolution a single-table lookup.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ─── Base: unified object identity ───────────────────────────────────────────

CREATE TABLE IF NOT EXISTS objects (
    id         TEXT PRIMARY KEY,          -- UUID stored as text
    title      TEXT NOT NULL UNIQUE,      -- globally unique; used for [[Title]] links
    type       TEXT NOT NULL CHECK(type IN ('task', 'event', 'note', 'journal')),
    date       TEXT,                      -- YYYY-MM-DD; meaning varies by type
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Keep updated_at current on every write
CREATE TRIGGER IF NOT EXISTS trg_objects_updated_at
    AFTER UPDATE ON objects FOR EACH ROW
BEGIN
    UPDATE objects SET updated_at = datetime('now') WHERE id = NEW.id;
END;

-- ─── Tasks ───────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS tasks (
    id                TEXT PRIMARY KEY REFERENCES objects(id) ON DELETE CASCADE,
    description       TEXT,
    status            TEXT NOT NULL DEFAULT 'inbox'
                          CHECK(status IN ('inbox', 'active', 'done', 'deferred', 'someday')),
    importance        TEXT NOT NULL DEFAULT 'normal'
                          CHECK(importance IN ('low', 'normal', 'high', 'critical')),
    time_estimate_min INTEGER,             -- planned effort in minutes
    due_date          TEXT,               -- YYYY-MM-DD
    -- JSON: {"type": "fixed"|"cyclic", "interval": N, "unit": "day"|"week"|"month"}
    recurrence_rule   TEXT,
    -- ISO datetime of last completion — anchor for cyclic recurrence scheduling
    recurrence_anchor TEXT,
    -- Non-null → this is a subtask; depth capped at 2–3 levels in the app layer
    parent_task_id    TEXT REFERENCES tasks(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_status     ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_due_date   ON tasks(due_date);
CREATE INDEX IF NOT EXISTS idx_tasks_parent     ON tasks(parent_task_id);

-- ─── Contexts ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS contexts (
    id        TEXT PRIMARY KEY,
    name      TEXT NOT NULL UNIQUE,
    -- Non-null → subcontext, e.g. Work.Project
    parent_id TEXT REFERENCES contexts(id) ON DELETE SET NULL,
    color     TEXT NOT NULL DEFAULT '#888888',
    -- is_system = 1: shown in UI but cannot be deleted
    is_system INTEGER NOT NULL DEFAULT 0
);

-- Seed default contexts (Someday is a task STATUS, not a context)
INSERT OR IGNORE INTO contexts (id, name, is_system, color) VALUES
    ('ctx-inbox',         'Inbox',         1, 'slate'),
    ('ctx-personal',      'Personal',      0, 'violet'),
    ('ctx-work',          'Work',          0, 'blue'),
    ('ctx-uncategorized', 'Uncategorized', 0, 'teal');

-- Migrate any existing rows to have correct colours (idempotent)
UPDATE contexts SET color='slate'  WHERE id='ctx-inbox';
UPDATE contexts SET color='violet' WHERE id='ctx-personal';
UPDATE contexts SET color='blue'   WHERE id='ctx-work';
UPDATE contexts SET color='teal'   WHERE id='ctx-uncategorized';

-- Remove Someday context if it exists (Someday = task status, not a context)
DELETE FROM contexts WHERE id='ctx-someday';

-- ─── Object ↔ Context (many-to-many) ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS object_contexts (
    object_id  TEXT NOT NULL REFERENCES objects(id)  ON DELETE CASCADE,
    context_id TEXT NOT NULL REFERENCES contexts(id) ON DELETE CASCADE,
    PRIMARY KEY (object_id, context_id)
);

CREATE INDEX IF NOT EXISTS idx_obj_ctx_context ON object_contexts(context_id);

-- ─── Tags ────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS tags (
    id   TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

-- ─── Object ↔ Tag (many-to-many) ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS object_tags (
    object_id TEXT NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
    tag_id    TEXT NOT NULL REFERENCES tags(id)    ON DELETE CASCADE,
    PRIMARY KEY (object_id, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_obj_tag_tag ON object_tags(tag_id);

-- ─── Links ───────────────────────────────────────────────────────────────────
-- Internal: source_id → target_id (both objects), target_url IS NULL
-- External: source_id → URL,       target_id IS NULL
--
-- ON DELETE SET NULL for target_id: if the target object is deleted,
-- the link row survives as a dangling reference so the UI can show warnings.

CREATE TABLE IF NOT EXISTS links (
    id         TEXT PRIMARY KEY,
    source_id  TEXT NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
    target_id  TEXT          REFERENCES objects(id) ON DELETE SET NULL,
    target_url TEXT,
    link_type  TEXT NOT NULL CHECK(link_type IN ('internal', 'external')),
    CHECK (
        (link_type = 'internal' AND target_id  IS NOT NULL AND target_url IS NULL) OR
        (link_type = 'external' AND target_url IS NOT NULL AND target_id  IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_links_source ON links(source_id);
CREATE INDEX IF NOT EXISTS idx_links_target ON links(target_id);

-- ─── Priority profiles ───────────────────────────────────────────────────────
-- Weights are stored here as data; the app computes scores at query time.
-- Scores are NEVER persisted — always recomputed from the active profile.

CREATE TABLE IF NOT EXISTS priority_profiles (
    id                TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    urgency_weight    REAL NOT NULL DEFAULT 0.40 CHECK(urgency_weight    BETWEEN 0 AND 1),
    importance_weight REAL NOT NULL DEFAULT 0.40 CHECK(importance_weight BETWEEN 0 AND 1),
    effort_weight     REAL NOT NULL DEFAULT 0.15 CHECK(effort_weight     BETWEEN 0 AND 1),
    staleness_weight  REAL NOT NULL DEFAULT 0.05 CHECK(staleness_weight  BETWEEN 0 AND 1),
    is_active         INTEGER NOT NULL DEFAULT 0
);

INSERT OR IGNORE INTO priority_profiles
    (id, name, urgency_weight, importance_weight, effort_weight, staleness_weight, is_active)
VALUES
    ('prof-default', 'Default', 0.40, 0.40, 0.15, 0.05, 1);

-- ─── Events ──────────────────────────────────────────────────────────────────
-- Extends objects via shared primary key (same pattern as tasks).
--
-- Recurrence model: master event + stored overrides.
--   Masters  → rrule IS NOT NULL (or NULL for one-off), parent_event_id IS NULL
--   Overrides→ parent_event_id IS NOT NULL, original_date = slot being replaced
--   Virtual occurrences are expanded at query time and never stored unless edited.
--
-- rrule_until: effective end of the series (ISO date, inclusive).
-- original_date: the YYYY-MM-DD slot in the master's series this child replaces.

CREATE TABLE IF NOT EXISTS events (
    id               TEXT PRIMARY KEY REFERENCES objects(id) ON DELETE CASCADE,
    start_datetime   TEXT NOT NULL,   -- ISO 8601 with TZ, e.g. 2026-06-01T09:00:00+00:00
    end_datetime     TEXT NOT NULL,
    all_day          INTEGER NOT NULL DEFAULT 0,
    location         TEXT,
    description      TEXT,
    status           TEXT NOT NULL DEFAULT 'confirmed'
                         CHECK(status IN ('confirmed', 'tentative', 'cancelled')),
    -- Recurrence (masters only)
    rrule            TEXT,            -- iCal RRULE e.g. "FREQ=WEEKLY;BYDAY=MO,WE"
    rrule_until      TEXT,            -- ISO date: series stops on or before this
    -- Override fields (children only)
    parent_event_id  TEXT REFERENCES events(id) ON DELETE CASCADE,
    root_event_id    TEXT REFERENCES events(id) ON DELETE CASCADE,
    original_date    TEXT,            -- YYYY-MM-DD slot this child replaces
    -- JSON array of YYYY-MM-DD dates excluded from recurring series
    exceptions       TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_events_start     ON events(start_datetime);
CREATE INDEX IF NOT EXISTS idx_events_parent    ON events(parent_event_id);
CREATE INDEX IF NOT EXISTS idx_events_root      ON events(root_event_id);
CREATE INDEX IF NOT EXISTS idx_events_orig_date ON events(original_date);

-- ─── Notes ───────────────────────────────────────────────────────────────────
-- Extends objects. Filesystem is canonical for content; DB for metadata + search.
-- Import rule: any .md dropped into NOTES_DIR is auto-assigned a UUID by the watcher.

CREATE TABLE IF NOT EXISTS notes (
    id       TEXT PRIMARY KEY REFERENCES objects(id) ON DELETE CASCADE,
    filepath TEXT NOT NULL UNIQUE   -- absolute path to the .md file
);

-- ─── Journal entries ──────────────────────────────────────────────────────────
-- One entry per day (UNIQUE on entry_date).

CREATE TABLE IF NOT EXISTS journal_entries (
    id         TEXT PRIMARY KEY REFERENCES objects(id) ON DELETE CASCADE,
    entry_date TEXT NOT NULL UNIQUE,   -- YYYY-MM-DD
    filepath   TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_journal_date ON journal_entries(entry_date);

-- ─── Phase 4: link index optimisation ────────────────────────────────────────
-- Partial index makes backlink queries (target_id WHERE internal) fast.

CREATE INDEX IF NOT EXISTS idx_links_internal_target
    ON links(target_id) WHERE link_type = 'internal';

CREATE INDEX IF NOT EXISTS idx_links_internal_source
    ON links(source_id) WHERE link_type = 'internal';
