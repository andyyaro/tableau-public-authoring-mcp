# Changelog

## [Unreleased]

### Added
- **The launch film.** A 68-second film of how the server works, on one architecture board: the
  JSON spec and the dry run that catches a typo, the compiler and the Hyper extract, Tableau
  Public opening the file, and publishing behind its guards, with the server's real replies and
  the repository's real screenshots. It plays at the top of the README and on its
  [watch page](https://andyyaro.github.io/tableau-public-authoring-mcp/film.html), with captions
  and a transcript. Its source is in [media/launch-film/](media/launch-film/); the MP4 is a
  release asset, not in git, and [film.yml](.github/workflows/film.yml) publishes the page to
  GitHub Pages.

## [0.1.0] - 2026-07-27

First working release. Authors Tableau workbooks, validates them in the real
Tableau Public application, and publishes through the visible desktop workflow.

### Added
- Declarative workbook spec (v0.1) with strict validation, unknown-key rejection
- `.twb` compiler using structured XML generation (no string splicing)
- Hyper extract generation - required, Tableau Public rejects live connections
- `.twbx` packaging with ZIP-slip protection and deterministic `.twb` output
- Worksheet templates: `bar`, `line`, `text_table`, `heatmap`, `scatter`, `circle`
- Calculated fields, categorical filters, color/size/label/tooltip, titles
- Desktop automation via CGWindowList + CGEvent (Accessibility is unusable here)
- Five-layer validation, incl. screenshot proof and public-URL verification
- Publishing via `File > Save to Tableau Public As...` with a frontmost-document
  precondition, `confirm_publish` gate, and `dry_run`
- 10 MCP tools; 39 tests

### Discovered (documented, not worked around)
- Tableau Public requires extracts (`Error 3C242D89`)
- Publishing lives on **File**, not Server, in the Public edition
- Tableau is Qt: Accessibility `click`/`AXPress` silently no-op; only CGEvent works
- Accessibility reports 0 windows; the Window menu lists worksheets, not documents
- Five `.twb` DTD constraints Tableau's own writer violates

### Known limitations
No dashboards, parameters, LODs, joins or live connections. `.twbx` is not
byte-reproducible (Hyper). Four templates are structurally but not visually verified.
