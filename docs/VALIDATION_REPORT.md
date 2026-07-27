# Validation Report

**Date:** 2026-07-27 · **Tableau Public:** 2026.2.0 · **macOS:** 26.5.1 arm64

## Layer 1 — specification validation

18 unit tests. Rejects unknown keys, invalid templates, missing CSVs, duplicate
worksheet names, unresolvable field references, duplicate data-source ids, bad
aggregations, dashboards, and template shelf violations. **PASS**

## Layer 2 — generated-file validation

Well-formed XML; required attributes; unique worksheet names matching the spec;
resolvable data-source and column references; no field-less worksheets; `.twbx`
contains exactly one `.twb`, all CSVs, and a `.hyper` per data source; every archive
entry ZIP-slip safe. **PASS**

## Layer 3 — opens in Tableau Public

The decisive test, and the one that found every real defect. Five load failures were
diagnosed from Tableau's own error text and fixed:

| # | Tableau's error | Fix |
|---|---|---|
| 1 | `missing required attribute 'dim-percentage'` | added to `<layout>` |
| 2 | `no declaration found for element 'object-graph'` | omitted |
| 3 | `element 'filter' is not allowed for content model` | moved into `<view>` |
| 4 | `element 'panes' is not allowed for content model` | added required `<style>` |
| 5 | `attribute 'object-id' is not declared for element 'extract'` | removed |

Plus one **semantic** failure that produced a *loadable but blank* workbook:

| Symptom | Cause | Fix |
|---|---|---|
| `Workbooks saved to Tableau Public must use extracts` (3C242D89) | CSV live connection | generate `.hyper` extracts |
| blank canvas, filter "Not available.", red `State` pill | tooltip dimension used `derivation="None"` | promote to `Attribute` |

Isolated by a controlled three-way bisect (filter-only / calc-only / plain-color),
which proved filters and calculated fields were both innocent.

**Final result: PASS** — opens with no corruption or repair dialog; all sheet tabs
present.

## Layer 4 — screenshot verification

`output/screenshots/full-feature-v2.png`: 12 marks rendered, status bar reads
`12 marks | 12 rows by 1 column | SUM(Readiness Score): 585.20`, title and subtitle
rendered, calculated-field colours applied, `ATTR(State)` resolves (blue, not red),
filter card shows `Status (All)`. **PASS**

## Layer 5 — publication verification

| Check | Result |
|---|---|
| Published workbook | `MCP_Authoring_Validation_-_20260727-0050` |
| Appears on profile | yes, via the reader MCP |
| Public URL | HTTP **200** |
| Live render | 12 bars, calculated-field colours, title + subtitle |
| Default view | `Readiness by Site` |
| **User's EV workbook** | **unchanged** — `revision 1.2`, identical `lastPublishDate`, `size`, `viewCount 1078` |

**PASS**

## Quality gates

| Gate | Result |
|---|---|
| `ruff format --check` | PASS (27 files) |
| `ruff check` | PASS (0 errors) |
| `pytest tests/unit` | **39 passed** |
| MCP `initialize` | PASS |
| MCP `tools/list` | PASS (10 tools) |
| MCP tool execution | PASS |
| Server survives tool error | PASS |
| Existing MCPs preserved | PASS (6 connected) |

## Known gaps

`line`, `heatmap`, `scatter`, `circle` compile and pass layers 1-2 but were not
individually screenshot-verified; only `bar` and `text_table` were. Recorded in
`docs/architecture/CAPABILITY_BOUNDARY.md` as partially supported rather than
claimed as working.
