# Change history - the reasoning behind each release

Pull-request write-ups, preserved as documentation.

Commit messages record *what* changed. These record *why*: the failure each
defect actually produced, how it was reproduced, and what proved it fixed. That
reasoning is the expensive part, and it does not travel with commits, so it is
kept here.

Bot signatures and trailing links are stripped and personal identifiers
replaced; the technical content is otherwise verbatim.

---

## Tableau Public authoring MCP - v0.1 MVP (verified end-to-end)

*Merged 2026-07-27.*

### Summary

An MCP server that **authors** Tableau workbooks from a declarative spec,
**validates** them by opening them in the installed Tableau Public 2026.2.0, and
**publishes** through Tableau's own visible desktop workflow.

Verified end-to-end: the generated workbook is live on Tableau Public, returns
HTTP 200, and renders 12 marks with calculated-field colours.

### Why this architecture

Three findings constrained the design before any preference applied:

1. **No publishing API exists for Tableau Public** - the REST API covers
   Server/Cloud only.
2. **No official library can create a workbook** - the Document API states
   verbatim it cannot create files from scratch.
3. **Tableau Public ships no AppleScript dictionary** (verified: no `.sdef`, no
   `NSAppleScriptEnabled`, no URL scheme).

Strategy D (hybrid compiler + desktop validation) scored 88.3% against
alternatives; B and C score **0** on publishing because they physically cannot
publish. See `docs/architecture/`.

### What the real application taught us

Every meaningful defect was found by loading files into Tableau, not by reasoning
about XML. Five DTD violations:

| Tableau's error | Fix |
|---|---|
| `missing required attribute 'dim-percentage'` | added to `<layout>` |
| `no declaration found for element 'object-graph'` | omitted |
| `element 'filter' is not allowed for content model` | moved into `<view>` |
| `element 'panes' is not allowed for content model` | added required `<style>` |
| `attribute 'object-id' is not declared for element 'extract'` | removed |

Two of these are elements Tableau's own **writer** emits but its **loader**
rejects.

Plus two semantic failures producing loadable-but-blank workbooks:

- **Tableau Public requires extracts** (`Error 3C242D89`) - every CSV is converted
  to `.hyper`.
- **Tooltip dimensions need `attr:` derivation** - with `none:` the pill turns red
  and the canvas goes blank. Isolated by a controlled three-way bisect.

### Automation findings

- Accessibility reports **0 windows** for Tableau; window discovery uses
  `CGWindowListCopyWindowInfo`.
- The **Window menu lists worksheets, not documents**.
- Tableau is **Qt**: `click` and `AXPress` on menu items report success and do
  nothing. Only real **CGEvent** HID clicks work.
- Publishing lives on **File**, not Server, in the Public edition - Tableau's docs
  describe Desktop Professional.

### Safety

- `publish_to_tableau_public` requires `confirm_publish: true`, defaults
  `overwrite: false`, supports `dry_run`.
- A hard precondition refuses to publish unless the intended workbook is the
  frontmost document - this caught a real near-miss against the user's own
  workbook, which was verified unchanged afterwards.
- No credentials are ever read, typed, or stored.
- XML injection, ZIP slip, path traversal and machine-identifier leakage are
  tested.

### Verification

| Gate | Result |
|---|---|
| ruff check / format | clean |
| pytest | 39 passed |
| MCP initialize / tools/list / call | pass (10 tools) |
| Opens in Tableau Public | pass, no repair dialog |
| Screenshot proves marks | pass (12 marks) |
| Published URL | **HTTP 200**, renders live |
| Existing MCPs preserved | pass (6 connected) |

### Honest gaps

`line`, `heatmap`, `scatter`, `circle` compile and pass structural validation but
were not individually screenshot-verified - recorded as *partially supported*
rather than claimed. No dashboards. `.twbx` is not byte-reproducible (Hyper writes
non-deterministic state); the `.twb` is.

---

## Stop treating destroyed windows as minimized ones

*Merged 2026-07-27.*

