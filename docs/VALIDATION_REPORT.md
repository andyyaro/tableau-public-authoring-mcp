# Validation Report

**Frozen record of the v0.1.0 validation run.** Dated 2026-07-27 · Tableau
Public 2026.2.0 · macOS 26.5.1 arm64.

> **This document is not maintained and is superseded by
> `docs/architecture/CAPABILITY_BOUNDARY.md`.** It records what one validation run
> measured on one day. Read it for *how* the defects below were found - the load
> failures and their fixes are the durable part. Do **not** read it as the current
> capability list, and do not read any count in it as the current count; both have
> moved on. Capability status lives in `CAPABILITY_BOUNDARY.md`, limitations in
> `docs/LIMITATIONS.md`, and gate numbers come from re-running the commands.

## Layer 1 - specification validation

Rejects unknown keys, invalid templates, missing CSVs, duplicate worksheet names,
unresolvable field references, duplicate data-source ids, bad aggregations, and
template shelf violations. **PASS**

At the time of this run a `dashboards` key was rejected outright. **That is no
longer true**: dashboards are parsed, compiled and verified rendering in Tableau
Public 2026.2.0. `tests/unit/test_spec_validation.py:92` documents the removal of
that rejection, and `tests/unit/test_dashboards.py` holds the dashboard contract.

## Layer 2 - generated-file validation

Well-formed XML; required attributes; unique worksheet names matching the spec;
resolvable data-source and column references; no field-less worksheets; `.twbx`
contains exactly one `.twb`, all CSVs, and a `.hyper` per data source; every archive
entry ZIP-slip safe. **PASS**

## Layer 3 - opens in Tableau Public

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

**Final result: PASS** - opens with no corruption or repair dialog; all sheet tabs
present.

## Layer 4 - screenshot verification

`output/screenshots/full-feature-v2.png`: 12 marks rendered, status bar reads
`12 marks | 12 rows by 1 column | SUM(Readiness Score): 585.20`, title and subtitle
rendered, calculated-field colours applied, `ATTR(State)` resolves (blue, not red),
filter card shows `Status (All)`. **PASS**

## Layer 5 - publication verification

| Check | Result |
|---|---|
| Published workbook | `MCP_Authoring_Validation_-_20260727-0050` |
| Appears on profile | yes, via the reader MCP |
| Public URL | HTTP **200** |
| Live render | 12 bars, calculated-field colours, title + subtitle |
| Default view | `Readiness by Site` |
| **User's EV workbook** | **unchanged** - `revision 1.2`, identical `lastPublishDate`, `size`, `viewCount 1078` |

**PASS**

## Quality gates

Every gate below passed on 2026-07-27 at v0.1.0. The counts are deliberately not
reproduced: the suite has grown substantially since, and a number copied out of a
frozen report is a number that will be wrong. Re-run the commands in
`README.md` instead.

| Gate | Result at v0.1.0 |
|---|---|
| `ruff format --check` | PASS |
| `ruff check` | PASS (0 errors) |
| `pytest tests/unit` | PASS |
| MCP `initialize` | PASS |
| MCP `tools/list` | PASS |
| MCP tool execution | PASS |
| Server survives tool error | PASS |
| Existing MCPs preserved | PASS |

## Gaps at the time of this run - all since closed

`line`, `heatmap`, `scatter` and `circle` compiled and passed layers 1-2 on this
date but had not been individually screenshot-verified; only `bar` and
`text_table` had. **That gap is closed.** Every template in `SUPPORTED_TEMPLATES` now seven, including `map` - is opened in the real app and checked for marks by
`tests/live/test_render_templates.py`, and
`test_all_supported_templates_are_covered` fails if a template is ever added
without a live case. Current status: `docs/architecture/CAPABILITY_BOUNDARY.md`.
