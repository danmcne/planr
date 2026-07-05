# planr v1.3.0 — changelog

## New

* **README.md** — full feature and syntax reference (capture tokens,
  wiki-link / web / file link syntax, keyboard shortcuts, install/update).
* **Root-context filter** (top bar): one chip per root context plus "All".
  Toggle any combination to restrict every view — Day, Week, Month, Tasks,
  Journal sidebar, Notes sidebar — to those context trees (e.g. only work,
  or only personal). Selection persists across pages and restarts
  (localStorage). While a filter is active, items without a context are
  hidden.
* **Two-color contexts**: events, all-day pills, week spanning bars, month
  chips, and task context badges show the ROOT context color on the left
  edge and the item's own (sub)context color as fill/text. Assign
  `work.project` its own color on the Contexts page to distinguish it from
  plain `work` items; subcontexts without a color inherit the root color.
  Backed by a `root_color` field added to event/task/note/journal API
  responses.

## Changed / hardened

* day.js / week.js / month.js are now fully self-contained modules
  (import only from shared.js) — no cross-file JS dependencies to go stale
  in a partial deploy.
* All script tags and shared.js imports carry a `?v=3` cache-buster with a
  single consistent specifier (mixed specifiers would instantiate
  shared.js twice).
* Month and week views render their grid scaffolding even if the API call
  fails, and surface the error as a toast — a blank page can no longer
  fail silently.
* Week view creates its all-day lane row dynamically if the template
  predates it.
