# Threat Model — Tableau Public Authoring MCP

**Date:** 2026-07-26
**Scope:** local MCP server that generates Tableau workbooks, drives the Tableau
Public desktop app via macOS Accessibility, and publishes to a public website.

## Trust boundaries

```
[ Claude / MCP client ]  --stdio-->  [ authoring MCP server ]
                                            |
                    +-----------------------+-----------------------+
                    |                       |                       |
              local filesystem      Tableau Public.app       public.tableau.com
              (CSV in, twbx out)    (AX automation)          (publish target)
```

Four boundaries matter:

1. **Model → server.** Tool arguments are attacker-influenceable in the general
   case (a model can be steered by content it reads). All input is untrusted.
2. **Server → filesystem.** The server reads CSVs and writes archives.
3. **Server → desktop app.** The server synthesises UI events into a real app.
4. **Server → public internet.** Publishing is irreversible and world-visible.

## Assets

| Asset | Why it matters |
|---|---|
| User's Tableau Public account | Publishing is public and attributable |
| User's Tableau credentials | Must never be read, stored, or logged |
| The user's existing published workbooks | Must not be overwritten |
| Local filesystem | Generation must not write outside allowed roots |
| Other running applications | Automation must not act on them |
| Existing MCP registrations | Must survive registration of this server |

## Threats and mitigations

### T1 — XML injection via spec fields
A workbook name, worksheet name, or calculated-field formula containing
`"`, `<`, `&`, or `]]>` could break out of its node and inject arbitrary XML.

**Mitigation:** all XML is built with `xml.etree.ElementTree` nodes and
attributes; escaping is performed by the serializer. No f-string or `.replace()`
ever produces markup. Enforced by `tests/unit/test_security.py::test_xml_metacharacters`.

### T2 — ZIP slip on packaging or inspection
A crafted entry name (`../../../.ssh/authorized_keys`) could escape the extraction
root; a crafted CSV path could be written to an arbitrary archive location.

**Mitigation:** every archive entry name is normalised and verified to resolve
inside the destination root before read or write; absolute paths and `..`
segments are rejected. Entries are written with explicit, sanitised arcnames.

### T3 — Path traversal on inputs/outputs
`csv_path` or `output.directory` could point outside the user's intended area, or
at a sensitive file.

**Mitigation:** paths are resolved to absolute and canonicalised; symlinks are
resolved; the CSV must exist, be a regular file, and have a `.csv` suffix; the
output directory must be creatable and writable. Traversal segments are rejected
before any I/O.

### T4 — Shell injection through automation
Worksheet or workbook names flow into AppleScript sent to `osascript`.

**Mitigation:** no `shell=True` anywhere; `subprocess` is always called with an
argument list. AppleScript source is passed on **stdin**, not interpolated into a
command line. Values crossing into AppleScript are escaped for AppleScript string
literals, and names are additionally constrained by schema pattern to a safe
character class.

### T5 — Credential exposure
The publish flow interacts with a sign-in surface.

**Mitigation:** the server never reads, requests, types, stores, or logs a
credential. It detects *whether* a sign-in window is present and hands off to the
user. No Keychain access. No credential appears in any tool output, log, or
document. If sign-in is required the run pauses at a visible checkpoint.

### T6 — Machine-identifying data leaking into a published artifact
Publishing is public; a `.twb` embedding `<home>/...` or a username would
leak it worldwide.

**Mitigation:** the compiler emits only relative `Data/` paths inside `.twbx`; a
test asserts generated XML contains no absolute path, no home directory, and no
system username. Verified pre-publish, not just pre-commit.

### T7 — Destructive or misdirected UI automation
Synthetic events could hit the wrong window — including one of the user's own
workbooks that happens to be open at the time.

**Mitigation:** automation targets the process by **bundle identifier**
(`com.tableausoftware.tableaupublic`), asserts the expected window title before
acting, never closes or saves windows it did not open, and takes no action if the
frontmost window is unrecognised. It never interacts with other applications.

### T8 — Accidental publication / overwrite
Publishing is irreversible.

**Mitigation:** `publish_to_tableau_public` is annotated destructive, defaults to
`overwrite=false`, requires an explicit `confirm_publish=true`, generates a unique
timestamped name, and refuses any name matching an existing user workbook. A
dry-run mode reports exactly what would happen without acting.

### T9 — Untrusted CSV content
A CSV could be enormous, contain a formula-injection payload (`=cmd|...`), or hold
sensitive data.

**Mitigation:** row/column caps enforced at inference time **and again when the
extract is built**; CSV values are treated strictly as data and are never
evaluated.

**Correction.** This section previously claimed the server "warns when a spec
marked `is_validation_test` uses a CSV outside the generated-fixtures directory".
No such warning has ever existed, and `is_validation_test` has since been removed
from the tool surface because it was never passed to the publish path either. A
threat model that credits a control it does not have is worse than one that omits
it, because it stops anyone from building the control.

**Residual risk, stated plainly.** A CSV is embedded verbatim into the `.twbx`,
and `publish_to_tableau_public` can then make that archive world-readable. Nothing
inspects the CSV for sensitive content — the server cannot know what is sensitive.
Choosing what to publish remains the user's decision, which is why publication
requires `confirm_publish` and a collision check rather than an automatic gate.

### T10 — Supply chain
Dependencies execute in-process.

**Mitigation:** minimal dependency set (`mcp`, `jsonschema`); everything else is
stdlib. Pinned lower bounds in `pyproject.toml`; `uv.lock` committed.

## Residual risks (accepted, documented)

- **Undocumented `.twb` schema.** Compiler output is validated by opening the file
  in Tableau, not against a formal schema. A Tableau update could invalidate
  templates. Detected by golden tests and live validation, not prevented.
- **AX fragility.** Menu labels could change between Tableau versions. Detected by
  preflight; fails loudly rather than clicking blindly.
- **Public exposure is irreversible.** Once published, content is world-readable.
  Mitigated only by the one-artifact limit, synthetic data, and clear labelling.

## Explicitly out of scope

Bypassing CAPTCHA/MFA/TCC/SIP, disabling security controls, reading Keychain,
calling private Tableau endpoints, publishing user data, and modifying other MCP
registrations. All are prohibited by MASTERPROMPT_AUTHORING.md §4 and none are
implemented.
