"""
db_utils.py — shared helpers used by all routers
"""
import re
import sqlite3


def sync_tags(conn: sqlite3.Connection, object_uuid: str, object_type: str, text: str):
    """Extract #tags from text and synchronise the tags + object_tags tables."""
    found = set(re.findall(r'#(\w+)', text))
    conn.execute("DELETE FROM object_tags WHERE object_uuid = ?", (object_uuid,))
    for name in found:
        conn.execute(
            """INSERT INTO tags (name, usage_count, last_used_at)
               VALUES (?, 1, datetime('now'))
               ON CONFLICT(name) DO UPDATE SET
                   usage_count  = usage_count + 1,
                   last_used_at = datetime('now')""",
            (name,),
        )
        tag_id = conn.execute(
            "SELECT id FROM tags WHERE name = ?", (name,)
        ).fetchone()["id"]
        conn.execute(
            "INSERT OR IGNORE INTO object_tags (object_uuid, tag_id, object_type) VALUES (?,?,?)",
            (object_uuid, tag_id, object_type),
        )


def sync_fts(conn: sqlite3.Connection, uuid: str, obj_type: str, title: str, content: str):
    """Keep the FTS5 search_index in sync with an object."""
    conn.execute("DELETE FROM search_index WHERE uuid = ?", (uuid,))
    conn.execute(
        "INSERT INTO search_index(uuid, type, title, content) VALUES (?,?,?,?)",
        (uuid, obj_type, title, content),
    )