### What broke

The live tier's first real teardown closed nine workbooks and reported **eight of them as failures**:

```
COULD NOT CLOSE LiveTest_..._bar: ... is minimized off-screen (bounds 218x161 at -234,367)
                                  and offers no on-screen tile to click.
COULD NOT CLOSE LiveTest_..._heatmap: Command-W was sent but ... is still open.
```

Both messages were false. The workbooks had closed.

### Root cause

One wrong belief, written into `window_control`'s module docstring as fact: *a window present in `kCGWindowListOptionAll` but absent from `OnScreenOnly` is minimized.* It is **destroyed**.

Every workbook Tableau has ever opened leaves a husk at exactly `218x161` at `(-234, 367)`. A minimized document keeps a **Dock tile**, and that tile *is* on-screen - so the on-screen list finds minimized windows perfectly well and nothing is lost by ignoring the `All` list.

Trusting `All` broke closing twice over:

1. **Target selection** takes the largest match. A husk (35,098 px²) outranks a live Dock tile (~23,000 px²), so closes were aimed at windows that no longer existed.
2. **Close verification** asked whether any window with that title remained. The husk always does, so no close could ever be reported as successful.

### Evidence

- With one workbook open, the same title appeared **twice**: live at `1291x949`, and as a husk.
- A screenshot showed a **single** real Tableau window while Quartz reported **26 documents** - every "open" workbook was in Tableau's *recent files* list.
- Against the live app, `document_windows()` went from 26 entries to 5, matching the screenshot exactly.

### Changes

- `WindowInfo.is_stale`; `document_windows()` hides husks unless `include_stale=True` (diagnostics only)
- `close_document` polls for the window to disappear instead of sampling once after a fixed 1.5s, which false-failed whenever Tableau was slow
- `close_document` reports "already closed" for a husk-only workbook rather than trying, and never re-opens it
- `close_all_generated` accepts `known_paths` so a minimized workbook is raised via `open -a` rather than a Dock-tile click, and reports `already_closed`
- Live teardown supplies the paths it built, and reports against what is **still open** rather than what it attempted

The test fixtures encoded the same wrong belief - `doc(offscreen=True)` built the exact husk signature while every test read it as "minimized". Renamed to `stale=True`, with separate Dock-tile fixtures for genuinely minimized windows.

### Verification

| | |
|---|---|
| Live tier | 13 passed; all 9 generated workbooks closed; **zero failures** |
| Unit tier | 226 passed (+8) |
| ruff | clean |

Teardown now accounts for every workbook it created:

```
[live] cleaning up 9 generated workbook(s) with prefix 'LiveTest'
[live]   closed LiveTest_024435_circle / _text_table / _heatmap / _scatter
[live]   already closed before teardown: 5 (_bar, _dashboard, _dashfixed, _line, _publish)
[live] all 9 generated workbook(s) are closed
```

Full write-up in limitation 10 of `docs/LIMITATIONS.md`.

---

## Maps, full audit remediation, and public-repo prep

*Merged 2026-07-27.*

Five commits: the `map` template, remediation of every finding from a six-agent audit, and preparation for making the repo public.

**481 tests** (466 unit + 15 live) · ruff clean · live teardown closes all 12 workbooks with zero failures.

### 1. `map` template

Plots latitude/longitude symbol marks on Tableau's background map. **Verified live** - basemap with state boundaries, 12 marks, one per site, each in its correct state.

Three things separate a map from a scatter plot, and each fails **silently** - no error dialog, just a wrong-looking sheet - so all three are pinned by tests:

| Missing | Result |
|---|---|
| `<mapsources>` | marks on blank white, no coastline |
| `semantic-role="[Geographical].[Latitude]"` | an ordinary scatter plot |
| `aggregation="Avg"` | one mark, at the average of all coordinates |

`geographic_role()` already existed as **dead code**, and was wrong - latitude and longitude both mapped to `[Country].[Name]` - while the capability report advertised "geographic roles are inferred". Now true.

### 2. Audit remediation

