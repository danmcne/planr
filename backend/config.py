"""
All filesystem paths live here. Override any of them via environment variables
so no path is ever hardcoded in application logic.

Defaults:
  PLANR_DATA_DIR      ~/.local/share/planr/   SQLite database (XDG-standard)
  PLANR_CONTENT_DIR   ~/planr/                notes and journal (phase 3)
"""

import os
from pathlib import Path


def _p(env: str, default: Path) -> Path:
    raw = os.environ.get(env, "")
    return Path(raw).expanduser().resolve() if raw else default


DATA_DIR    = _p("PLANR_DATA_DIR",    Path.home() / ".local" / "share" / "planr")
CONTENT_DIR = _p("PLANR_CONTENT_DIR", Path.home() / "planr")

DB_PATH     = DATA_DIR    / "app.db"
NOTES_DIR   = CONTENT_DIR / "notes"
JOURNAL_DIR = CONTENT_DIR / "journal"
