# planr 1.5.0

## Recurring events: Nth-weekday rules, day-31 clamping, edit scopes

### Nth weekday of the month / year
The event editor's Monthly and Yearly **On** choices now reliably cover
"the third Thursday" (monthly) and "the third Thursday of July" (yearly),
emitted as `FREQ=MONTHLY;BYDAY=3TH` / `FREQ=YEARLY;BYMONTH=7;BYDAY=3TH`.
Only the 1st–4th weekday is offered — a "5th X-day" exists only in some
months; dates in a month's final week are offered *the last X* instead
(`BYDAY=-1TH`). The widget is now covered by DOM-level tests (jsdom), not
just a parse check. If the "On" select ever seems missing after an update,
hard-refresh (`Ctrl+Shift+R`) — stale `shared.js` is the classic cause.

### Day 29–31 clamps instead of skipping
A monthly rule on day 29/30/31 (and a yearly rule on February 29) now
means "that day if it exists, otherwise the last day of the month",
emitted as `BYMONTHDAY=28..d;BYSETPOS=-1` — pure RFC 5545, no special
cases in the expander. The editor shows a warning explaining the clamp
when such a rule is selected. (Pre-1.5.0 plain `FREQ=MONTHLY` rules on
day 31 keep the standard's skip behaviour; re-save the event to adopt
the clamp.)

### Edit scopes: all / only this occurrence / this and future
Saving or deleting a recurring event now asks for a scope:

* **Only this occurrence** — iCal-style override: the series rule gains an
  exception date (`recur_exceptions`), and edits create a standalone
  override event (`parent_uuid` → its segment, `recurrence_id` = the
  original occurrence datetime).
* **This and all future occurrences** — the segment's rule is capped with
  `UNTIL` one second before the chosen occurrence; a new segment row
  carries the (possibly edited) series onward. Exception dates after the
  split move to the new segment.
* **All occurrences** — reaches every row sharing the series root:
  masters, split segments, and overrides, past and future. Text fields
  (title, description, context, location) are overwritten everywhere;
  start/end move by the delta you applied (an override you had moved
  keeps its relative offset); exception dates and `UNTIL` bounds shift
  with the series. A rule change propagates to all segments **only when
  you structurally changed it** (so a title edit can't flatten a future
  segment's different pattern), and each segment keeps its own
  `UNTIL`/`COUNT` — a past split can never resurrect its occurrences.

All parts of a series share one `root_uuid`, so *all occurrences* always
finds all of them — exactly the iCal split model on export, one root
group in the database.

### Schema
Two columns added to `events`: `recur_exceptions` (comma-separated ISO
datetimes) and `recurrence_id` (on override rows, the occurrence they
replace). The migration is automatic and idempotent on startup; existing
data is untouched (covered by `tests/test_migration.py`).

### API
* `PUT /api/events/{uuid}` accepts `scope` (`all` | `occurrence` |
  `future` | `this`) and `occurrence_at` (the original start of the
  occurrence being edited). Without `scope`, behaviour is unchanged.
* `DELETE /api/events/{uuid}` accepts the same as query parameters.

### Frontend
* Occurrence rows now prefill the editor with the occurrence's own dates
  (1.4.0 redirected to the master; with scopes, the occurrence is the
  natural reference). The scope chooser appears on save/delete of any
  series member; overrides offer *only this event* / *all in the series*.
* Clamp warning line under the recurrence controls.

### Tests (100 total)
* `tests/test_recurrence.py` — 41 unit tests (adds clamp expansion,
  exception skipping, rule merge/shift/UNTIL helpers).
* `tests/test_scopes_http.py` — 22 end-to-end tests of the full scope
  lifecycle: override → split → edit-all across the root group →
  rule-change propagation with UNTIL preservation → scoped deletes →
  clamp behaviour through the calendar endpoints.
* `tests/test_recurrence_http.py` — 11 (unchanged, still green).
* `tests/test_widget.js` — 22 DOM tests of the editor widget (jsdom).
* `tests/test_migration.py` — 4 tests upgrading a 1.4.0 database.
