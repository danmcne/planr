
# 1. Core Model (Unified Object System)

All primary entities share a common structure:

* Tasks
* Events
* Notes
* Journal entries

## 1.1 Shared fields

Every object has:

* `uuid` (immutable primary identity)
* `title` (mutable, globally unique *for internal linking*)
* `date` (YYYY-MM-DD base reference; meaning depends on type)
* `contexts[]` (required, at least one)
* `tags[]`
* `links[]` (internal + external)
* `created_at`
* `updated_at`

---

# 2. Context System (GTD-inspired but generalized)

Contexts apply uniformly to all object types.

## 2.1 Base rules

* Every object must have ≥1 context
* Default assignment rules:

  * Tasks → `Inbox`
  * Events → `Inbox`
  * Notes → `Uncategorized`
  * Journal entries → `Uncategorized`

## 2.2 Editable base contexts (rename, delete, color assoc.)

Default set:

* Inbox
* Work
* Personal
* Someday
* Uncategorized

Constraints:

* At least one context must always exist
* User can add/rename/delete contexts (except system-enforced minimum presence rule)

Contexts may have subcontexts, e.g. Work.Project

---

# 3. File System Model (Markdown layer)

Notes and journal entries are filesystem-native.

## 3.1 Journal

* Path: `journal/YYYY-MM-DD-<title>.md` (title is optional)
* One entry per day

Frontmatter:

* uuid
* date (always YYYY-MM-DD)
* optional title
* tags
* contexts
* links

---

## 3.2 Notes

* Path format:

  * `<title>-<date>-<short-uuid>.md`

Rules:

* title is part of filename (human readable directory browsing)
* uuid suffix guarantees uniqueness
* if title changes → filename is renamed

Import rule:

* any `.md` dropped into `/notes` is imported:

  * assigned uuid
  * renamed to `<filename>-<date>-<short-uuid>.md`

This makes the directory usable without the app.

---

# 4. Linking System (Strict Internal Identity Model)

## 4.1 Preferred syntax

Internal links use:

* `[[Title]]`

Note that typing "[[T..." should begin an autocompletion over the range of possible titles. Note that we should consider the "title" of a journal entry here, not the date.

## 4.2 Critical constraint

To support `[[Title]]` safely:

* All titles must be globally unique across:

  * tasks
  * events
  * notes
  * journal entries (optional: usually excluded from linking target space.)

## 4.3 Identity resolution

* `[[Title]]` → resolved to UUID via index
* Display always uses current title
* Rename triggers global link update (via UUID mapping)

## 4.4 External links

* plain URLs
* file references

## 4.5 UI representation

Links are shown in a side/bottom panel:

* internal links → clickable, open object view
* external links → open browser tab

---

# 5. Task System

## 5.1 Core fields

* uuid
* title
* description
* status (Inbox / Active / Done / Deferred / Someday)
* importance (enum, not numeric in UI)
* urgency (computed from deadline or provided)
* time_estimate
* due_date (optional)
* recurrence_rule
* contexts
* tags
* links

---

## 5.2 Importance (human-readable)

Replace numeric scale with discrete labels:

E.g.
* Low
* Normal
* High
* Critical

This avoids false precision and improves scanning speed.

---

## 5.3 Recurrence model

Two types:

### A. Fixed recurring

* e.g. rent, subscriptions
* Must occur on schedule regardless of completion state

### B. Cyclic recurring (“movable”)

* Next instance is scheduled relative to completion time
* NOT rescheduled on delay
* Example:

  * “clean every 7 days”
  * completed Jan 1 → next due Jan 8
  * completed Jan 5 → next due Jan 12

Key property:

* recurrence anchor = last completion timestamp

---

# 6. Priority System (and “magic numbers” issue) (Here we want something simple, preferably without "magic numbers" ... something defensible and understandable)

The previous coefficients are explicitly *not stable design constants*.

## 6.1 Problem

Fixed weights like:

* 0.45 urgency
* 0.35 importance

are arbitrary and will break under real usage variation.

---

## 6.2 Revised approach: bounded scoring + calibration layer

Instead of a fixed weighted sum:

### Step 1: normalize dimensions

Each factor maps to [0, 1]:

