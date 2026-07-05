# planr 1.4.0

## Recurring events actually recur

Through 1.3.0 the recurrence rule chosen in the event editor was saved and
then never read: the calendar endpoints ran a plain date-overlap query, so a
"weekly" event appeared exactly once. Fixed by expanding rules at query time.

### Backend
* New `recurrence.py`: expands a recurring event over a date range with
  `dateutil.rrule` (RFC 5545). The stored rule is now RRULE text; legacy
  `unit:n` values written by ≤ 1.3.0 are translated on read, so existing
  events start recurring immediately after the update — no migration.
* `/api/calendar/{day,week,month}`: the overlap query also picks up
  recurring masters that started on/before the range; fetched rows are
  expanded into per-occurrence rows (same uuid, shifted `start_at`/`end_at`,
  plus `is_occurrence` and `master_start_at`). A malformed rule degrades to
  a one-off event rather than erroring the view.
* `GET /api/events` with both `start` and `end` (Review page) expands too.
* Occurrence generation is capped at 1000 per event per query window.

### New: "Nth weekday" rules
* The event editor's Monthly/Yearly options gain an **On** select, phrased
  from the start date: *on day 14* / *the second Tuesday* / *the last
  Tuesday* (last-weekday offered when the date is in the month's final
  week); yearly adds the month (*the second Tuesday of July*). Emitted as
  `FREQ=MONTHLY;BYDAY=2TU`, `BYDAY=-1FR`, `FREQ=YEARLY;BYMONTH=7;BYDAY=2TU`.
* The labels re-derive when the start date changes; the weekday/position is
  recomputed from the current start date on save.

### Frontend
* Opening an occurrence re-fetches and edits the master — previously an
  occurrence row's shifted dates would have been written back over the
  series on save.
* Recurring events are marked ↻ in Day, Week, and Month views.
* Deleting a recurring event asks "Delete this repeating event and all its
  occurrences?".

### Semantics and limits
* Wall-clock times are preserved across DST (calendar semantics).
* `FREQ=MONTHLY` from a start on the 29th–31st skips months lacking that
  day (RFC behaviour); use the *last …* form for "last Friday" intent.
* `UNTIL=`/`COUNT=` in a rule are honoured by the backend; the editor does
  not offer them yet ("repeat until" is the natural next increment).
* Per-occurrence overrides ("edit/delete only this occurrence") are not
  supported: editing affects the series. Task recurrence is untouched (it
  is stored but not yet acted on — same as 1.3.0; flagged for a future
  version).

### Tests
* `tests/test_recurrence.py` — 27 unit tests on expansion: weekly/biweekly,
  2nd/5th/last weekday, day-31 skipping, yearly Nth-weekday across years,
  window straddling via duration, all-day series, legacy format, malformed
  rules, COUNT/UNTIL.
* `tests/test_recurrence_http.py` — 11 end-to-end tests against a live
  server on a temp DB, covering day/week/month/list endpoints, the legacy
  format, and non-recurring passthrough.
  Run both with `.venv/bin/python tests/<file>.py`.
