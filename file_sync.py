"""
file_sync.py — Notes and journal file sync for planr.

The DB is the source of truth.  Files are durable, human-readable exports.
Every note / journal entry is written as a Markdown file with a YAML front-
matter block containing the UUID so files can always be reconciled with DB.
"""
import hashlib
import os
import re
from pathlib import Path
from typing import Optional, Tuple

NOTES_DIR   = Path(os.environ.get("PLANR_NOTES_DIR",   str(Path.home() / ".planr" / "notes")))
JOURNAL_DIR = Path(os.environ.get("PLANR_JOURNAL_DIR", str(Path.home() / ".planr" / "journal")))


# ── helpers ──────────────────────────────────────────────────────────────────

def short_uuid(uuid: str) -> str:
    return uuid[:8]


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:32]


def _safe_slug(s: str) -> str:
    return re.sub(r"[^\w\s-]", "", s).strip().replace(" ", "-")[:60]


def _frontmatter(uuid: str, title: str, obj_type: str, created_at: str) -> str:
    return f"---\nuuid: {uuid}\ntitle: {title}\ntype: {obj_type}\ncreated: {created_at}\n---\n\n"


def strip_frontmatter(raw: str) -> Tuple[dict, str]:
    if not raw.startswith("---\n"):
        return {}, raw
    end = raw.find("\n---\n", 4)
    if end == -1:
        return {}, raw
    meta: dict = {}
    for line in raw[4:end].splitlines():
        if ": " in line:
            k, v = line.split(": ", 1)
            meta[k.strip()] = v.strip()
    return meta, raw[end + 5:]


# ── write / rename ────────────────────────────────────────────────────────────

def write_note(uuid: str, title: str, content: str, created_at: str) -> Tuple[str, str]:
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    filename  = f"{_safe_slug(title)}-{created_at[:10]}-{short_uuid(uuid)}.md"
    file_path = NOTES_DIR / filename
    file_path.write_text(_frontmatter(uuid, title, "note", created_at) + content, encoding="utf-8")
    return str(file_path), content_hash(content)


def write_journal(uuid: str, title: str, content: str,
                  entry_date: str, created_at: str) -> Tuple[str, str]:
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    slug      = f"-{_safe_slug(title)}" if title else ""
    filename  = f"{entry_date}{slug}-{short_uuid(uuid)}.md"
    file_path = JOURNAL_DIR / filename
    file_path.write_text(
        _frontmatter(uuid, title or entry_date, "journal", created_at) + content,
        encoding="utf-8",
    )
    return str(file_path), content_hash(content)


def rename_note_file(old_path: str, uuid: str, new_title: str, created_at: str) -> str:
    """Rename a note file when its title changes; returns new path."""
    old = Path(old_path)
    if not old.exists():
        # Just generate the new path; write_note will create it
        _, body = strip_frontmatter("")
        new_path, _ = write_note(uuid, new_title, body, created_at)
        return new_path

    _, body = strip_frontmatter(old.read_text(encoding="utf-8"))
    new_path_str, _ = write_note(uuid, new_title, body, created_at)
    new_path = Path(new_path_str)
    if old.resolve() != new_path.resolve():
        old.unlink(missing_ok=True)
    return new_path_str


# ── scan ─────────────────────────────────────────────────────────────────────

def scan_notes() -> list:
    if not NOTES_DIR.exists():
        return []
    results = []
    for fp in NOTES_DIR.glob("*.md"):
        try:
            raw = fp.read_text(encoding="utf-8")
            meta, body = strip_frontmatter(raw)
            results.append({
                "file_path":    str(fp),
                "uuid":         meta.get("uuid"),
                "title":        meta.get("title", fp.stem),
                "content":      body,
                "content_hash": content_hash(body),
            })
        except Exception:
            pass
    return results


def scan_journal() -> list:
    if not JOURNAL_DIR.exists():
        return []
    results = []
    for fp in JOURNAL_DIR.glob("*.md"):
        try:
            raw = fp.read_text(encoding="utf-8")
            meta, body = strip_frontmatter(raw)
            m = re.match(r"^(\d{4}-\d{2}-\d{2})", fp.name)
            results.append({
                "file_path":    str(fp),
                "uuid":         meta.get("uuid"),
                "title":        meta.get("title", ""),
                "entry_date":   m.group(1) if m else "",
                "content":      body,
                "content_hash": content_hash(body),
            })
        except Exception:
            pass
    return results
