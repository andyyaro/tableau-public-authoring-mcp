# Limitations

Honest inventory. Nothing here is speculative — each item was hit during development.

## 1. `.twbx` packaging is not byte-reproducible

The generated `.twb` **is** byte-identical for an identical spec (deterministic IDs
from SHA-256 of stable inputs). The `.twbx` is **not**: the embedded `.hyper`
extract is written by Tableau's Hyper engine, which emits non-deterministic
internal state. ZIP entries already use fixed timestamps and ordering.

Covered by `test_twb_generation_is_byte_deterministic` and
`test_twbx_hash_is_not_guaranteed_stable`.

## 2. The `.twb` format is not a published schema

Structures were derived from a real workbook produced by build 2026.2.0. Tableau
does not publish a formal schema, so a future release could invalidate templates.
Five concrete constraints were discovered only by loading files into Tableau:

| Constraint | Symptom if violated |
|---|---|
| `<layout>` requires `dim-percentage`, `measure-percentage` | `missing required attribute` |
| `<object-graph>` must be omitted | `no declaration found for element` |
| `<filter>`/`<slices>` live in `<view>`, not `<table>` | `element not allowed for content model` |
| `<style>` is required between `<view>` and `<panes>` | `element 'panes' is not allowed` |
| `<extract>` accepts only `count`/`enabled`/`units` | `attribute 'object-id' is not declared` |

Tableau writes `object-graph` and `extract/@object-id` in its **own** files but
rejects them on load. The writer is more permissive than the loader.

## 3. Tableau exposes almost nothing to Accessibility

- `count of windows` returns **0** even with document windows open, so AX cannot
  enumerate or raise windows. Window discovery uses `CGWindowListCopyWindowInfo`.
- The **Window menu lists worksheets, not documents**, so it cannot identify the
  active workbook.
- Menu `click` and `AXPress` report success and **do nothing** (Qt). Only real
  `CGEvent` HID clicks activate menu items. This cost several failed approaches
  and is now encoded in `desktop/tableau_app.real_click`.
- `AXSelected` is not exposed on menu items, so keyboard menu navigation cannot be
  verified before committing — it is therefore not used.

## 4. Window targeting is fragile

Opening many workbooks leaves minimised windows that `open -a` will not reliably
raise. The publisher mitigates the *danger* with a hard precondition
(`assert_target_frontmost`) that refuses to invoke publish unless the intended
workbook is the frontmost document — but it cannot always *make* it frontmost.
Practical guidance: keep one workbook open when publishing.

## 5. Publishing cannot be automated end-to-end without a UI

No API exists. Publishing requires a visible app, a signed-in session, and
Accessibility + Screen Recording permissions. It cannot run headless or in CI.

## 6. All seven worksheet patterns are now screenshot-verified

`bar`, `text_table`, `line`, `heatmap`, `scatter` and `circle` were each opened in
Tableau Public 2026.2.0 and confirmed to render marks.

A real gap surfaced while verifying, and has since been **resolved**. Worksheets
now accept a `detail` array compiled to `<lod column='[federated.x].[none:Field:nk]'/>`
inside `<encodings>`, so a scatter with `Status` on Color and `Site Name` on Detail
draws one mark per site (12) instead of one per Status value (3) — confirmed in
Tableau. The compiler deliberately keeps the `none:` derivation there rather than
the `attr:` promotion tooltips receive, because raising the level of detail is
exactly what Detail is for. That asymmetry is visible in Tableau's own files: the
reference workbook's heat-map sheet uses `attr:` on its tooltip dimension and
`none:` on its lod dimension in the same `<encodings>` block.

## 7. The Save-button click uses calibrated coordinates

The publish dialog's Save button is clicked at a fraction of the dialog's *live*
bounds (not a hardcoded screen position), because AX does not expose the button.
This is the documented brittle fallback permitted for last resort. If Tableau
changes that dialog's layout, this breaks and must be re-measured.


## 8. Dashboards: verified, but only the basic shape

