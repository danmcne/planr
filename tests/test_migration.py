"""Migration test: a 1.4.0-era database (no recur_exceptions/recurrence_id
columns) must be upgraded in place by init_db, with existing recurring
events intact.

    .venv/bin/python tests/test_migration.py
"""
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
tmp = tempfile.mkdtemp(prefix="planr-mig-")
dbfile = f"{tmp}/old.db"

# Build a minimal 1.4.0-shaped events table with a legacy recurring event.
conn = sqlite3.connect(dbfile)
conn.execute("""CREATE TABLE events (
    uuid TEXT PRIMARY KEY, title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    context_id INTEGER, start_at TEXT, end_at TEXT,
    all_day INTEGER NOT NULL DEFAULT 0,
    recurrence TEXT NOT NULL DEFAULT '',
    parent_uuid TEXT, root_uuid TEXT,
    location TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    modified_at TEXT NOT NULL DEFAULT (datetime('now')))""")
conn.execute("""INSERT INTO events (uuid,title,start_at,end_at,recurrence,root_uuid)
                VALUES ('u1','Old weekly','2026-07-07T15:00:00',
                        '2026-07-07T16:00:00','week:1','u1')""")
conn.commit()
conn.close()

# Run init_db in a subprocess so PLANR_DB is read at import time.
code = """
import sys; sys.path.insert(0, r'%s')
from db import init_db
init_db()
""" % ROOT
env = dict(os.environ, PLANR_DB=dbfile,
           PLANR_NOTES_DIR=f"{tmp}/n", PLANR_JOURNAL_DIR=f"{tmp}/j")
r = subprocess.run([sys.executable, "-c", code], env=env,
                   capture_output=True, text=True)
assert r.returncode == 0, f"init_db failed:\n{r.stderr}"

conn = sqlite3.connect(dbfile)
conn.row_factory = sqlite3.Row
cols = {row[1] for row in conn.execute("PRAGMA table_info(events)")}
assert "recur_exceptions" in cols, "recur_exceptions column missing"
print("  ok  recur_exceptions column added")
assert "recurrence_id" in cols, "recurrence_id column missing"
print("  ok  recurrence_id column added")
row = dict(conn.execute("SELECT * FROM events WHERE uuid='u1'").fetchone())
assert row["recurrence"] == "week:1" and row["recur_exceptions"] == ""
print("  ok  existing event untouched, defaults applied")

# The migrated row must expand.
sys.path.insert(0, str(ROOT))
from datetime import date
from recurrence import expand
occ = expand(row, date(2026, 7, 1), date(2026, 7, 31))
assert len(occ) == 4, f"expected 4 occurrences, got {len(occ)}"
print("  ok  legacy recurring event expands after migration")

conn.close()
print("\nAll 4 migration tests passed.")
