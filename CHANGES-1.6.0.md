# planr 1.6.0

## The 1.5.0 features, actually delivered — plus weekly day toggles and a view card

### Root cause of "the 1.5.0 UI never appeared"
planr's modules are cache-busted with a `?v=N` query parameter. The 1.4.0
and 1.5.0 releases changed `shared.js` **without bumping it**, so browsers
kept serving the cached pre-update module — no "On" select, no clamp
warning, no scope chooser — while the backend (which did update) silently
translated the old widget's legacy rule format. Two fixes:

* every `?v=` reference bumped (19 files), and
* `/static` is now served with `Cache-Control: no-cache` (ETag
  revalidation keeps it cheap), so a forgotten bump can never strand a
  browser on stale modules again. Verified by an HTTP test.

### Day 29–31 clamps by default — including existing events
"Monthly starting July 31" now lands on **September 30** and
**February 28**, as specified. The clamp is applied at expansion time to
any plain day-of-month rule (legacy `month:1` included), so events
created before this release behave correctly **without re-saving**.
Rules that explicitly say BYDAY/BYMONTHDAY/BYSETPOS are never rewritten.
This deliberately replaces the RFC "skip the month" default.

### Weekly on multiple days
Weekly rules get Mo–Su toggle buttons: one event can repeat Tue+Thu or
Mon/Wed/Fri (`FREQ=WEEKLY;BYDAY=TU,TH`). Defaults to the start date's
weekday; a single-day selection matching the start date stays canonical
plain `FREQ=WEEKLY`. Interval composes (`INTERVAL=2;BYDAY=TU,TH` =
Tue+Thu of every second week).

### View before edit
Clicking an event now opens a read-only details card — when,
repeats-in-words ("Repeats monthly on the third Thursday", "Repeats
weekly on Monday, Wednesday and Friday until 2026-12-31"), context,
location, description — with **Edit** and **Close** buttons. This
applies in Day, Week, and Month views. Month-view event chips are now
directly clickable (the surrounding cell still opens the day). The
scope chooser (all / only this occurrence / this and future) appears on
save/delete from the editor, as shipped in 1.5.0 — now actually
reachable.

### Tests (136 total)
* 49 unit (adds default-clamp incl. the reported July-31 case, explicit
  rules untouched, multi-weekday expansion)
* 16 HTTP (adds the exact reported scenario end-to-end, Tue+Thu weekly,
  cache-header and version-straggler checks)
* 22 scope end-to-end · 39 widget DOM (adds toggles, humanizer) ·
  4 migration · 6 view-wiring parse checks
