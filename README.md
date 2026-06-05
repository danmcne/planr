# planr

A personal organiser — local-first, self-hosted, no accounts, no cloud.

Tasks, events, notes, and a journal all live in one place and can link to each other with `[[wiki-style links]]`. The backend is a small FastAPI process serving a single HTML file; there is no build step and no JavaScript framework.

---

## What it does

| View | Purpose |
|------|---------|
| **Today** | Time-blocked schedule on the left; prioritised tasks and today's journal on the right |
| **Week** | Seven-day grid showing events hour by hour |
| **Month** | Calendar overview — click any day to jump to the week view for that day |
| **Tasks** | Full task list with status / sort filters; inline mark-done and delete |
| **Notes** | Searchable wiki-style notes stored as Markdown files; split edit/preview panel |
| **Journal** | One entry per day, stored as Markdown files; auto-saves as you type |

The **context bar** below the capture bar narrows every view — tasks, events, notes, journal — to a single context (e.g. Work, Personal) or shows everything at once.

Note: dates use YYYY-MM-DD format globally.

---

## Quick-capture bar

The bar at the top of every view creates tasks instantly. Press **Enter** or click **+ Add**.

| Input | Result |
|-------|--------|
| `Buy oat milk` | Task in Inbox |
| `Call dentist @personal` | Task assigned to Personal context |
| `Review PR @work.projectalpha` | Task in Work › ProjectAlpha subcontext |

---

## Key concepts

### Contexts (GTD-inspired categories)

Every object belongs to at least one context. Defaults: **Inbox**, **Personal**, **Work**, **Uncategorised**. Contexts can be added, renamed, or deleted via the API; the frontend shows them as coloured pills.

Subcontexts use dot notation: `Work.ProjectAlpha`. Type `@Work.ProjectAlpha` in the capture bar to assign on the fly.

When a context is deleted, objects that would be left with no context are automatically re-homed — tasks/events to **Inbox**, notes/journal to **Uncategorised**.

Context colors can be a 6-digit hex value (`#4a90d9`) or any Tailwind CSS color name (`slate`, `violet`, `blue`, `teal`, …).

### Tasks

- **Importance**: Low / Normal / High / Critical.
- **Urgency**: computed from importance + deadline, shown as a colour-coded label on each card (Overdue / Due today / Due in Xd).
- **Effort**: 5 m → 15 m → 30 m → 1 h → 1 h 30 → 2 h → 3 h → 4 h → Full day.
- **Priority score**: urgency × weight + importance × weight − effort × weight + staleness × weight; weights stored in `priority_profiles` table.
- **Recurring tasks** (two flavours):
  - *Fixed* — fires on a fixed schedule regardless of completion date (e.g. rent).
  - *Cyclic* — next instance anchors to completion date (e.g. "clean every 7 days"). The `recurrence_anchor` field supports this; full scheduling logic is a planned extension.
- **Subtasks** — full tasks linked via a parent UUID.

### Events

Full calendar events with location, description, optional recurrence (daily / weekly / weekdays / monthly / yearly, or a custom iCal RRULE string), and an all-day toggle.

Recurring events use a master/override model:
- **Master row** holds the RRULE; virtual occurrences are expanded at read time.
- **Override rows** (child events) record per-occurrence edits.
- **Deleted occurrences** are recorded in the master's `exceptions` JSON array — no stale "cancelled" rows appear in search results.

When editing a recurring event the frontend asks: *this occurrence only*, *this and all future*, or *all occurrences*.

### Notes and journal

Notes and journal entries are Markdown files on your filesystem — readable and editable outside the app. The backend keeps a lightweight SQLite index (UUID, title, filepath). Any `.md` file dropped into `~/planr/notes/` or `~/planr/journal/` is automatically imported on the next watcher cycle.

Frontmatter (YAML between `---` fences) stores metadata (uuid, date, tags, contexts, links).

Filenames:
- Notes: `<slug>-<YYYY-MM-DD>-<short-uuid>.md`
- Journal: `<YYYY-MM-DD>-<optional-title>-<short-uuid>.md`

The journal auto-saves 1.5 s after you stop typing; the save status is shown below the editor.

### Linking with `[[…]]`

Inside any text field, type `[[` to trigger the autocomplete dropdown. Selecting an item inserts a typed link:

