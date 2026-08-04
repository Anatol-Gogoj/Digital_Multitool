# Digital Multitool (repo: SCPI_Control) — agent context

Tk bench-control app for SCPI lab instruments + the SLDEA test/analysis
suite. Deep context lives in `README.md` (setup, quirks — every instrument
quirk there is bench-verified), `SLDEA_HANDOFF.md` (decision log),
`SLDEA_MEASUREMENT.md` (error budget), `docs/manual-src/README.md`
(manual pipeline + release checklist).

## Conventions that override defaults

- **Changelogs/release notes/PR bodies start with a dumb TL;DR** — two or
  three plain sentences a tired labmate can skim, before any wordy
  sections. Applies to GitHub releases, PR descriptions, and new
  `SLDEA_HANDOFF.md` entries.
- **Never ship bench-unverified instrument I/O.** New SCPI paths need a
  bench session; until then they are documented follow-ups, not code.
  Existing bench-verified claims in README/code comments cite dates —
  keep that habit.
- **Releases ship regenerated manuals** — both `docs/*.html` and `.pdf`
  (see `docs/manual-src/README.md` "Releasing" + `version.py` docstring).
- **Run data never enters the repo.** `.gitignore` blocks run folders and
  their outputs; if a new capture artifact type appears, extend
  `.gitignore` in the same PR that introduces it.
- **Behavior changes land with a dated observation → decision entry in
  `SLDEA_HANDOFF.md`** when they touch the SLDEA measurement chain.
- Plot styling: Anatol prefers the **Paul Tol bright** palette family for
  scientific plots.
