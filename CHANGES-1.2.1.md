# planr v1.2.1 — changelog

Separate /day, /week, /month pages are back (the unified /calendar page is
gone; old /calendar bookmarks redirect). Nav and URLs match v1.1.x.

## Multi-day events — correct semantics

An event has ONE start datetime and ONE end datetime. A timed multi-day
event (e.g. conference Mon 09:00 → Fri 15:00) now displays as:

* **first day** — timed block from 09:00, labelled `09:00 →`, dashed
  bottom edge;
* **middle days** — all-day: pill in the day view strip, spanning bar in
  the week view lane row (with ◂ ▸ when it continues beyond the bar);
* **last day** — timed block until 15:00, labelled `→ 15:00`, dashed top
  edge.

All-day events (`all_day = 1`) span their whole range as bars. A timed
event ending exactly at 00:00 belongs entirely to the previous day
(Mon 20:00 → Tue 00:00 renders as Monday 20:00–24:00 only). Two-day events
without middle days (Wed 21:00 → Thu 10:00) produce just the two boundary
blocks. Clicking any segment opens the one event with its real start/end.

## Date entry — always YYYY-MM-DD

The dropdown pickers are gone, and so is the bare native date input
(browsers render that in *their* locale — mm/dd/yyyy on an en-US browser,
which is what you were seeing). Date fields are now a plain text input that
always shows ISO `YYYY-MM-DD` (red border while invalid) plus a 📅 button
that opens the native browser calendar popup; picking a date writes ISO
back into the field.

## Modals (new task / new event)

* Wiki-link autocomplete now works in the event description (it was never
  wired up — only the task modal had it).
* Both modals have a live links/tags panel under the description showing
  internal links, external links, and #tags as clickable chips.
* Editing an event no longer rounds its times to the nearest 30 minutes.

## Autocomplete positioning

The `[[` dropdown now anchors at the text caret (mirror-div measurement),
not at the bottom edge of the textarea — in the full-page journal/notes
editors it used to appear at the bottom of the screen. It flips above the
caret when there is no room below.

## Search over date fields

* Search page: a query starting with digits (e.g. `2026`, `2026-06`,
  `2026-06-12`) also matches journal entry dates, event start dates and
  task due dates. (Previously `2026-06` crashed the FTS engine — `-` is an
  FTS5 operator; queries are now phrase-quoted.)
* Wiki-link autocomplete: `[[2026…` matches date fields too, per the spec,
  and results show the object's date.

## External links — syntax and behaviour

Per the architecture doc:

* `[[web:Some site<https://example.com>]]` — opens in a new tab.
* `[[file:My PDF</home/me/docs/x.pdf>]]` — opened by the desktop via a new
  `POST /api/open` endpoint (`xdg-open`); browsers refuse `file://` links
  from an http page, so the server hands the path to the OS instead.

Both kinds appear in the links panel (editor side panel and modal panel)
as clickable chips. The empty-state hint in the links panel documents the
syntax, as do the description placeholders.

## Also

* Month view fixed (duplicate `const` SyntaxError killed the module;
  adjacent-month cells also carried the wrong year around January).
* Week view gained the all-day lane row and labelled task-deadline chips.
* `GET /api/events?start=…` no longer drops events without an end.
* Quick capture context prefix is `+` (e.g. `+work.training`); the parser
  no longer mangles titles containing `+` (e.g. "5+3 split").
* New `static/js/cal-common.js` shares the time-grid layout between day
  and week views. Keyboard: ←/→ navigate, `t` today, `d`/`w`/`m` switch view.
