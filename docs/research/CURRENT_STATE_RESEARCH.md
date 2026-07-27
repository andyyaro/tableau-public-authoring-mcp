# Current State Research — Tableau Public Authoring & Publishing

**Research date:** 2026-07-26
**Researcher:** Claude Code (autonomous run, MASTERPROMPT_AUTHORING.md §5)
**Target environment:** macOS 26.5.1, arm64, Tableau Public 2026.2.0

All findings below are either (a) directly verified on this machine, or (b) sourced
from official documentation with the link and access date recorded. Blog posts and
Stack Overflow were not used as primary evidence.

---

## 1. Locally verified environment facts

These were measured directly on this Mac on 2026-07-26, not read from documentation.

| Fact | Value | How verified |
|---|---|---|
| Tableau app path | `/Applications/Tableau Public (Apple silicon).app` | `ls -d /Applications/Tableau*` |
| Bundle identifier | `com.tableausoftware.tableaupublic` | `PlistBuddy -c 'Print :CFBundleIdentifier'` |
| Version | `2026.2.0` | `PlistBuddy -c 'Print :CFBundleShortVersionString'` |
| macOS | `26.5.1` / `arm64` | `sw_vers`, `uname -m` |
| Python | 3.14.6 | `python3 --version` |
| uv | 0.11.29 | `uv --version` |
| Node | v25.8.2 | `node --version` |
| `gh` auth | logged in as `<your-github-user>`, scopes incl. `repo` | `gh auth status` |
| Bundled Hyper engine | `Contents/MacOS/hyper/hyperd` (267 MB) | `ls -la` |

### 1.1 AppleScript support — NONE (decisive finding)

Checked per §12. Result: **Tableau Public 2026.2.0 exposes no AppleScript dictionary.**

| Probe | Result |
|---|---|
| `.sdef` file anywhere in bundle | none found |
| `NSAppleScriptEnabled` in Info.plist | key does not exist |
| `OSAScriptingDefinition` in Info.plist | key does not exist |
| `CFBundleURLTypes` (URL schemes) | key does not exist |
| `NSAppleEventsUsageDescription` | key does not exist |
| `.scriptSuite` / `.scriptTerminology` | none found |

The `sdef` command itself is unavailable (requires full Xcode; only Command Line
Tools are installed), but the bundle inspection above is conclusive on its own —
an app with a scripting dictionary must ship an `.sdef` and declare it.

**Implication:** Strategy A (pure AppleScript control) is impossible. Any desktop
automation must use the macOS Accessibility (AX) API, driven either through
`System Events` via `osascript` or through PyObjC/`AXUIElement`.

### 1.2 macOS permissions — ALREADY GRANTED (no checkpoint required)

| Permission | Status | Probe |
|---|---|---|
| Apple Events / Automation | **granted** | `tell application "System Events" to return name of first process` → `loginwindow` |
| Accessibility (UI elements) | **granted** | `tell process "Finder" to return count of windows` → `3` |
| `screencapture` binary | present | `/usr/sbin/screencapture` |

No TCC prompt is required for this run. No system database was modified (§4 rule
respected).

### 1.3 Tableau Public accessibility surface — verified usable

With the app running (pid 76583), the AX tree is readable:

- Window: `Tableau Public - the reference workbook` (role `AXWindow`)
- Menu bar items: `Tableau Public, File, Data, Worksheet, Dashboard, Story,
  Analysis, Map, Format, Server, Window, Help`

The `Server` menu currently exposes only `Run Optimizer...`, and `File` shows
start-page items (`New`, `Open...`, `Open from Tableau Public...`,
`Hide Start Page`, `Manage My Profile...`, plus a recent-files list). This is
because the **Start Page is active**; macOS apps populate workbook-context menu
items only when a workbook window is frontmost. Full menu enumeration must be
repeated with a workbook open — see §5 below.

**Implication:** Named menu-item automation is viable. Coordinate clicking is not
required as the primary mechanism (§4 rule respected).

