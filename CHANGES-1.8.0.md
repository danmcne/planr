# planr 1.8.0

## "Edit all occurrences" now unifies times — the fix for the
## override-not-reached report

The reported sequence (one-off edit → future split → edit-all from a
future occurrence) was replayed end-to-end — real modals driving a real
server — and text edits *did* reach the one-off override at every
level. What did not behave as expected was **time**: the old semantics
applied a time change as a relative shift, so an occurrence you had
moved to a different time kept its offset instead of adopting the new
series time — indistinguishable, on the calendar, from the edit not
reaching it.

Edit-all is now **unify**: every row in the series — masters, split
segments, and one-off overrides — adopts the new time-of-day and
duration, keeping its own date (shifted by any date change you made).
The bookkeeping follows: exception dates and each segment's UNTIL bound
are re-timed, so split boundaries survive even a move to an *earlier*
time (which under naive handling would resurrect the capped master's
occurrence on the split date as a duplicate). Covered by new unit tests
(retime helpers, both directions), updated scope integration tests, and
two new end-to-end scenarios replaying the report, one text-based and
one time-based.

If your case genuinely involved a *text* edit not reaching an override,
that would be a distinct bug none of the three test levels can
reproduce — the exact edit you made would help.

## Import / Export

A **⇅** button in the top bar opens the transfer dialog.

* **Calendar → .ics** — events, tasks, or both; optionally one context
  subtree. Series export with RRULE (legacy rules translated, day-31
  clamping made explicit), EXDATE for deleted occurrences, and proper
  RECURRENCE-ID components (sharing the master's UID) for one-off
  overrides. Tasks are VTODOs with DUE/STATUS/PRIORITY plus X-PLANR-*
  fields (effort, moveable/fixed) for lossless round-trips. Times are
  floating local wall-clock — planr's native semantics.
* **Journal / Notes → .zip** of the canonical Markdown files.
* **Import .ics** — series reassembled from UID groups (base = master,
  RECURRENCE-ID components = overrides). Time zones in the file are
  ignored; the literal clock time is taken. Items land in a chosen
  context, optionally matching the file's CATEGORIES against existing
  context paths first. Duplicates (same title + start/due) skipped and
  counted.
* **Import journal .zip** — entry date from frontmatter/filename, else
  the file's date in the archive; duplicates skipped by uuid or
  (date, content); untitled collisions become titled entries.
* **Import notes .zip** — title from frontmatter or cleaned filename
  (planr's own -date-shortuuid suffix stripped); duplicates skipped by
  uuid or (title, content); title collisions suffixed "(imported)".

## Tests (205 total)

* **25 transfer round-trip tests (new)** — two live servers: export
  from A, import into fresh B, verify calendar/journal/notes
  equivalence (including override reassembly and escaping), re-import
  proves duplicate skipping, foreign files exercise the fallback rules.
* 13 end-to-end UI↔server (was 10; + time-unification scenario)
* 31 full-modal jsdom (was 25; + transfer dialog)
* 54 unit (+ retime helpers) · 22 scope (unify expectations) ·
  17 HTTP · 39 widget DOM · 4 migration — all green.

Cache-bust version is now `?v=6` across all 20 references (tested).
