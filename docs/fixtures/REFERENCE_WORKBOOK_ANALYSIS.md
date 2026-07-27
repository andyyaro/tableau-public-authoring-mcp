# Reference Workbook Forensics

**Source:** the user's own published workbook (correct fixture: it represents the
kind of workbook this MCP will author most often).
**Canonical URL:** <https://public.tableau.com/app/profile/<your-profile>/viz/the reference workbook/Matrix-ActionDecisionQuadrant>
**Downloaded:** 2026-07-26 · **Hash + counts:** `REFERENCE_WORKBOOK_MANIFEST.json`
**Element classification:** `REFERENCE_WORKBOOK_ELEMENT_MAP.csv`

The original `.twbx` is **not committed** (see `.gitignore`); its SHA-256 is recorded
so mutation is detectable.

## Verified structure

Every lead in the master prompt was re-checked rather than assumed. All confirmed:

| Claim | Verified |
|---|---|
| ~12 worksheets | 12 |
| ~13 data sources | 13 |
| 3 calculated fields | 3 |
| No dashboards | 0 dashboards, 0 stories, 0 parameters |
| One flat CSV per worksheet | 13 federated->textscan CSVs, 0 joins, 0 custom SQL |
| Built by 2026.2.0 | `source-build 2026.2.0 (20262.26.0603.1643)`, `source-platform mac` |
| Doc version 18.1 | `version="18.1"` |

## Composition of the 514,262-character `.twb`

| Section | Chars | Share |
|---|---:|---:|
| 13 `<datasource>` blocks | ~402,600 | **78%** |
| 12 `<worksheet>` blocks | ~94,800 | 18% |
| everything else | ~17,000 | 3% |

The bulk is mechanical data-source scaffolding — and most of *that* is the
`<extract>` block, which exists because publishing creates extracts. Design-bearing
worksheet blocks are only 5.5-10.8 KB each. This is what makes template-derived
compilation viable.

## Mark types present (7 distinct)

`Bar` x2, `Square` x3, `Line` x2, `Shape` x2, `Circle` x1, `GanttBar` x1,
`Automatic` x1 — effectively a pattern library in a single file.

## Structures the compiler adopted

```
workbook/
  preferences
  datasources/datasource
    connection[@class=federated]/named-connections/named-connection/connection[@class=textscan]
    connection/relation/columns/column
    connection/metadata-records/metadata-record
    aliases, column (+ calculation), extract, layout
  worksheets/worksheet
    layout-options/title/formatted-text/run
    table/(view, style, panes, rows, cols)      <- order is MANDATORY
      view/(datasources, datasource-dependencies, filter*, slices?, aggregation)
      panes/pane/(view, mark, encodings)
  windows/window/cards
```

Column-instance naming: `[none:Field:nk]`, `[sum:Field:qk]`, `[attr:Field:nk]`.
Shelf references are fully qualified: `[federated.<id>].[sum:Field:qk]`.

## What was deliberately NOT copied

`repository-location` (identifies a *published* workbook), `simple-id`,
`object-graph`, `semantic-values`, the 13 `#TableauTemp_*.hyper` files, all real
site data, and every user-identifying path. Generated workbooks are asserted free of
machine identifiers before packaging.

## Corrections the fixture forced

Two things Tableau **writes** but **rejects on load** — the writer is more permissive
than the loader:

- `<object-graph>` inside `<datasource>`
- `object-id` / `user-specific` on `<extract>`

Both are omitted by the compiler.
