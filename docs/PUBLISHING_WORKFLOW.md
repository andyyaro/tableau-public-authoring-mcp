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
5. Invoke `Save to Tableau Public As...` — see below
6. Sign-in window if not authenticated -> **stop, hand off to the user**
7. "Save Workbook to Tableau Public" dialog -> **type** the title -> click **Save**
8. Poll the profile until the workbook appears, then load its public URL and
   expect HTTP 200 (`verify_published_workbook` does the same check on demand)

## Invoking the command: shortcut first, menu second

The primary path is a **real Command+Shift+S HID key event**
(`publisher.invoke_save_to_public` -> `tableau_app.real_key(VK_ANSI_S,
command=True, shift=True)`). Command+Shift+S maps to `Save to Tableau Public
As...` in Tableau Public 2026.2.0. Success is confirmed by waiting for the "Save
Workbook to Tableau Public" window, not by assuming the keystroke landed.

Only if that fails does the tool fall back to opening the **File** menu and
CGEvent-clicking the item, and finally to the Desktop-Professional `Server >
Tableau Public` path. The menu click used to be the primary path and was replaced
because it was unreliable in practice: a menu item's AX geometry is valid only
while the *same* `osascript` call holds the menu open, the File menu's width moves
with the recent-files list, and a correctly-computed dwell-then-click on the
highlighted item still frequently did nothing. A shortcut needs no geometry, no
open menu and no mouse tracking. See `docs/LIMITATIONS.md` §9.

## The title is typed, not accepted

Tableau pre-fills the Workbook Title from the file name. The tool does **not**
keep it: `set_title` defaults to `true`, so `set_dialog_title` sends
Command+A and types `public_name` over the pre-filled value. Pass
`set_title: false` to keep Tableau's own text instead. Keystrokes do reach Qt —
System Events synthesises them as session-level events — which is why typing
works where an Accessibility click on a menu item does not.

## Safety

- `confirm_publish: true` and `profile` are both required; `overwrite` defaults
  to `false`
- **Overwrite protection is enforced, not decorative**: the tool queries your
  published workbooks and refuses on a name collision. It compares both the raw
  title and Tableau's normalised repo-URL form, because a new title can collide
  with an existing workbook's URL even when the titles look different. It fails
  **closed** — a failed lookup returns "UNABLE TO VERIFY", never "safe". `profile`
  is required rather than optional precisely because this check was once gated on
  `if profile:`, so omitting one argument skipped it entirely.
- `dry_run: true` reports what would happen without acting. Two fields in its
  `would_publish` payload are stale and should not be believed: `menu_path` still
  prints the Desktop-Professional `Server > Tableau Public > ...` string rather
  than the Command+Shift+S path actually taken, and `is_validation_test` is
  emitted despite no longer being a tool argument and never having been wired to
  anything (see `docs/MCP_TOOLS.md`)
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
The user's `the reference workbook` was confirmed unchanged
(`revision 1.2`, identical `lastPublishDate`).
