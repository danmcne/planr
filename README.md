# planr

A self-hosted, local-first personal information manager: a capable
calendar/todo app, a journal, and a zettelkasten-style notes system
(wiki-links, backlinks, tags) in one small web app.

* **Single source of truth**: SQLite (with FTS5 full-text search).
* **Filesystem-canonical text**: notes and journal entries live as Markdown
  files with YAML frontmatter; the database indexes them and reconciles by
  UUID, so you can edit the files with anything (including Obsidian).
* **No build step**: FastAPI backend, vanilla-JS ES modules, one CSS file.
  No npm, no bundler.
* **Dark-first IBM Plex design**, 24-hour times, ISO dates everywhere
  (`YYYY-MM-DD`) — never mm/dd/yyyy.

---

## Pages

| Page | What it shows |
|---|---|
| **Day** | Time grid (06:00–22:00) with an all-day strip, plus the day's task list with effort filter. |
| **Week** | Seven columns, an all-day lane row for spanning events, task-deadline chips per day. |
| **Month** | Classic grid; event chips with continuation styling, task dots by importance. |
| **Tasks** | Full task list with status/importance/effort/context filters, priority-sorted. |
| **Journal** | One entry per day (or titled entries), Markdown editor with links panel. |
| **Notes** | Sidebar + tabbed editor — multiple notes open at once; tabs persist. |
| **Review** | GTD-style five-step weekly review flow. |
| **Search** | FTS5 search across everything, plus filters and tag browser. |
| **Contexts** | Manage the context tree and per-context colors. |

## Contexts, colors, and the root filter

Contexts form a tree (`work`, `work.training`, `personal.home`, …). Each
context can have its own color on the Contexts page.

* **Root filter (top bar)**: chips for every root context. Click one or
  more to restrict *all* views — calendar, tasks, journal, notes — to those
  trees (e.g. only `work`, or `work` + `inbox`). Click **All** to clear.
  The selection persists across pages and restarts. While a filter is
  active, items *without* a context are hidden.
* **Two-color display**: every event block, all-day pill, spanning bar,
  month chip, and task context badge shows its **root context color on the
  left edge** and its **own (sub)context color as fill/text**. Give
  `work.project` its own color on the Contexts page and its items read as
  "work, project-flavoured" at a glance. Subcontexts without their own
  color simply inherit the root color.

## Events

Events have **one start datetime and one end datetime**.

* **Timed, single day** — a block on the grid.
* **All-day** (checkbox) — a pill/bar across its whole date range.
* **Timed, multi-day** (e.g. a conference Mon 09:00 → Fri 16:00):
  * first day: timed block from 09:00, labelled `09:00 →`
  * middle days: all-day (pill in Day view, spanning bar in Week view)
  * last day: timed block until 16:00, labelled `→ 16:00`
  An event ending at exactly 00:00 belongs entirely to the previous day.

### Recurring events

