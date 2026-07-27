# Live tier

Tests that drive the **real Tableau Public desktop app**. They are the automated
form of the manual check that found every important defect in this project: six
that stopped a workbook loading, and two where it loaded perfectly and rendered
nothing at all. Unit tests cannot see either class of failure — the `.twb` is
well-formed, deterministic and structurally valid in both cases.

## Running it

```bash
uv run pytest -m live                 # everything except the publish-flow tests
uv run pytest -m "live and not publish"
uv run pytest -m publish -v           # the publish-flow tests (still never publish)
uv run pytest -m live -k dashboard    # one file
```

`TABLEAU_LIVE_TESTS=1 uv run pytest tests/live` works too, for when you want to
name the directory instead of the marker.

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

Permission is granted to whatever binary is actually running pytest — your
terminal, or your IDE. See `docs/MACOS_PERMISSIONS.md`.

**It never fails merely because the environment is wrong.** A Linux box, a
machine without Tableau, or a machine without the permissions all *skip*.

## It must never run in CI

A default `pytest` run **deselects** the whole tier (`tests/live/conftest.py`
does this in `pytest_collection_modifyitems`, because `pyproject.toml` sets no
`addopts` marker filter). Selecting it takes a deliberate `-m live` or
`TABLEAU_LIVE_TESTS=1`.

CI cannot run this anyway: publishing and rendering both need a visible app, a
window server, a signed-in session and two macOS privacy permissions. There is no
headless mode and no publishing API.

## It is slow, and it takes over your screen

Expect **several minutes**. Each case compiles a workbook, materialises a Hyper
extract, launches or re-uses Tableau, waits for a window, and screenshots it
until the canvas has ink. Tableau windows will appear and take focus while it
runs. Do not use the machine at the same time — a stray click changes which
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
are never candidates — **so do not name a real workbook `LiveTest...`**.

This cleanup is not tidiness. A session that left roughly eighteen workbooks open
wedged Tableau to the point where it stopped accepting new documents, which looks
exactly like a compiler bug until you count the windows. The tier also refuses to
open more than `MAX_LIVE_WORKBOOKS` (12) in one run rather than wedge the app
halfway through.

If teardown reports `COULD NOT CLOSE`, close those windows in Tableau by hand
before the next run. The most likely reason is Tableau asking whether to save —
this project never answers that prompt, because "Don't Save" destroys work.

## How "not blank" is decided

`canvas.py`. The window screenshot is decoded to RGBA with CoreGraphics (no
Pillow and no numpy are installed, and neither was added — `pyobjc` is already a
hard requirement for enumerating Tableau's windows). A rectangle of the *canvas*
is cropped, excluding the Data pane, the Marks card, the toolbar, the worksheet
title and the sheet tabs, because all of those draw whether or not the viz did.

Each sampled pixel is background (bright and colourless: white canvas or a pale
gridline) or ink. Coloured ink is counted separately, which is what separates
"the marks drew" from "only the black axis labels drew".

* `MIN_INK_RATIO = 0.0005` — a blank canvas measures **0.00000**; there is no
  noise floor to clear. Real vizzes measure an order of magnitude above this.
* `MIN_CHROMA_RATIO = 0.0002` — required for every template except `text_table`,
  whose marks are black text.

Neither number is a guess. `_calibration.py` draws synthetic Tableau-shaped
captures and reports what the analyser measures on them — **no Tableau and no GUI
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
