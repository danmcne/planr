# planr 1.7.0

## Two invisible-UI bugs found and fixed — with the test harness that
## should have existed all along

### The scope chooser was an empty overlay (1.5.0–1.6.0)
The all/this-occurrence/future dialog built its box of buttons and never
attached it to the backdrop it appended — one missing `appendChild`. On
a dark theme, a translucent empty backdrop is nearly invisible; any
click hit it and resolved as "cancel", so Save/Delete on a recurring
event silently did nothing. This is why scoped editing appeared absent.
Caught by the new full-modal jsdom harness (below) on its first run.

### Weekday toggles had state, but no styling to show it
`style.css` was linked **unversioned** — the one URL the ?v= convention
never covered — so browsers kept a pre-1.6.0 stylesheet indefinitely and
the `.on` highlight had no rules to render. The classes toggled; nothing
showed. The stylesheet link is now versioned (`style.css?v=5`), all 20
cache-bust references agree (tested), `/static` already serves
`Cache-Control: no-cache`, and the toggles got real button chrome:
neutral bordered chips, amber-filled when selected.

### Scope is now chosen when you click Edit, not at save time
On a recurring event, the view card's **Edit** button asks first —
*only this occurrence / this and future / all occurrences* — and the
editor opens with that choice in its title and a note in the form. In
only-this-occurrence mode the recurrence rule is hidden (an override
never changes the series rule). Save applies the choice without asking
again; Delete uses it too (with a scope-specific confirmation).
Unscoped paths (e.g. opening an event from Search) keep the save-time
question as a fallback. Cancelling the question keeps the view card.

### Task view card
Clicking a task in Day, Week, or Tasks views now opens the same kind of
read-only card — status, importance/effort, due date, recurrence in
words (including the moveable/fixed distinction), context, description —
with Edit and Close.

### + Event / + Task everywhere
Week view gains **+ Task**; Month view gains both buttons. All three
calendar views now match Day.

### Tests (172 total)
* **25 full-modal jsdom tests (new)** — the real `openEventModal`,
  `openEventView`, `openTaskView` driven end-to-end with a stubbed API:
  weekday toggling in context, the save-time fallback chooser, preset
  save/delete, edit-scope-first flow, cancellation, and the task card.
  This harness reproduced both reported bugs before fixing them.
* 49 unit · 17 HTTP (now checks version consistency incl. the stylesheet)
  · 22 scope end-to-end · 39 widget DOM · 4 migration — all green.
