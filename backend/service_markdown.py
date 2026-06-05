# backend/markdown.py
"""
Markdown frontmatter helpers.

Handles:
  - Parsing / writing YAML frontmatter (--- delimiters)
  - [[Title]] link extraction
  - Filename generation for notes and journal entries
"""

import re
import uuid as _uuid
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

_FM_RE   = re.compile(r'^---\n(.*?)\n---\n?', re.DOTALL)
_LINK_RE = re.compile(r'\[\[(.+?)\]\]')


# ── frontmatter ───────────────────────────────────────────────────────────────

def parse(text: str) -> Tuple[Dict[str, Any], str]:
    """Return (meta_dict, body). meta_dict is {} if no frontmatter present."""
    m = _FM_RE.match(text)
    if m:
        meta = yaml.safe_load(m.group(1)) or {}
        return meta, text[m.end():]
    return {}, text


def dumps(meta: Dict[str, Any], content: str) -> str:
    fm = yaml.dump(meta, default_flow_style=False, allow_unicode=True, sort_keys=True)
    return f"---\n{fm}---\n{content}"


def read(filepath: Path) -> Tuple[Dict[str, Any], str]:
    return parse(filepath.read_text(encoding="utf-8"))


def write(filepath: Path, meta: Dict[str, Any], content: str) -> None:
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(dumps(meta, content), encoding="utf-8")


# ── link extraction ───────────────────────────────────────────────────────────

def extract_links(content: str) -> List[str]:
    """Return titles referenced via [[Title]] in content."""
    return _LINK_RE.findall(content)


# ── filename generation ───────────────────────────────────────────────────────

def _slug(text: str, maxlen: int = 60) -> str:
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')[:maxlen]


def note_filename(title: str, created: date, short_id: str) -> str:
    """<slug>-<YYYY-MM-DD>-<short-uuid>.md"""
    return f"{_slug(title)}-{created.isoformat()}-{short_id}.md"


def journal_filename(entry_date: date, title: Optional[str] = None) -> str:
    """YYYY-MM-DD[-<slug>].md"""
    if title:
        return f"{entry_date.isoformat()}-{_slug(title)}.md"
    return f"{entry_date.isoformat()}.md"


def short_id() -> str:
    return str(_uuid.uuid4())[:8]