**Resolved.** A generated dashboard was opened in Tableau Public 2026.2.0 and
renders: title, two tiled worksheets, and a fixed 1200x800 canvas
(`output/screenshots/dashboard-gate.png`). This retired every risk the fixture
analysis flagged as unproven:

| Former risk | Outcome |
|---|---|
| `type-v2` required at doc version 18.1 | **No.** Plain `type` loads. The attribute appears in zero fixtures and is not needed. |
| Container nesting wrong (`layout-flow` inside `layout-basic`) | **Correct as generated.** |
| Zone worksheet reference silently unresolved | Both zones bound to real sheets and drew data. |
| Title needing two cooperating pieces | Confirmed - the `type="title"` zone plus `layout-options/title` renders. |
| Zone tiling / rounding | Title 6000 + two 47000 spans tiled the canvas cleanly. |

What is still NOT generated, because one example of each is not enough to
generalise: filter cards, colour legends, highlighters, parameter controls,
images, floating zones, device layouts, and dashboard actions. Only worksheet
zones inside a single horizontal or vertical container are produced.

Dashboard geometry remains the most fragile part of the compiler: zone `x/y/w/h`
are a 0..100000 normalised grid (NOT pixels, unlike `<size>`), and siblings must
tile their parent exactly. A tiling bug clips or overlaps silently rather than
failing to load, which is why the layer-2 `zone_tiling` and
`unresolved_zone_worksheet` checks are not optional.

## 9. Menu automation is unreliable; the shortcut is not

Invoking `Save to Tableau Public As...` by clicking the menu item proved
unworkable, even with correct coordinates:

* a menu item's AX geometry is only valid while the **same** `osascript` call holds
  the menu open — query it from a separate call and you get `(0, 0)`;
* the File menu's width varies with the recent-files list, so the click point moves;
* even a correctly-computed dwell-then-click on the highlighted item frequently did
  nothing.

The publisher now sends **Command+Shift+S** as a real HID key event, which needs no
geometry, no open menu and no mouse tracking. The menu path is retained only as a
fallback. If Tableau changes that shortcut, the fallback is exercised again.

## 10. The window server keeps destroyed windows

`kCGWindowListOptionAll` returns entries for windows that no longer exist. This
caused **four** distinct bugs, and it is the single most expensive misunderstanding
in this project.

The first two were in the publisher: a permanent false "sign-in required" (matching
a 59x112 husk of a closed sign-in window), and Save clicks aimed at a dialog that
had already been replaced.

The other two were in workbook cleanup, and came from a wrong belief written into
`window_control` as documentation: that a window present in `All` but absent from
`OnScreenOnly` is *minimised*. It is not — it is **destroyed**. Every workbook
Tableau has ever opened leaves a husk at exactly `218x161` at `(-234, 367)`. A
minimised document keeps a Dock tile, and that tile **is** on-screen, so the
on-screen list alone finds minimised windows perfectly well.

Because the code trusted the `All` list, cleanup:

1. aimed at husks instead of live windows — target selection picks the largest
   match, and a husk (35,098 px²) outranks a Dock tile (~23,000 px²), producing the
   error "is minimized off-screen ... and offers no on-screen tile to click" about
   workbooks that were open and perfectly reachable; and
2. never believed a close had worked, because it checked whether a window with that
   title still existed and the husk always does. **Every successful close was
   reported as a failure.** A live run closed nine workbooks and reported eight of
   them as errors.

Proof: with one workbook open, the same title appeared twice — live at `1291x949`
and as a husk — and a screenshot showed a single real Tableau window while Quartz
reported twenty-six documents. Every workbook named in those errors was sitting in
Tableau's *recent files* list.

**Rule: `OnScreenOnly` is the list of windows that exist.** `document_windows()`
hides stale entries by default; pass `include_stale=True` for diagnostics only. The
one cost is that a hidden Tableau (Command-H) looks like it has no documents, which
is a safe failure because every caller refuses to act on a window it cannot find.
