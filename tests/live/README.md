# Live tier

Tests that drive the **real Tableau Public desktop app**. They are the automated
form of the manual check that found every important defect in this project: six
that stopped a workbook loading, and two where it loaded perfectly and rendered
nothing at all. Unit tests cannot see either class of failure - the `.twb` is
well-formed, deterministic and structurally valid in both cases.

## What is in here

| File | What it opens |
|---|---|
| `test_render_templates.py` | one workbook per entry in `SUPPORTED_TEMPLATES` |
| `test_encodings_and_sources.py` | a size-encoded worksheet, and a two-data-source workbook whose first sheet is bound to the *second* source |
| `test_dashboard.py` | an automatic and a fixed-size dashboard |
| `test_publish_flow.py` | one workbook, taken to the publish dialog and no further |

Everything that only *reads* something from this directory rather than opening a
window belongs in `tests/unit/test_coverage_gaps.py`, which runs by default. The
drift check over `TEMPLATE_CASES` lives there for exactly that reason: while it
sat in `test_render_templates.py` under this package's `live` marker, the one
test whose job is noticing a new template arriving without a live case only ran
on the runs that were already driving Tableau.

## Running it

```bash
uv run pytest -m live                    # the whole tier, publish-flow tests included
uv run pytest -m "live and not publish"  # render checks only
uv run pytest -m publish -v              # the publish-flow tests (still never publish)
uv run pytest -m live -k dashboard       # one file
TABLEAU_LIVE_TESTS=1 uv run pytest tests/live   # name the directory, not the marker
```

Every line above is checked: `-m live` selects 15 tests, `-m "live and not
publish"` selects 11, `-m publish` selects 4. The publish-flow tests carry
**both** markers, so `-m live` includes them - an earlier version of this file
claimed the opposite.

The environment-variable route needs the conftest's help, because
`pyproject.toml` sets `addopts = "-m 'not live'"` and that filter would deselect
the very tests you just asked for. `TABLEAU_LIVE_TESTS=1` drops it; see
`resolve_selection` in `conftest.py`. An explicit `-m` of your own always wins
over the variable.

Add `-s` if you want the `[live]` progress lines as they happen rather than at
the end.

## What it requires

| Requirement | If missing |
|---|---|
| macOS | tier skips |
| Tableau Public installed in `/Applications` | tier skips |
| `pyobjc` (Quartz) | tier skips |
| Accessibility permission for the process running pytest | tier skips |
| Screen Recording permission for the same process | tier skips |
| A signed-in Tableau Public session | only the publish tests skip |

Permission is granted to whatever binary is actually running pytest - your
terminal, or your IDE. See `docs/MACOS_PERMISSIONS.md`.

**It never fails merely because the environment is wrong.** A Linux box, a
machine without Tableau, or a machine without the permissions all *skip*.

## It must never run in CI

A default `pytest` run **deselects** the whole tier. Two mechanisms do that, and
they cover different failures:

1. **`pyproject.toml` sets `addopts = "-m 'not live'"`.** pytest's own marker
   filter deselects everything carrying the `live` marker, wherever it lives.
   This is what does the work on a normal day.
2. **`pytest_collection_modifyitems` in `conftest.py`.** It covers what a marker
   filter structurally cannot: a test added to this directory that nobody
   marked. Such a test used to run in a bare `pytest` and launch Tableau. It is
   marked during collection now - before pytest's filter runs - and reported, so
   the omission is visible rather than silently patched. If there is no marker
   filter in force at all (`addopts` removed, or `-m ""`), the same hook
   deselects the tier itself instead.

Neither is decoration. The hook was inert for a long time: it asked
`if "live" in markexpr`, and `addopts` makes that string `"not live"`, which
contains `live` - so it decided the tier had been requested and returned without
acting on *every single run*.

Selecting the tier takes a deliberate `-m live` or `TABLEAU_LIVE_TESTS=1`.
`tests/unit/test_coverage_gaps.py` pins both mechanisms and audits this
directory for unmarked modules, in the tier that actually runs by default.

CI cannot run this anyway: publishing and rendering both need a visible app, a
window server, a signed-in session and two macOS privacy permissions. There is no
headless mode and no publishing API.

## It is slow, and it takes over your screen