---

## 2. Is there a supported programmatic publishing API for Tableau Public?

**No.** This is the single most consequential finding.

- The Tableau REST API's publishing methods target **Tableau Server and Tableau
  Cloud**, not Tableau Public.
  Source: [Publishing Methods — Tableau Server REST API](https://help.tableau.com/current/api/rest_api/en-us/REST/rest_api_ref_publishing.htm) (accessed 2026-07-26)
  Source: [Publishing Resources — Tableau Server REST API](https://help.tableau.com/current/api/rest_api/en-us/REST/rest_api_concepts_publish.htm) (accessed 2026-07-26)

- The **only** documented way to publish to Tableau Public is the desktop UI:
  > "Server > Tableau Public > Save to Tableau Public"

  Source: [Save Workbooks to Tableau Public](https://help.tableau.com/current/pro/desktop/en-us/publish_workbooks_tableaupublic.htm) (accessed 2026-07-26)

  That page also documents three constraints that directly shape this project:
  1. **Sign-in is required.** A sign-in screen appears, followed by a save dialog
     where the workbook name is entered.
  2. **"Your viz must contain at least one field before the save option becomes
     available."** → A blank or field-less workbook is *not publishable*. The
     compiler must therefore emit real encodings, not an empty shell.
  3. Publishing creates an extract of the data connection, and published content
     is public to anyone.

**Implication:** Publishing must go through the visible desktop workflow. §4
forbids reverse-engineering the private endpoint that Desktop calls internally,
and this project does not do so.

### 2.1 Terms of service

`https://www.tableau.com/legal/terms-of-service` returned **HTTP 403** to
automated retrieval on 2026-07-26, so its text could not be quoted here.

The design is conservative regardless: this project drives only the same
documented, user-facing UI workflow a human performs, using the user's own
already-authenticated desktop session, and publishes exactly one clearly-labeled
validation artifact under explicit user authorization. No private endpoint is
called, no credential is read, and no login protection is bypassed.

---

## 3. Official Tableau developer tooling — capability assessment

| Tool | Can it create a workbook from scratch? | Can it publish to Tableau Public? | Verdict for this project |
|---|---|---|---|
| **Tableau Document API (Python)** | **No** | No | Cannot be the compiler |
| **Tableau Hyper API** | N/A (data only) | No | Optional, for `.hyper` extracts |
| **Tableau REST API** | N/A | **No** (Server/Cloud only) | Not applicable |
| **tabcmd** | No | No (Server/Cloud) | Not applicable |
| **Metadata API** | No | No | Not applicable |
| **Extensions API** | No (runs inside a viz) | No | Not applicable |

### 3.1 Document API — explicitly cannot create files

The official documentation states verbatim:

> "We don't yet support creating files from scratch, adding extracts into
> workbooks or data sources, or updating field information."

It further describes itself as an **"unsupported"** way to make updates — i.e.
Tableau does not guarantee stability across versions.

Source: [Tableau Document API](https://tableau.github.io/document-api-python/) (accessed 2026-07-26)
Source: [tableau/document-api-python README](https://github.com/tableau/document-api-python/blob/master/README.md) (accessed 2026-07-26)

**Implication:** The Document API is useful only for *modifying* an existing
workbook's connections. It cannot serve as the generation engine. This project
must generate `.twb` XML itself, using structures verified against a real
workbook produced by the installed Tableau version.

### 3.2 Hyper API — available but not required for v0.1

`tableauhyperapi` 0.0.25080 is available on PyPI (requires Python ≥3.6). The
Tableau Public app additionally bundles its own `hyperd` engine.

Source: [PyPI tableauhyperapi](https://pypi.org/project/tableauhyperapi/) (accessed 2026-07-26)

**Decision:** v0.1 packages **CSV** into `.twbx` rather than building `.hyper`
extracts. Rationale: the user's own reference workbook uses flat CSV-backed
federated connections (verified in §5), CSV keeps generated packages
inspectable and diffable, and it removes a large binary dependency from the MVP.
Hyper is recorded as a roadmap item, not a claimed capability.

---

## 4. MCP SDK

- `mcp` (Python SDK) latest: **1.28.1**, requires Python ≥3.10.
  Source: [PyPI mcp](https://pypi.org/project/mcp/) (accessed 2026-07-26)

Local Python is 3.14.6, so the SDK's floor is satisfied.

### 4.1 Language selection: Python

Evaluated per §7 rather than assumed.

**Chosen: Python.** Evidence:

1. **Registration consistency.** The user's existing `keynote-mcp` is registered as
   `uv --directory <another-mcp-server> run keynote-mcp`. `uv` 0.11.29
   is installed. A Python MCP registered the same way fits the user's existing,
   working pattern.
2. **Desktop automation.** macOS AX automation is reachable from Python via
   `subprocess`→`osascript` (already permitted, verified working) and via PyObjC
   if deeper AX access is later needed. Node has no comparable first-party path.
3. **Stdlib sufficiency.** `xml.etree.ElementTree` (structured XML generation,
   satisfying §13's "no unsafe global string replacement"), `zipfile` (`.twbx`
   packaging), `csv`, `hashlib` — all stdlib, minimising dependency surface.
4. **Hyper API is Python-first**, keeping the roadmap open.

TypeScript's advantages (mature SDK, npm distribution) are real, and the reader
MCP is TypeScript. But this server's core work is local file generation plus
macOS UI automation, where Python is the stronger fit. The two MCPs remain
independent processes, so a language split costs nothing operationally.

---

## 5. Structure of `.twb`/`.twbx` produced by the installed Tableau version

Verified against the user's own workbook, which the reader MCP downloaded and
unpacked during this session (full forensics in
`docs/fixtures/REFERENCE_WORKBOOK_ANALYSIS.md`).

Independently confirmed facts (the masterprompt's §2 leads were treated as
unverified and re-checked):

| Lead from masterprompt §2 | Verified? | Actual |
|---|---|---|
| ~12 worksheets | ✅ | 12 |
| ~13 data sources | ✅ | 13 |
| 3 calculated fields | ✅ | 3 |
| No dashboards | ✅ | 0 dashboards, 0 stories, 0 parameters |
| One flat CSV per worksheet | ✅ | 13 federated CSV connections, 0 joins, 0 custom SQL |
| Created by Tableau Public 2026.2.0 | ✅ | `build 2026.2.0 (20262.26.0603.1643)`, `platform=mac` |
| Document version 18.1 | ✅ | `version='18.1'` |

Structural composition of the 514,262-character `.twb`:

| Section | Chars | Share |
|---|---:|---:|
| 13 `<datasource>` blocks | ~402,600 | 78% |
| 12 `<worksheet>` blocks | ~94,800 | 18% |
| everything else | ~17,000 | 3% |

Top-level element order observed:
`document-format-change-manifest`, `repository-location`, `preferences`,
`datasources`, `mapsources`, `worksheets`, `windows`.

Mark types present (7 distinct): `Bar` ×2, `Square` ×3, `Line` ×2, `Shape` ×2,
`Circle` ×1, `GanttBar` ×1, `Automatic` ×1.

**Implication:** ~78% of a generated workbook is mechanical data-source
scaffolding, which is highly templatable. The design-bearing worksheet blocks are
only 5.5–10.8 KB each. This strongly favours a template-derived compiler over
either free-form XML synthesis or UI automation.

---

## 6. macOS desktop automation options

| Option | Available here | Assessment |
|---|---|---|
| AppleScript dictionary | **No** (§1.1) | Ruled out |
| AX via `osascript`/System Events | **Yes, permission granted** | Chosen — named menus/dialogs, no coordinates |
| PyObjC `AXUIElement` | Available if installed | Deeper control; adds dependency. Fallback |
| CGEvent synthetic keys | Available | Only for text entry into focused fields |
| `screencapture` | Present | Used for validation screenshots |
| Automator / Shortcuts | No app actions exposed | Ruled out |
| CLI arguments | None documented | Ruled out; `open -a` used to open files |

**Chosen:** `osascript` + System Events, addressing elements by **role and
accessible name** (menu bar item "Server" → menu item "Tableau Public" → "Save to
Tableau Public"), with `screencapture` for evidence. Fixed coordinates are
implemented only as a documented, calibrated last-resort fallback (§4).

---

## 7. Security implications considered

Detailed in `docs/architecture/THREAT_MODEL.md`. Summary of the concrete risks
this project must mitigate:

1. **XML injection** via user-supplied names/formulas → structured `ElementTree`
   generation with automatic escaping; never string concatenation into XML.
2. **ZIP slip** on `.twbx` read/write → validate every archive entry resolves
   inside the target directory.
3. **Path traversal** on CSV/output paths → resolve to absolute, reject `..`
   escapes and non-allowlisted roots.
4. **Shell injection** → all subprocess calls use argument lists, never
   `shell=True`; AppleScript is passed via stdin, not interpolated.
5. **Credential leakage** → the server never reads, stores, or logs credentials;
   authentication is delegated entirely to the user's desktop session.
6. **Machine-path leakage into published artifacts** → generated `.twb` must not
   embed temp paths or usernames; verified by test.
7. **Destructive UI automation** → automation is scoped to the Tableau process by
   bundle ID, verifies window titles before acting, and never touches other apps.

---

## 8. Conclusions feeding the architecture decision

1. Publishing to Tableau Public **must** use the visible desktop UI. No supported
   API exists. (§2)
2. No official library can generate a workbook, so the compiler must be
   first-party, built on structures verified from a real 2026.2.0 file. (§3.1)
3. Tableau Public has **no AppleScript dictionary**, so automation must be
   AX-based — and AX permission is already granted. (§1.1, §1.2)
4. A published viz **must contain at least one field**, so "emits valid XML" is
   an insufficient success bar; the workbook must render marks. (§2)
5. The workbook format is ~78% mechanical scaffolding, making template-derived
   compilation markedly more reliable than free-form synthesis. (§5)

These conclusions point to a hybrid compiler + desktop-validation + visible-UI
publishing architecture. That candidate is evaluated against alternatives, rather
than assumed, in `docs/architecture/ARCHITECTURE_DECISION.md`.

---

## Sources

- [Save Workbooks to Tableau Public](https://help.tableau.com/current/pro/desktop/en-us/publish_workbooks_tableaupublic.htm) — accessed 2026-07-26
- [Publishing Methods — Tableau Server REST API](https://help.tableau.com/current/api/rest_api/en-us/REST/rest_api_ref_publishing.htm) — accessed 2026-07-26
- [Publishing Resources — Tableau Server REST API](https://help.tableau.com/current/api/rest_api/en-us/REST/rest_api_concepts_publish.htm) — accessed 2026-07-26
- [Publish a Workbook (Desktop)](https://help.tableau.com/current/pro/desktop/en-us/publish_workbooks_howto.htm) — accessed 2026-07-26
- [Tableau Document API (official docs site)](https://tableau.github.io/document-api-python/) — accessed 2026-07-26
- [tableau/document-api-python README](https://github.com/tableau/document-api-python/blob/master/README.md) — accessed 2026-07-26
- [Tableau Developer Tools & APIs](https://tableau.com/developer/automation) — accessed 2026-07-26
- [PyPI — mcp 1.28.1](https://pypi.org/project/mcp/) — accessed 2026-07-26
- [PyPI — tableauhyperapi 0.0.25080](https://pypi.org/project/tableauhyperapi/) — accessed 2026-07-26
- `https://www.tableau.com/legal/terms-of-service` — **HTTP 403**, not retrievable by automated request on 2026-07-26
