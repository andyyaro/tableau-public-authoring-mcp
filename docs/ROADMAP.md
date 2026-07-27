# Roadmap

## v0.2 — close the verification gap
- Screenshot-verify `line`, `heatmap`, `scatter`, `circle` individually
- Per-sheet validation (switch tabs, capture each)
- `size` encoding visual confirmation
- Multi-data-source live test

## v0.3 — dashboards
Deliberately deferred: dashboard XML (zones, layout containers, sizing) is the
most intricate part of the format and the reference workbook contains **zero**
dashboards, so there was no verified structure to derive from. Needs a fixture
that actually contains one.

## v0.4 — richer analytics
Parameters, LOD expressions, table calculations, sets/groups, reference lines,
joins and custom SQL, date hierarchies.

## v0.5 — robustness
- Window management: close/raise specific documents reliably
- Re-derive templates automatically against a new Tableau build
- Detect Tableau version drift and warn when templates may be stale
- Overwrite-aware publishing (query existing workbooks first)

## Not planned
Anything requiring a private Tableau endpoint, credential handling, or bypassing
platform limits. Publishing will always go through the visible UI.
