# Roadmap

Current status by capability lives in `docs/architecture/CAPABILITY_BOUNDARY.md`.
This file is only what is **not** done yet, plus what shipped, so that nothing is
listed as future work twice.

## Shipped (was on this roadmap, is no longer future work)

- **Every template screenshot-verified individually.** `line`, `heatmap`,
  `scatter` and `circle` - plus `bar`, `text_table` and `map` - are each opened
  in the real Tableau Public and checked for coloured ink on the canvas by
  `tests/live/test_render_templates.py`.
  `test_all_supported_templates_are_covered` fails if a template is added to
  `SUPPORTED_TEMPLATES` without a live case.
- **Dashboards.** No longer deferred. A generated dashboard opens in Tableau
  Public 2026.2.0 with its title, both tiled worksheets and a fixed 1200x800
  canvas; `tests/live/test_dashboard.py` re-checks each zone's own slice of the
  canvas, so a zone whose worksheet reference silently fails to resolve is caught.
  See `docs/LIMITATIONS.md` §8.
- **Window management.** `desktop/window_control.py` classifies, raises,
  un-minimises and closes specific documents, and distinguishes a live window
  from the husk the window server keeps for a destroyed one - the misunderstanding
  that caused four separate bugs (`docs/LIMITATIONS.md` §10).
- **Overwrite-aware publishing.** `publishing/existing.py` queries the profile's
  published workbooks before an irreversible publish, compares both the raw title
  and Tableau's normalised repo-URL form, and fails **closed** when the lookup
  cannot complete. `profile` is now a required argument, because the check was
  previously gated on it being supplied.

## Verified by hand, not by a test

Two capabilities `CAPABILITY_BOUNDARY.md` lists as verified rest on a manual
screenshot taken once, with **no automated coverage**. They are real - the
screenshots exist - but nothing will notice if a future change breaks them:

| Capability | Evidence | What is missing |
|---|---|---|
| `size` encoding | `output/screenshots/size-gate.png` (`output/SizeEncodingGate.manifest.json`) | no test asserts that mark radii vary. The live `map` case does put `size` on a shelf, but its assertions only measure ink and chroma across the whole canvas, which a size-less render passes just as well. |
| Multiple data sources | `output/screenshots/multisource-gate.png` (`output/MultiSourceGate.manifest.json`) | no test builds a two-source workbook at all. Every spec in `tests/` declares exactly one data source. |

Closing these two is the next unit of work.

## Open

### Verification
- Per-sheet validation: switch sheet tabs and capture each one. Every live render
  case currently builds a **single-worksheet** workbook, so a multi-sheet
  workbook's second tab has never been photographed. The dashboard test crops
  per-zone, which is the closest thing that exists and is not the same check.
- Detect Tableau version drift: the compiler hardcodes
  `SOURCE_BUILD = "2026.2.0 (…)"`, and `app_version()` can already read the
  installed build, but nothing compares the two or warns when the templates may
  be stale.
- Re-derive templates automatically against a new Tableau build.

### Richer analytics
Parameters, LOD expressions, table calculations, sets/groups, reference lines,
joins and custom SQL, date hierarchies.

### Filling in the partial capabilities
- Map extras: filled/choropleth maps, custom territories, map layers, spatial
  files, custom geocoding.
- Dashboard extras: filter cards, colour legends, highlighters, parameter
  controls, images, floating zones, device layouts, dashboard actions.

## Not planned
Anything requiring a private Tableau endpoint, credential handling, or bypassing
platform limits. Publishing will always go through the visible UI.