Set **Repeats** in the event editor: daily, weekly, monthly, or yearly,
with an *Every N* interval. Weekly rules offer **day toggles** — one
event can repeat on Tuesday and Thursday, or Mon/Wed/Fri (defaults to
the start date's weekday). Monthly and
yearly rules add an **On** choice derived from the start date — e.g. for
a start on Thursday 2026-07-16: *on day 16* or *the third Thursday*;
yearly rules pin the month (*the third Thursday of July*). Only the
1st–4th weekday is offered (a "5th Tuesday" exists only in some months);
dates in a month's final week get *the last Thursday* instead. Any
day-of-month rule on the 29th–31st (and yearly February 29) **clamps**:
in months lacking that day the occurrence falls on the month's last day.
The editor shows a warning when you pick such a rule, and the clamp is
planr's default interpretation — it applies to existing plain monthly
rules too, no re-save needed.

Occurrences are computed at view time from the stored rule (RFC 5545
RRULE via `dateutil`) — nothing is materialised into the database.
Recurring events are marked ↻ in every view.

**Clicking an event or task** (in Day, Week, Month, or Tasks views —
Month chips open the event directly; the cell around them still opens
the day) shows a read-only details card: when/due, repeats-in-words,
context, location, description — with an **Edit** button leading to the
editor. For a recurring event, clicking Edit first asks which part to
edit — *only this occurrence*, *this and all future occurrences*, or
*all occurrences* — and the editor then shows and applies that choice
(in only-this-occurrence mode the series rule is hidden, since it stays
unchanged). Delete offers the same three scopes.


**Editing and deleting** an occurrence asks for a scope:

* *Only this occurrence* — the series gains an exception and (for edits)
  a standalone override event carries your changes.
* *This and all future occurrences* — the series is split: the earlier
  part is capped, a new segment carries the changes onward.
* *All occurrences* — a **reset**: this scope removes all other edits.
  The whole series collapses back to one clean rule carrying exactly
  what the form says. One-off edited occurrences are un-edited — their
  rows are deleted and they rejoin the regular grid (monthly on the 5th
  changed to the 7th puts *everything* on the 7th, including an
  occurrence you once moved to the 4th). Previous this-and-future
  splits are merged away and the old split-caps lifted. The one thing
  that survives is outright *deletion*: occurrences you removed stay
  removed, re-timed onto the new schedule.

All parts of a series stay linked under one root in the database, so
*all occurrences* always means all of them.

## Tasks

GTD-flavoured: status (`inbox / active / waiting / someday / done`),
importance (`low / normal / high / critical`), effort (`low / medium /
high`), optional due date, context, recurrence. A normalized **priority
score** (importance, urgency from due date, effort, age) orders every list.

## Quick capture (top bar)

Type and press Enter. Prefix with `>` to create an **event** instead of a
task.

| Token | Meaning | Example |
|---|---|---|
| `+context` | assign (and auto-create) a context | `+work.training` |
| `!importance` | `!low !normal !high !critical` | `!high` |
| `~effort` | `~low ~medium ~high` | `~low` |
| `^date` | due date (tasks) / start (events) | `^2026-06-12` |
| `#tag` | tag | `#clients` |

Example: `Send program to client +work.training !high ~low ^2026-06-12 #clients`

## Linking (wiki-links)

Type `[[` in any description, note, or journal entry for autocomplete
(anchored at your cursor). Typing digits — `[[2026-06` — also searches
dates (journal entry dates, event starts, task due dates).

| Syntax | Links to |
|---|---|
| `[[Title]]` | any object by title |
| `[[task:Title]]` `[[event:…]]` `[[note:…]]` `[[journal:…]]` | typed link |
| `[[note:Title-1a2b3c4d]]` | exact link by short UUID (what autocomplete inserts) |
| `[[web:Site name<https://example.com>]]` | external web page (new tab) |
| `[[file:My PDF</home/me/docs/x.pdf>]]` | local file — opened by the desktop via `xdg-open` |

Links and `#tags` appear as clickable chips in the links panel (editor
sidebar and inside task/event modals). Backlinks are tracked in the DB.

## Search

The Search page covers titles and content (FTS5) plus, for digit-leading
queries (`2026`, `2026-06-12`), the date fields. Filters: type, context,
status, date range.

## Keyboard

`←` / `→` previous/next · `t` today · `d` / `w` / `m` jump between Day,
Week, Month.

---

## Import / Export

The **⇅** button in the top bar opens the transfer dialog.

**Export.** Calendar data exports as standard iCalendar (`.ics`) —
events, tasks, or both, optionally restricted to one context and its
descendants. Recurring series export faithfully: the rule as RRULE
(legacy rules translated, day-31 clamping made explicit), deleted
occurrences as EXDATE, and one-off edited occurrences as proper
RECURRENCE-ID components sharing the series UID, so other calendar
applications reassemble the series correctly. Tasks export as VTODO
(due date, status, priority), with `X-PLANR-*` properties preserving
planr-specific detail (effort, moveable/fixed recurrence) for lossless
round-trips. Journal and Notes export as `.zip` archives of their
canonical Markdown files, frontmatter included.

**Import.** `.ics` files import events and tasks; series with
RECURRENCE-ID components are reassembled into master + overrides.
Times are read as literal wall-clock values (planr keeps naive local
times; time zones in the file are ignored). Each item can land in a
chosen context, and optionally the file's CATEGORIES are matched
against your existing context paths first. Duplicates — same title and
same start (events) or due date (tasks) — are skipped and counted.
Journal zips take the entry date from planr's own frontmatter or
filename, falling back to the file's date inside the archive; imports
are skipped when the same day already has identical content, and an
untitled import that would collide with an existing untitled entry
becomes a titled one. Notes take their title from frontmatter or the
cleaned filename (planr's own `-date-shortuuid` suffix stripped);
identical title-and-content duplicates are skipped, and a title
collision with different content imports with an "(imported)" suffix.

## Install

```sh
./install.sh            # creates venv, installs deps, sets up planr.service
# or manually:
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn main:app --port 8000
```

Data locations (override with env vars): database `PLANR_DB`, notes dir
`PLANR_NOTES_DIR`, journal dir `PLANR_JOURNAL_DIR`.

## Updating

**Always update into a clean code directory** — see `UPDATING.md`. In
short: stop the service, remove the old *code* (your DB/notes/journal are
elsewhere and untouched), unzip the new version, restart, hard-refresh the
browser (`Ctrl+Shift+R`). Unzipping over an old tree leaves removed files
behind and is the classic cause of "the fix changed nothing" — a stale
`main.py` keeps serving old routes and stale JS keeps old bugs alive.

## Architecture notes

See `planr-arch.txt` (design) and `app-reqs.txt` (requirements).
Stack: FastAPI + Jinja2 + SQLite (FTS5) · vanilla ES modules · IBM Plex.
API under `/api/*`; pages are thin Jinja templates hydrated by one JS
module each; `shared.js` holds the API client, modals, capture, wiki-link
autocomplete, root filter, and rendering helpers.
