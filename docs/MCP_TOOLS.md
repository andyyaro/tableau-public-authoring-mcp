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
| `publish_to_tableau_public` | visible `Save to Tableau Public As...` flow, invoked with Command+Shift+S (File menu as fallback) |

Required: `workbook_window`, `public_name`, `confirm_publish: true`, `profile`.
Optional: `overwrite` (default `false`), `set_title` (default `true`),
`workbook_path`, `dry_run`, `screenshot_dir`.

**Pass `workbook_path`** (the absolute `.twbx` being published) when you have it.
It lets a minimised workbook be raised with `open -a`, which `window_control`
documents as the reliable route; without it only the coordinate-click fallback is
available.

Runs the flow to completion: send Command+Shift+S (falling back to the File menu),
hand off if a sign-in window appears, type the workbook title, click Save, wait for
the upload to be submitted, resolve the public URL from your profile, and verify it
responds.

**`profile`** (your Tableau Public profile name) is required, not optional,
because two things depend on it:
1. **Overwrite protection** — the tool queries your published workbooks first and
   refuses to clobber an existing one unless `overwrite: true`. It fails *closed*:
   if the lookup fails it refuses rather than assuming the name is free. This was
   once gated on `if profile:` while `profile` was optional, so omitting one
   argument skipped the only guard against replacing a live workbook.
2. **URL resolution and verification** — the profile is polled until the new
   workbook appears, and its URL is then loaded to confirm it responds.

Refuses to act unless the intended workbook is the frontmost document. Never reads,
types or stores credentials; stops and hands off if a sign-in window appears.

### `is_validation_test` is not a publish option

It is **not in the tool schema**, and the schema sets `additionalProperties:
false`, so a conforming client cannot send it. It never was wired to anything:
`publisher.publish()` has no such parameter and never received one, so on a real
publish it labelled nothing, changed no behaviour, and appeared nowhere in the
published workbook.

One vestige remains — the `dry_run` payload still emits
`"is_validation_test": true` inside `would_publish`. That key reflects nothing and
will read `true` whatever you do. `docs/architecture/THREAT_MODEL.md` describes a
warning keyed off this flag (T9); **that warning does not exist in the code.**

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


## Preflight

`get_tableau_public_app_status` returns a `preflight` block alongside the app
status: every environmental prerequisite, its state, and how to fix it.

It is there because all of those prerequisites fail *silently*. Without Quartz,
Tableau appears to have no windows and publishing reports "no document window
matching …". Without Screen Recording, validation screenshots are blank with no
error. A caller seeing those symptoms has no way to reach the cause otherwise.

The same report is available from a terminal, before the server is registered
with anything:

```bash
tableau-public-authoring doctor
```