| Syntax | Links to |
|--------|----------|
| `[[Title]]` | any object named *Title* |
| `[[task:Buy milk]]` | a task |
| `[[event:Team standup]]` | an event |
| `[[journal:2026-06-01]]` | a journal entry |
| `[[web:https://example.com]]` | an external URL |
| `[[file:path/to/file]]` | a local file |

Renaming an object propagates the rename through all linked documents automatically (the old title must be fetched before the update — this was a bug in 0.5.0, fixed in 0.6.0).

---

## ICS export / subscribe

Calendar feeds are available from the **Subscribe .ics ↗** link in the sidebar footer, or directly:

| URL | Contents |
|-----|----------|
| `/api/export/events.ics` | All events (VEVENT) |
| `/api/export/tasks.ics` | Tasks with due dates (VTODO) |
| `/api/export/all.ics` | Both combined |

To subscribe in GNOME Calendar, Thunderbird, or similar:

```
http://127.0.0.1:8000/api/export/all.ics
```

---

## Diagnostic endpoint

```
http://127.0.0.1:8000/api/debug/test
```

Returns table row counts and column lists — useful for checking migrations ran correctly.

---

## Requirements

- **Python 3.11+** (tested on 3.12)
- **SQLite 3.30+** (ships with Ubuntu 20.04+)
- No Node.js, no npm, no build step
- Internet on first load (Google Fonts CDN + jsDelivr CDN for marked.js and DOMPurify; all cached afterwards)

---

## Installation

### 1 — Place the project

```bash
mkdir -p ~/Documents/planr
# Copy backend/ and frontend/ here
```

### 2 — Create a virtual environment

```bash
python3 -m venv ~/.venv/planr
source ~/.venv/planr/bin/activate
pip install -r ~/Documents/planr/backend/requirements.txt
```

### 3 — Install the systemd service

```bash
bash ~/Documents/planr/backend/install_service.sh
```

This writes `~/.config/systemd/user/planr.service`, enables it, and starts it immediately. planr will auto-start on login.

### 4 — Open the app

```
http://127.0.0.1:8000
```

---

## Service management

```bash
systemctl --user status  planr        # is it running?
systemctl --user restart planr        # apply backend changes
systemctl --user stop    planr        # shut down
journalctl --user -u planr -f        # live log tail
```

---

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `PLANR_DATA_DIR` | `~/.local/share/planr/` | SQLite database |
| `PLANR_CONTENT_DIR` | `~/planr/` | Root for notes and journal files |

Override by adding to the service file under `[Service]`:

```ini
Environment=PLANR_CONTENT_DIR=/mnt/syncthing/planr
```

Then: `systemctl --user daemon-reload && systemctl --user restart planr`

---

## Making changes

**Backend** — edit any `.py` file, then `systemctl --user restart planr`.

**Frontend** — edit `frontend/index.html` and reload the browser (no restart needed for HTML/CSS/JS changes).

**Schema** — add columns to `schema.sql` and add a matching `ALTER TABLE … ADD COLUMN` in `db.py`'s `init_db()` migration block (SQLite swallows "column already exists" errors idempotently).

---

## Data layout

```
~/.local/share/planr/
└── app.db                         SQLite — tasks, events, metadata, links, tags, contexts

~/planr/
├── notes/
│   └── my-note-2026-06-01-a3f9b2c1.md    <slug>-<date>-<short-uuid>.md
└── journal/
    └── 2026-06-01-a-good-day-abcd1234.md  <date>-<optional-title>-<short-uuid>.md
```

Both file types use YAML frontmatter:

```markdown
---
uuid: a3f9b2c1-…
title: My note
date: 2026-06-01
tags: [reading, ideas]
contexts: [Personal]
links: []
---

Your content here. Link to [[task:Buy milk]] or [[journal:2026-06-01]].
```

---

## Project file structure

