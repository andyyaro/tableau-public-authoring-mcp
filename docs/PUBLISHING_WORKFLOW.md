# Publishing Workflow

## The path Tableau actually offers

Tableau's docs describe `Server > Tableau Public > Save to Tableau Public`. That is
the **Tableau Desktop Professional** path. In the **Tableau Public** edition
(2026.2.0) the Server menu contains only `Run Optimizer...`, and publishing lives on
the **File** menu:

- `File > Save to Tableau Public...` — publishes under the current name
- `File > Save to Tableau Public As...` — prompts for a name (**used by default**,
  because it cannot silently overwrite)

Both are disabled until the viz contains at least one field.

## Sequence

1. `build_workbook` -> `.twbx` with Hyper extracts
2. `open_in_tableau_public` -> confirm it loads
3. `validate_in_tableau_public` -> screenshot proves marks render
4. **Precondition**: `assert_target_frontmost` refuses unless the intended workbook
   is the frontmost document
5. `File > Save to Tableau Public As...` via **CGEvent** click
6. Sign-in window if not authenticated -> **stop, hand off to the user**
7. "Save Workbook to Tableau Public" dialog -> title pre-filled -> click **Save**
8. `verify_published_workbook` -> load the public URL, expect HTTP 200

## Safety

- `confirm_publish: true` is required; `overwrite` defaults to `false`
- **Overwrite protection is enforced, not decorative**: with `profile` supplied the
  tool queries your published workbooks and refuses on a name collision. It compares
  both the raw title and Tableau's normalised repo-URL form, because a new title can
  collide with an existing workbook's URL even when the titles look different. It
  fails **closed** — a failed lookup returns "UNABLE TO VERIFY", never "safe".
- `dry_run: true` reports what would happen without acting
- the frontmost-document precondition prevents publishing the wrong workbook —
  this caught a real near-miss against the user's own workbook during development
- the server never reads, types, or stores credentials

## Dismissing the dialog

Use **Escape**, not a click on Cancel. Measured behaviour: clicking Cancel leaves the
dialog on screen (it repaints blank mid-transition and lingers), whereas Escape closes
it deterministically. The **Save** button click is verified working and uses a
calibrated fraction of the dialog's live bounds.

## Verified run (2026-07-27)

Published `MCP_Authoring_Validation_-_20260727-0050`; public URL
returned HTTP 200 and the live render showed 12 bars with calculated-field colours.
The user's `Quarterly_Sales_Review` was confirmed unchanged
(`revision 1.2`, identical `lastPublishDate`).