Expect **several minutes**. Each case compiles a workbook, materialises a Hyper
extract, launches or re-uses Tableau, waits for a window, and screenshots it
until the canvas has ink. Tableau windows will appear and take focus while it
runs. Do not use the machine at the same time - a stray click changes which
document is frontmost, which is exactly what the publish guard is designed to
notice.

## Nothing here publishes

`test_publish_flow.py` stops at the "Save Workbook to Tableau Public" dialog,
asserts it appeared and settled, and dismisses it with Escape (clicking Cancel
was measured to leave the dialog on screen). The Save button is never located and
never clicked, and `publisher.publish`, `publisher.click_dialog_button` and
`publisher.set_dialog_title` are replaced with tripwires that raise if anything
in the module reaches for them. Those tests carry both the `live` and `publish`
markers so either filter excludes them.

## Cleanup, and the one naming rule

Every workbook this tier creates is named `LiveTest_<runid>_<slug>`. Teardown
calls `window_control.close_all_generated(["LiveTest"])`, which only ever matches
document windows whose title stem *starts with* that prefix. Your own workbooks
are never candidates - **so do not name a real workbook `LiveTest...`**.

Teardown passes `known_paths`, the stem-to-file map it built while running, so a
minimised workbook can be raised with `open -a` instead of by clicking its Dock
tile. Supplying the path is the more reliable of the two routes.

The final line reports against what is **still open**, not against what teardown
attempted, and it accounts for every workbook the run created: some are closed by
teardown and the rest were already closed by the time it ran. An earlier version
counted destroyed windows as open and announced eight failures for nine
successful closes - see limitation 10 in `docs/LIMITATIONS.md`.

This cleanup is not tidiness. A session that left roughly eighteen workbooks open
wedged Tableau to the point where it stopped accepting new documents, which looks
exactly like a compiler bug until you count the windows. The tier also refuses to
open more than `MAX_LIVE_WORKBOOKS` (14) in one run rather than wedge the app
halfway through. A full `-m live` run currently opens twelve, so that ceiling has
to stay above twelve and comfortably below the eighteen that wedged Tableau;
raising it further is not the fix if a run starts hitting it.

If teardown reports workbooks still open, close them in Tableau by hand before the
next run. The most likely reason is Tableau asking whether to save - this project
never answers that prompt, because "Don't Save" destroys work.

Tableau opens a fresh blank `Book<N>` whenever it closes the last visible document,
so a run leaves a handful of empty start-page windows behind. They are not part of
this tier's cleanup contract, which touches only what it created.

## How "not blank" is decided

`canvas.py`. The window screenshot is decoded to RGBA with CoreGraphics (no
Pillow and no numpy are installed, and neither was added - `pyobjc` is already a
hard requirement for enumerating Tableau's windows). A rectangle of the *canvas*
is cropped, excluding the Data pane, the Marks card, the toolbar, the worksheet
title and the sheet tabs, because all of those draw whether or not the viz did.

Each sampled pixel is background (bright and colourless: white canvas or a pale
gridline) or ink. Coloured ink is counted separately, which is what separates
"the marks drew" from "only the black axis labels drew".

* `MIN_INK_RATIO = 0.0005` - a blank canvas measures **0.00000**; there is no
  noise floor to clear. Real vizzes measure an order of magnitude above this.
* `MIN_CHROMA_RATIO = 0.0002` - required for every template except `text_table`,
  whose marks are black text.

Neither number is a guess. `_calibration.py` draws synthetic Tableau-shaped
captures and reports what the analyser measures on them - **no Tableau and no GUI
involved**, so you can re-run it anywhere before changing a threshold:

```bash
.venv/bin/python -m tests.live._calibration
```

| case | ink_ratio | chroma |
|---|---|---|
| blank canvas | 0.00000 | 0.00000 |
| axis text only, no marks | 0.00683 | 0.00000 |
| 6 marks, radius 10px @2x | 0.00783 | 0.00100 |
| 6 marks, radius 26px @2x | 0.01356 | 0.00672 |

The second row is why the colour check exists: a canvas that drew its axes and
headers but no marks is comfortably "not blank" by ink alone.

Both failure messages print the measured numbers and the path to the screenshot,
so a borderline result can be judged by a human instead of by an `assert False`.
