# Architecture Decision Record - Tableau Public Authoring MCP

**Status:** Accepted
**Date:** 2026-07-26
**Decision owner:** Claude Code autonomous run (MASTERPROMPT_AUTHORING.md §6)
**Supersedes:** none

---

## Context

The goal is an MCP server that can generate Tableau workbooks from a declarative
spec, validate them in the installed Tableau Public 2026.2.0, and publish one to
the user's Tableau Public account.

Three findings from `docs/research/CURRENT_STATE_RESEARCH.md` constrain the design
before any preference is applied:

1. **There is no supported programmatic publishing API for Tableau Public.** The
   REST API covers Server/Cloud only. The sole documented path is
   `Server > Tableau Public > Save to Tableau Public` in the desktop app.
2. **No official library can create a workbook from scratch.** The Tableau
   Document API states verbatim that it does not support "creating files from
   scratch," and describes itself as unsupported.
3. **Tableau Public 2026.2.0 ships no AppleScript dictionary** (no `.sdef`, no
   `NSAppleScriptEnabled`, no URL scheme - verified on this machine).

A fourth finding sets the success bar: Tableau's own documentation states *"Your
viz must contain at least one field before the save option becomes available."*
Emitting well-formed XML is therefore **not** sufficient; the workbook must carry
real encodings and render marks, or it cannot be published at all.

---

## Decision

**Adopt Strategy D - hybrid compiler plus desktop validation and visible-UI
publishing**, implemented in **Python**.

Concretely:

- A **compiler** deterministically generates `.twb` XML from a validated spec,
  using node structures derived from a real workbook produced by the installed
  Tableau build, via structured `ElementTree` generation (never string splicing).
- A **packager** produces `.twbx` archives with ZIP-slip protection and no
  machine-specific paths.
- A **desktop layer** opens generated workbooks in Tableau Public via macOS
  Accessibility automation, detects failure dialogs, and captures screenshots.
- A **publishing layer** drives the documented, visible
  `Server > Tableau Public > Save to Tableau Public` workflow using the user's
  existing signed-in session, and never touches credentials.
- A **verification layer** loads the resulting public URL to confirm success.

---

## Options considered

Scored with a weighted matrix (`DECISION_MATRIX.csv`, 12 criteria, weights 2–5,
max 240):

| Strategy | Score | % |
|---|---:|---:|
| **D - hybrid compiler + desktop validation** | **212** | **88.3%** |
| C - template transformation only | 157 | 65.4% |
| B - direct `.twb` generation only | 119 | 49.6% |
| A - pure desktop UI automation | 105 | 43.8% |

### Why A (pure UI automation) fails

Scored 1/5 on authoring reliability. Building a viz through the UI requires
dragging fields onto Rows/Columns/Marks shelves. Those shelves are not exposed as
named, addressable Accessibility elements with stable identifiers; automating them
means synthetic drag gestures at coordinates, which §4 forbids as a primary
mechanism and which break on any layout or version change. It is also the slowest
option and effectively untestable in CI.

It scores well (4/5) on publishing only - which is precisely the sub-problem
Strategy D borrows from it.

### Why B (direct XML generation from scratch) fails

Scored 0/5 on publishing feasibility: generating a file does not publish it, and
no API exists to close that gap. It also scored 2/5 on compatibility because
Tableau does not publish a formal `.twb` schema, so freely-synthesised XML has no
authority to validate against and would likely trigger repair dialogs.

### Why C (template transformation) is insufficient alone

Strong on generation (4/5) and testability (5/5), but likewise **0/5 on
publishing**, and 2/5 on validation because it never confirms Tableau actually
accepts the output. C is a necessary component, not a sufficient architecture.

### Why D wins

D is C's generation strength plus A's publishing capability plus a validation loop
neither has alone. It is the only option that can satisfy the acceptance criteria
in §22, which require both a rendered-marks screenshot and a verified public URL.

The masterprompt predicted this outcome. The prediction was **not** taken as
justification: the matrix was scored from measured evidence (no `.sdef`, no
publishing API, no create-from-scratch library), and B/C fail on an objective
capability gap rather than on preference.

### Strategy E - alternatives discovered during research

Two were evaluated and rejected:

- **Tableau Document API as the generator.** Rejected: officially cannot create
  files from scratch, and is self-described as unsupported.
- **Driving Tableau's internal publish endpoint directly.** Rejected on rule
  grounds (§4 forbids reverse-engineering private endpoints) and on engineering
  grounds (undocumented, unversioned, breaks silently).

---

## Language: Python

Selected against TypeScript rather than assumed (§7).

**For Python:** matches the user's existing `keynote-mcp` registration pattern
(`uv --directory … run …`, and `uv` 0.11.29 is installed); `osascript` automation
is a `subprocess` call away with PyObjC available for deeper AX work; stdlib
covers XML, ZIP, CSV and hashing so the dependency surface stays small; the Hyper
API is Python-first, keeping the extract roadmap open.

**For TypeScript:** more mature MCP SDK, npm distribution, and the *reader* MCP is
already TypeScript.

**Resolution:** this server's real work is local file generation plus macOS UI
automation, where Python is clearly stronger. The reader and authoring MCPs are
separate processes, so the language split imposes no operational cost.

---

## Consequences

**Positive**

- Generation is deterministic and unit-testable without Tableau installed.
- Validation is genuine - the file is opened by the real application.
- Publishing uses only the documented user-facing workflow; no private endpoints,
  no stored credentials.
- CI can run everything except the live/publish tiers.

**Negative / accepted risks**

- The `.twb` format is not formally published by Tableau, so the compiler depends
  on structures observed in build 2026.2.0. A future Tableau release may require
  re-deriving templates. Mitigated by recording version metadata and by a golden
  round-trip test that fails loudly on drift.
- The publish step depends on macOS Accessibility and on the user's session being
  signed in. Mitigated by preflight checks and a clean manual-login handoff.
- Desktop automation cannot run headless or in GitHub CI. Mitigated with pytest
  markers isolating `live` and `publish` tiers.

---

## Compliance with the safety rules (§4)

| Rule | How this design complies |
|---|---|
| No private publishing endpoints | Publishing drives the documented menu path only |
| No credential handling | Auth delegated to the desktop session; server never reads secrets |
| No coordinate-first automation | Elements addressed by AX role + accessible name; coordinates are a documented last-resort fallback |
| No permission bypass | Uses already-granted TCC permissions; no system database is modified |
| Preserve existing MCPs | Registered under a new distinct name; config backed up before any change |
| Don't overwrite user's EV workbook | Publish path uses a unique timestamped name; overwrite defaults to `false` |
| Don't claim unsupported capability | `CAPABILITY_BOUNDARY.md` enumerates supported vs experimental vs unsupported |