Every finding independently verified before action; each fix has a regression test that fails without it. **All of them passed the 263-test suite that existed at the time.**

#### Could publish or destroy the wrong thing
- **`assert_target_frontmost` matched by substring** - publishing `Q3_Sales` while `Q3_Sales_Draft` was frontmost would push the draft to the public internet under the intended name, and report success.
- **Overwrite protection was fail-open two ways** - gated on an optional argument, and wrapped in `except ImportError: pass`.
- **The ZIP-slip guard ran after the destructive writes** - it overwrote and deleted files, *then* raised.
- **`Cmd+W` and `Cmd+Shift+S` never checked Tableau was the active application** - every guard ranked only Tableau's own windows, so all passed while the user was in a browser.
- **`_await_published_url` matched on title alone** - every overwrite publish reported verified success whether or not the upload worked.
- **A failed title still clicked Save** - publishing under a filename-derived name the collision check never examined.

#### Silent corruption
- **Tableau identifiers had no escaping** - a column named `Val]ue` corrupted its own references; a crafted header could redirect one column's shelf reference to another field.
- **A blank CSV line became a row of NULLs** in the extract and every viz.
- **`find_window` matched substrings** - validation could go green against a different workbook, screenshot included.
- **`read_error_dialog` returned the clipboard** with no evidence it came from Tableau.

#### Dead code presented as working
- `fit` was validated, never passed to `Worksheet`, *and* rejected as an unknown key - unusable three ways at once.
- `output.package_twbx` parsed and ignored.
- `data_dir_ref` accepted and discarded, so a standalone `.twb` **could not resolve its data**. Now it can.
- `empty_worksheet` validation could never fire.
- The JSON Schema was never loaded and had already drifted stricter than the server. It is now **generated** from the spec model, pinned by a drift test, and published as the MCP input schema.

#### Tests that could not fail
Two determinism tests built twice to the **same path** and compared the file to itself - they would have passed with random zone ids. Twelve window tests asserted a disproven model. Three capabilities marked "verified" had zero coverage.

#### Hardening
Real path containment (opt-in via `TABLEAU_MCP_ALLOWED_ROOTS`, since a hardcoded allowlist would break the tool's actual job), case-folded blocklist, Windows-traversal rejection, bounded untrusted-archive inspection, XML entity-expansion defence (a 282-byte file expanding to 100,000 chars is now rejected), streamed extract rows with the row cap actually enforced, and blocking calls moved off the MCP event loop.

### 3. The last bug was mine

Adding `known_paths` so teardown could raise a minimized workbook with `open -a` made the raise succeed and the **close** unreliable: `open -a` rearranges windows without making the document active, so the window server reports the target as frontmost while Tableau's active-document state points elsewhere, and `Cmd+W` closes a different workbook.

Reproduced rather than inferred - closing `CloseTestA` via `open -a` failed twice over 21s while consuming two blank `Book` windows. The Dock-tile click succeeded first time. Click is now preferred; `open -a` is the fallback.

I also shipped a `TypeError` in `inspect_local_workbook` (a `suffixes=` argument that didn't exist, so the tool crashed on every call). Caught by an agent, fixed, now covered end to end.

### 4. Public-repo prep

Removed three session artifacts that were pure machine records (private repo URL, published viz URL, home paths). Scrubbed profile name, display name, personal workbook name and home paths from docs, source, tests and fixtures; renamed `EV_WORKBOOK_*` fixtures to `REFERENCE_WORKBOOK_*`; dropped the account URL from the generated schema's `$id`. `.gitignore` now covers `hyperd*.log` (an 82 MB one was untracked).

**README now opens with three screenshots** of workbooks this server generated - dashboard, symbol map, bar chart - from synthetic fixture data. No personal workbooks appear anywhere.

> ⚠️ **Not addressed by this PR:** git history and the diffs of PRs #1–#3 are stored by GitHub and survive any history rewrite. Making this repo public exposes them. A fresh repository seeded from this tree is the only option that closes both.

---
