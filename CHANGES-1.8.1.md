# planr 1.8.1

## "Edit all occurrences" is now a true reset

1.8.0's "unify" was still wrong: it unified values but preserved each
occurrence's own date, applying date changes as a per-row delta — so a
one-off moved to the 4th, in a monthly-on-the-5th series edited to the
7th, landed on the 6th instead of the 7th. The reported example made
the correct semantics unambiguous: **editing all occurrences removes
all other edits.**

Scope=all now collapses the entire root group back to ONE clean series
carrying the form's values:

* One-off override rows are **deleted** and their exception dates
  lifted — those occurrences rejoin the regular grid. Monthly on the
  5th changed to the 7th puts everything on the 7th, including the
  occurrence once moved to the 4th.
* This-and-future split segments are **deleted** and the master's
  split-cap removed; one uncapped rule remains (a genuine tail bound —
  UNTIL the widget cannot express — is preserved from the last
  segment, since split caps live on earlier rows and are exactly the
  edits being removed).
* The one deliberate exception: occurrences **deleted outright** stay
  deleted, re-timed onto the new schedule. Renaming a series should
  not resurrect the session you cancelled for a holiday. Covered by a
  dedicated test; easy to flip if full resurrection is preferred.
* The response of PUT scope=all is the surviving master row (the row
  addressed by the request may have been a segment that no longer
  exists).

The reported scenario is pinned verbatim as a regression test
(monthly/5th → one-off to the 4th → edit-all to the 7th → everything,
including the former one-off, on the 7th — not delta-shifted to the
6th), alongside end-to-end UI↔server proofs that the override row is
gone and its slot rejoins the grid at the new time.

## Tests (210 total)

* 25 scope integration (rewritten for reset semantics; + the verbatim
  reported case, + deletion-survival)
* 14 end-to-end UI↔server (+ override-row-purged proofs)
* 54 unit · 25 transfer round-trip · 31 full-modal · 17 HTTP ·
  39 widget DOM · 4 migration — all green.

No frontend changes; cache-bust remains ?v=6.