```
backend/
├── main.py                  FastAPI app — mounts all routers, serves frontend/
├── config.py                Path config (DATA_DIR, CONTENT_DIR, NOTES_DIR, JOURNAL_DIR)
├── db.py                    SQLite init, migrations, get_db() dependency
├── schema.sql               Full database schema with seeds
├── requirements.txt         Python dependencies
├── install_service.sh       One-shot systemd service installer
│
├── router_compat.py         ★ Main API — aggregation & priority routes the frontend calls
│                              GET /api/today  GET /api/events/day/{date}
│                              GET /api/tasks/today  GET /api/journal/today
│                              POST /api/quick-capture  GET /api/debug/test
├── router_tasks.py          Tasks CRUD
├── router_events.py         Events CRUD (master/override/virtual model)
├── router_notes.py          Notes CRUD
├── router_journal.py        Journal CRUD
├── router_links.py          [[wiki-link]] panel and autocomplete
├── router_ics.py            ICS export (RFC 5545)
├── router_tags.py           Tag management
├── router_search.py         Full-text search
├── router_contexts.py       Context CRUD
│
├── helpers.py               ★ Shared DB helpers (contexts_of, tags_of, validate_contexts, …)
│
├── model_task.py            Pydantic models — tasks
├── model_event.py                            events
├── model_note.py                             notes
├── model_journal.py                          journal
├── model_context.py                          contexts (color: hex or Tailwind name)
├── model_links.py                            links
│
├── service_priority.py      Priority scoring (weights in DB, not hardcoded)
├── service_recurrence.py    RRULE expansion; master exceptions array; override lookup
├── service_markdown.py      Frontmatter read/write for .md files
├── service_watcher.py       Filesystem watcher — auto-imports dropped .md files
├── service_links.py         [[link]] extraction, resolution, rename propagation
└── service_ics.py           iCalendar generation (RRULE UNTIL= correctly appended, per-request DTSTAMP)

frontend/
└── index.html               ★ Entire frontend — HTML + CSS + JS, no build step
                               Views: Today · Week · Month · Tasks · Notes · Journal
                               Libraries: marked.js + DOMPurify (jsDelivr CDN)
                               Features: quick-capture · context filter · [[link]] autocomplete
                                         timeline · auto-save journal · task/event/note CRUD
```

---

## Changelog

### 0.6.0 (current)
- **Frontend** added: complete single-file SPA (Today/Week/Month/Tasks/Notes/Journal views, quick-capture, context filter, `[[link]]` autocomplete, task/event/note CRUD, auto-save journal)
- **Bug fix**: rename propagation in `router_tasks.py` and `router_events.py` — old title was read after the UPDATE; it's now fetched before
- **Bug fix**: `router_events.py` delete-this now writes to master's `exceptions` JSON array instead of creating "cancelled" override rows that polluted search results; `expand_master()` in `service_recurrence.py` skips excepted dates
- **Bug fix**: ICS `rrule_until` was emitted as `EXDATE` (which excludes the date); it's now folded into the `RRULE` property as `UNTIL=` which correctly ends the series
- **Bug fix**: `_DTSTAMP` in `service_ics.py` was a module-level constant (frozen at server start); it's now computed per response
- **Bug fix**: four routers (`router_links`, `router_ics`, `router_tags`, `router_search`) were imported but never mounted in `main.py` — all routes are now reachable
- **New file**: `router_compat.py` (was missing entirely — app would not start)
- **New file**: `helpers.py` — shared DB helpers extracted from all four routers
- **Improvement**: `router_contexts.py` delete now re-homes orphaned objects to Inbox/Uncategorised instead of leaving them contextless; dead-code guard (`count ≤ 1`) replaced with system-context check
- **Improvement**: `model_context.py` color field now accepts both hex (`#rrggbb`) and Tailwind named colors (`slate`, `violet`, …), resolving the mismatch between model validation and DB seeds
- **Improvement**: CORS origin list updated; comment clarifies same-origin production vs. Vite dev-server use

### 0.5.0
- Initial backend release

---

## Troubleshooting

| Symptom | First check |
|---------|-------------|
| Blank page / spinning | Open DevTools → Console for JS errors; check `/api/debug/test` for backend health |
| 500 on any API call | `journalctl --user -u planr -f` while reproducing |
| Notes content lost | Check `~/planr/notes/` exists and is writable |
| Events not appearing | `/api/debug/test` — check `events` row count and `exceptions` column presence |
| Fonts look wrong | IBM Plex loads from Google Fonts CDN — needs internet on first load, then browser-cached |
| Port 8000 in use | Edit service `ExecStart`: add `--port 8001`; update bookmark |
| Auto-save not triggering | Check browser console; journal PATCH requires an existing entry or POST creates one |