* urgency → time decay curve (exponential preferred)
* importance → ordinal mapping
* effort → inverse utility curve
* staleness → log decay

### Step 2: combine with adjustable weights

Weights become:

* user-configurable profile parameters (not sure this is a great idea)
* not hardcoded constants

Default profile:

* urgency: 0.4
* importance: 0.4
* effort penalty: 0.15
* staleness: 0.05

But stored as data, not logic.

---

## 6.3 Key design choice

Do NOT treat prioritization as “truth”.

Treat it as:

* ranking heuristic
* editable behavior profile
* explainable scoring breakdown per task

---

# 7. Subtasks (explicit structure)

Yes, this is necessary.

## 7.1 Model

Tasks can contain:

* `subtasks[]` (tree structure, max recommended depth: 2–3)

Each subtask:

* uuid
* title
* status
* optional estimate
* links

---

## 7.2 Behavior rules

* Parent task completion:

  * either blocked until subtasks complete OR
  * optionally allowed “partial completion mode” (configurable)

* Subtasks inherit:

  * contexts (default)
  * tags (optional inheritance toggle)

---

## 7.3 UI constraint (important for ADHD focus)

* Only show:

  * top-level tasks in default view
  * subtasks only when expanding a task

---

# 8. Calendar / ICS Model

## 8.1 ICS support reality check

iCalendar supports:

* events (VEVENT) ✔
* recurring events ✔
* alarms ✔
* tasks (VTODO) ⚠ partially supported

## 8.2 Practical decision

* Events: full bidirectional ICS support
* Tasks:

  * export only (best-effort VTODO mapping)
  * import optional / limited

Reason:

* VTODO support is inconsistent across clients

---

## 8.3 Export modes

System must support:

1. Events only → `.ics`
2. Tasks only → `.ics` (VTODO subset)
3. Combined export → mixed calendar feed
4. “Scheduled tasks only”:

   * tasks with due date OR recurrence
   * optionally converted into calendar blocks

---

## 8.4 Task → Event conversion

Needed for export reliability:

* task becomes pseudo-event:

  * start = scheduled slot (or due date)
  * duration = time_estimate

---

# 9. Views / Tabs (finalized)

## 9.1 Daily

* time-blocked schedule
* focus tasks (max 3–7)
* journal entry

## 9.2 Weekly

* events overview
* workload distribution
* task pacing preview

## 9.3 Monthly

* events
* recurring tasks
* deadline tasks 

## 9.4 Tasks (central hub)

Filters:

* all
* inbox
* active
* done
* contexts
* tags

Sorting:

* urgency
* importance
* effort
* due date

---

## 9.5 Journal

* chronological
* per-day navigation
* navigation via tags/links
* searchable

## 9.6 Notes

* searchable
* tag/context filters
* backlink visibility

---

# 10. Linking UX (final model)

## 10.1 Inline links

* `[[Title]]` inside markdown

## 10.2 Side panel (required)

Always show:

* Backlinks
* Forward links
* Tags
* Contexts
* External links

This avoids cluttering main content.

---

# 11. Cognitive Load Constraints (hard rules)

* Default task view ≤ 7 items
* No full backlog dumps unless explicitly requested (Task tab gives this)
* Always prioritize “next action” framing
* Hide stale items unless user asks
* Recurring tasks should not accumulate visually

---

# 12. Identity and Renaming Edge Case (important)

Problem: recurring events + title uniqueness + renaming.

Resolution:

* Internal identity always UUID
* Title uniqueness enforced only for `[[Title]]` resolution
* Recurring instances:

  * either:

    * single logical object with recurrence expansion (preferred)
    * or generated instances with shared parent UUID

Preferred model:

* “master object + generated occurrences”

This avoids title duplication explosions.

There is still the problem of changing one occurrance of a recurring event. This has to remain linked via a root uuid to the original event (not the immediate parent). We should be able to change one occurrance, "this and all future" occurances, or "all occurrances" ... when changing "all occurrances", all "one-off" edits should be eliminated (all child events deleted). When editting "all occurrances", we should be editing the base event and all child events should be removed.

---

# 13. System architecture implications (brief)

* DB is canonical for:

  * tasks/events/links/indexing
* filesystem is canonical for:

  * notes/journal content
* sync layer resolves both via UUID mapping

