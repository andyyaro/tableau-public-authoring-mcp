# MCP Tools

10 tools. All return JSON with an `ok` boolean; errors never crash the server.

## Read-only

| Tool | Purpose |
|---|---|
| `get_authoring_capabilities` | supported/unsupported matrix + app + permission state (**derived from the code**, see below) |
| `list_workbook_templates` | templates, mark classes, shelf requirements |
| `validate_workbook_spec` | dry-run validation, writes nothing |
| `inspect_local_workbook` | ZIP-slip-guarded `.twbx` inspection |
| `get_tableau_public_app_status` | install, version, running, windows, Accessibility |
| `verify_published_workbook` | load a public URL, expect 2xx/3xx |

## Authoring

| Tool | Purpose |
|---|---|
| **`build_workbook`** | **primary** — spec -> `.twb` + `.twbx` + Hyper extracts |
| `open_in_tableau_public` | open and wait; returns Tableau's load error verbatim |
| `validate_in_tableau_public` | layers 3+4: open, detect dialogs, screenshot |

## Publishing (destructive)

| Tool | Purpose |
|---|---|
| `publish_to_tableau_public` | visible `File > Save to Tableau Public As...` flow |

Required: `workbook_window`, `public_name`, `confirm_publish: true`.
Optional: `profile`, `overwrite` (default `false`), `set_title` (default `true`),
`is_validation_test`, `dry_run`, `screenshot_dir`.

Runs the flow to completion: invoke the menu, hand off if a sign-in window appears,
type the workbook title, click Save, wait for the upload to be submitted, resolve
the public URL from your profile, and verify it responds.

**Pass `profile`** (your Tableau Public profile name) to get two things:
1. **Overwrite protection** — the tool queries your published workbooks first and
   refuses to clobber an existing one unless `overwrite: true`. It fails *closed*:
   if the lookup fails it refuses rather than assuming the name is free.
2. **URL resolution and verification** — without it, publication is submitted but
   the tool cannot confirm or return the resulting URL.

Refuses to act unless the intended workbook is the frontmost document. Never reads,
types or stores credentials; stops and hands off if a sign-in window appears.

## Capability reporting is derived, not hand-written

`get_authoring_capabilities` and `list_workbook_templates` compute their answers
from the spec model and compiler at call time (`capabilities.py`) rather than from
a maintained list.

This is a correctness measure, not tidiness. The report previously claimed
`"dashboards": "not implemented in v0.1"` long after dashboards were implemented
and verified rendering. Stale docs are cosmetic; a stale *tool surface* changes
behaviour, because a model decides what to attempt from this payload — a false
"unsupported" silently removes a working feature.

Adding an encoding to the `Worksheet` model now surfaces here automatically, and
`tests/unit/test_capability_drift.py` fails if the report and the code ever
diverge again.

## Typical sequence

```
validate_workbook_spec   (dry run)
build_workbook           (writes .twbx)
validate_in_tableau_public
publish_to_tableau_public  { dry_run: true }   -> review
publish_to_tableau_public  { confirm_publish: true }
verify_published_workbook
```
