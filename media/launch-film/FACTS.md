# Tableau Public Authoring MCP film: FACTS

Every claim on screen or in the narration, its source and the value checked. Repo = github.com/andyyaro/tableau-public-authoring-mcp
(public, MIT), cloned at **d77186f** (2026-11-01, "Add project logo") into the scratch dir. "Probe" = `research/real-responses.json`: the server's own
`call_tool()` run offline at d77186f in a scratch venv, with `osascript`, `open` and `screencapture` shimmed to fail so nothing could touch the GUI.
Tableau Public is not installed on this Mac (`/Applications/Tableau Public.app` absent), and no desktop app was opened.

## Narration

| id | Line (written) | Source | Verified |
|---|---|---|---|
| v01 | Tableau Public has no publishing API. | README "Two constraints" 1; docs/architecture/ARCHITECTURE_DECISION.md finding 1 | "Tableau Public has no publishing API. The REST API covers Server/Cloud only" |
| v02 | And no official library can build workbooks from scratch. | ARCHITECTURE_DECISION.md finding 2 | "No official library can create a workbook from scratch. The Tableau Document API states verbatim that it does not support 'creating files from scratch'" |
| v03 | Tableau Public Authoring MCP builds and publishes them anyway. | README H1 + first paragraph; repo description | authors workbooks from a spec, publishes "through Tableau's own visible desktop workflow" (not an API; the film never says API) |
| v04 | Describe a workbook in JSON. | README "Build a workbook"; schemas/workbook-spec-v0.1.json; docs/AUTHORING_SPEC.md | declarative JSON spec |
| v05 | A dry run checks every field against the data, so a typo fails with the right names. | docs/MCP_TOOLS.md (`validate_workbook_spec`: "dry-run validation, writes nothing"); AUTHORING_SPEC.md Validation 3; probe `validate_typo_Stauts` | real response: `specification error: worksheets[0].color: field 'Stauts' does not exist in data source 'sites'. Available: ['Annual Sessions', 'Assessment Date', 'Charger Count', 'City', 'Estimated Cost', 'Latitude', 'Longitude', 'Readiness Score', 'Site Name', 'State', 'Status']`; valid spec returns `"valid": true, "note": "dry run - no files were written"` |
| v06 | The compiler writes the workbook, and turns each CSV into the Hyper extract Tableau Public requires. | compiler/build.py, compiler/extract.py (tableauhyperapi), compiler/workbook.py (`xml.etree.ElementTree`); README "Two constraints" 2 | "Tableau Public rejects non-extract data sources (Error Code: 3C242D89). Every CSV is therefore converted to a Hyper extract at build time." Probe build entries: `Demo_Map.twb`, `Data/sites/sites.hyper`, `Data/sites/sites.csv`, warnings `[]` |
| v07 | Then it opens the file in the real Tableau Public app, and photographs it. | MCP_TOOLS.md `validate_in_tableau_public` ("layers 3+4: open, detect dialogs, screenshot"); server.py lines 367-385 | payload layers `layer3_open`, `layer4_screenshot`, `no_error_dialog` |
| v08 | Five of Tableau's load rules only showed up that way. | docs/LIMITATIONS.md §2; docs/VALIDATION_REPORT.md layer 3 | "Five concrete constraints were discovered only by loading files into Tableau"; the five error strings below |
| v09 | Every screenshot here is a generated workbook, untouched in Tableau. | README "What it produces" | "Every screenshot below is a workbook generated from a JSON spec by this server, then opened in Tableau Public 2026.2.0 and photographed. Nothing was authored by hand, and nothing was touched in Tableau before the screenshot was taken. The data is the synthetic 12-row fixture". The film shows only these three images as screenshots. |
| v10 | Publishing drives Tableau's own save flow, in your signed-in session. | README "Publishing"; docs/PUBLISHING_WORKFLOW.md | "drives the visible command ... it uses your existing signed-in desktop session"; `File > Save to Tableau Public As...` invoked with a real Command+Shift+S |
| v11 | It never reads credentials, and won't replace a live workbook unless told to. | README "Publishing"; THREAT_MODEL.md T5, T8; publishing/existing.py; server.py 388-440 | "never reads, types, or stores credentials"; `overwrite` defaults to `false`; refuses a name collision unless `overwrite: true`; fails closed ("UNABLE TO VERIFY") |
| v12 | 507 tests pass without Tableau. 15 more drive the real app. | `uv sync` + `pytest -q` at d77186f (Python 3.13.14, scratch venv, GUI tools shimmed), 37.99 s | `507 passed, 15 deselected`; `pytest --collect-only -m live` = 15 tests in tests/live (dashboard 2, encodings 2, publish-flow guards 4, render templates 7), which "drive a visible GUI" (tests/live/conftest.py). Live tier not run here. `ruff check .` = All checks passed. |
| v13 | Tableau Public Authoring MCP. | README H1 | name |
| v14 | Declarative specs, compiled into Tableau workbooks. | docs/assets/brand/logo-sheet.png tagline | verbatim |

## On screen

| Item | Source | Value |
|---|---|---|
| Hook card 1 "Publishing API" / "the REST API covers Server and Cloud only" / "● none" | README, ADR finding 1 | as above |
| Hook card 2 "Build from scratch" / "the Document API can't create files from scratch" / "● none" | ADR finding 2 | as above |
| Chip "MCP server · MIT · macOS" | brand README ("MCP server · MIT"); LICENSE (MIT); README Requirements ("macOS with Tableau Public installed") | yes |
| "Claude Code" / "MCP client · over stdio" | README "Register with Claude Code" (`claude mcp add --transport stdio ...`); THREAT_MODEL trust boundary `[ Claude / MCP client ] --stdio-->` | yes. No Claude logo. |
| Zone "tableau-public-authoring" / "MCP server · 10 tools" | docs/MCP_TOOLS.md ("10 tools"); server.py `list_tools` (10 `Tool(` entries) | 10: get_authoring_capabilities, list_workbook_templates, validate_workbook_spec, build_workbook, inspect_local_workbook, get_tableau_public_app_status, open_in_tableau_public, validate_in_tableau_public, publish_to_tableau_public, verify_published_workbook |
| Spec card (map worksheet) | README "The spec behind the map" | `"name": "Site Map", "template": "map", "data_source": "sites", "detail": ["Site Name"], "color": "Status", "size": { "field": "Annual Sessions", "aggregation": "Sum" }, "title": "Candidate sites"`. NOTE: demo_map.png also shows `City` on Label and a subtitle, which the README snippet omits, so the film never says this snippet is the screenshot's entire input. The probe compiled this snippet (wrapped in a minimal workbook) without warnings. |
| "sites.csv" / "12 rows · synthetic fixture" | tests/fixtures/data/ev_site_readiness.csv (13 lines = header + 12); README "synthetic 12-row fixture" | 11 columns, 12 rows |
| Typo "Stauts" + error card + "Available:" chips | probe `validate_typo_Stauts` | verbatim text above; chips may show a subset of the list ending in "Site Name" "State" "Status" |
| "● valid" | probe `validate_ok` | `"valid": true` |
| "Compiler" / "ElementTree XML, never string splicing" / ".twb" | compiler/workbook.py line 21 `import xml.etree.ElementTree as ET`; README Security; THREAT_MODEL T1 | yes |
| "Hyper extract" / "tableauhyperapi" / ".hyper" | compiler/extract.py (imports tableauhyperapi); pyproject dependency `tableauhyperapi>=0.0.25080` (Tableau's Hyper API, credited by name) | yes |
| Edge label "required: Error Code 3C242D89 without it" | README "Two constraints" 2; VALIDATION_REPORT semantic failure | `Workbooks saved to Tableau Public must use extracts` (3C242D89) |
| "Package" / "ZIP-slip guarded" / ".twbx" | packaging/twbx.py (safe_archive_name, assert_within); THREAT_MODEL T2; README Security | yes |
| "Checks" / "no machine paths · structure valid" / "● warnings: none" | compiler/build.py: `contains_machine_identifiers` before packaging, `validate_generated` (layer 2) after; probe warnings `[]` | yes |
| Chips "Demo_Map.twb" "Data/sites/sites.hyper" "Data/sites/sites.csv" | probe `build_workbook_1.build.package_entries` | verbatim |
| "Tableau Public 2026.2.0" | README, VALIDATION_REPORT, CHANGELOG | version the project was verified against |
| "● opened" "● no error dialog" "● screenshot" | server.py validate_in_tableau_public payload | `layer3_open`, `no_error_dialog`, `layer4_screenshot` |
| The five load errors | VALIDATION_REPORT.md layer 3 table (also LIMITATIONS §2) | `missing required attribute 'dim-percentage'` · `no declaration found for element 'object-graph'` · `element 'filter' is not allowed for content model` · `element 'panes' is not allowed for content model` · `attribute 'object-id' is not declared for element 'extract'`; each "fixed" (table's Fix column) |
| demo_dashboard.png caption "Dashboard · two generated sheets, 1200 x 800" | README ("two generated worksheets tiled in one container, fixed 1200×800 canvas"); the image ("Custom size (1200 x 800)") | yes (written "1200 x 800", no multiplication sign needed) |
| demo_map.png caption "Symbol map · 12 marks" | README; image status bar "12 marks" | yes |
| demo_bar.png caption "Bar chart · colour and labels" | README ("colour by dimension, mark labels drawn"); image subtitle "Bar chart with colour and mark labels" | yes |
| Caption chip "generated from a spec · untouched in Tableau Public 2026.2.0 · synthetic 12-row data" | README "What it produces" | yes |
| "publish_to_tableau_public" / "Save to Tableau Public As..." / "Command+Shift+S" | PUBLISHING_WORKFLOW.md; MCP_TOOLS.md; publisher.py line 398 `real_key(VK_ANSI_S, command=True, shift=True)` | yes (Public edition puts it on the File menu, not Server) |
| "● your signed-in session" | README "Publishing" | yes |
| Guards chips "confirm_publish: true" "profile" "overwrite: false" | server.py publish schema (`required: workbook_window, public_name, confirm_publish, profile`), `overwrite` default false | yes |
| "credentials: never read, typed or stored" | README "Publishing"; THREAT_MODEL T5 | "never reads, types, or stores credentials" |
| Refusal card "refusing to publish: confirm_publish must be true." | probe `publish_without_confirm` | real text continues "Publication to Tableau Public is irreversible and world-visible." (may be shown in full) |
| "public.tableau.com" / "public and irreversible" | THREAT_MODEL boundary 4 ("irreversible and world-visible"); README | yes |
| "verify_published_workbook · HTTP 200" | MCP_TOOLS.md; VALIDATION_REPORT layer 5 and PUBLISHING_WORKFLOW "Verified run (2026-07-27)": published `MCP_Authoring_Validation_-_20260727-0050`, public URL HTTP 200 | yes, one verified run |
| Header "How Tableau Public Authoring MCP works" + legend (runs without Tableau / needs Tableau Public on this Mac / public and irreversible) | ADR Consequences ("Generation is deterministic and unit-testable without Tableau installed"; "Desktop automation cannot run headless"); README Publishing | grouping is the film's, each card's placement follows the docs: validate/build without Tableau; open/validate_in need the app; publish is public |
| Tests card "pytest" / "commit d77186f" / "507" "pass without Tableau installed" / "● 15 live tests drive the real app" | pytest run above | 507 passed, 15 deselected, at d77186f |
| ".twb byte-identical on rebuild" | probe `determinism`; LIMITATIONS §1; test `test_twb_generation_is_byte_deterministic` | two builds (two different output folders): .twb SHA-256 `1c646bbc...29b6d3` both times; .twbx differs (Hyper writes non-deterministic state; never claim the .twbx is reproducible) |
| End line 2 "github.com/andyyaro/tableau-public-authoring-mcp" | `gh repo view` | public, MIT, created 2026-07-27 |
| App icon | docs/assets/brand/icons/icon-rounded.svg (copied unchanged to assets/brand/) | braces #FF4FA3, bars #FFD9C2, ground #2A0E33 |

## Brand

- Mark: two pink braces around three rising peach bars. Files copied: `assets/brand/mark-color.svg`, `mark-black.svg`, `mark-white.svg`,
  `icon-rounded.svg`, `icon-square.svg`, `favicon.svg`, `icon-512.png`, and the brand README as `BRAND-README.md`.
- Colours (brand README): #2A0E33, #FF4FA3, #FFD9C2, #FFF0F6.
- Wordmark typeface: Martian Mono SemiBold, a MONOSPACE face. The lockup SVGs carry it as outlines, so they are deliberately not copied and not
  used; the film sets the name in the system face (HostUI = SF Pro). Supporting text on the brand sheet is Geist; the film follows the HIG look instead.
- The project has no website (no homepage on the repo); the URL on the end card is the GitHub repo.

## Numbers checked and NOT used

| Claim | Where | Why not |
|---|---|---|
| "419 tests" | Andy's private project notes | stale: today 522 collected (507 offline passed + 15 live) at d77186f |
| "~17,000 lines, more test code than source" | Andy's private project notes | measured 16,925 Python lines (src 8,209, tests 8,716): true, but not needed on screen |
| "39 tests" at v0.1.0 | CHANGELOG | historical |
| Strategy D 212/240 (88.3%) | ADR | true, but a decision-matrix score is noise for a launch film |
| "1 star" | Andy's private project notes, GitHub | not a selling point; never show |
| VALIDATION_REPORT counts | the report says itself they are frozen and not to be read as current | only its layer-3 error strings are used |

## Credits and honesty notes

- Solo project by Andy Yaro (Andy's project notes say "Solo"; every commit authored Andy Yaro; Jul 27 to Aug 19, 2026, logo added 2026-11-01). The ADR records
  "Decision owner: Claude Code autonomous run", so it was built with Claude Code; the film makes no claim either way.
- Upstream named on screen: Tableau Public (the app it drives), Tableau's Hyper API (`tableauhyperapi`), Claude Code (the client in the README).
  Tableau's own logo is never drawn; it appears only inside the real screenshots. Data in the screenshots is synthetic.
- The compiler's structures were derived from a real workbook produced by Tableau Public 2026.2.0 (ADR; docs/fixtures/); the film does not
  claim Tableau documents the format (LIMITATIONS §2: "not a published schema").
- Known caveats not shown (true, but out of scope): Save-button click uses calibrated coordinates (LIMITATIONS §7); window targeting is fragile
  (§4); `dry_run` payload has two stale fields (PUBLISHING_WORKFLOW).

## Architecture map (the board's parts, real names, arrows)

| # | Part | Real name / code | On the board |
|---|---|---|---|
| 1 | MCP client | Claude Code (README registration), over stdio | "Who asks" |
| 2 | Workbook spec | JSON, `schemas/workbook-spec-v0.1.json` (generated from `models/spec.py`) | "Who asks" |
| 3 | CSV data | `sites.csv` (`tests/fixtures/data/ev_site_readiness.csv`, 12 synthetic rows) | "Who asks" |
| 4 | The server | `tableau-public-authoring` (`server.py`), 10 tools | zone |
| 5 | Dry run | `validate_workbook_spec` -> `models/spec.parse_spec` (layer 1) | zone |
| 6 | Compiler | `compiler/workbook.py` `WorkbookCompiler`, ElementTree -> `.twb`; deterministic ids `compiler/ids.py` (SHA-256) | zone |
| 7 | Hyper extract | `compiler/extract.py` `build_hyper` (tableauhyperapi) -> `.hyper` | zone |
| 8 | Checks | `security/paths.contains_machine_identifiers` (before packaging), `validation/structure.validate_generated` (layer 2) | zone |
| 9 | Package | `packaging/twbx.package_twbx` -> `.twbx` (ZIP-slip guarded) | zone |
| 10 | Tableau Public 2026.2.0 | `desktop/tableau_app.py`, `desktop/window_control.py` (CGWindowList + real CGEvent clicks and keys) | "On this Mac" |
| 11 | Open and photograph | `validate_in_tableau_public` (layers 3+4), `open_in_tableau_public` | "On this Mac" |
| 12 | Screenshots | docs/images/demo_dashboard.png, demo_map.png, demo_bar.png | "On this Mac" |
| 13 | Publisher | `publishing/publisher.py`: `assert_target_frontmost`, Command+Shift+S, "Save Workbook to Tableau Public" dialog, sign-in hand-off | "Outside" |
| 14 | Overwrite guard | `publishing/existing.assert_safe_to_publish` (profile lookup, fails closed) + `confirm_publish` gate in server.py | "Outside" |
| 15 | public.tableau.com | the profile and the public URL | "Outside" |
| 16 | Verify | `verify_published_workbook` (expects 2xx/3xx; the 2026-07-27 run got HTTP 200) | "Outside" |
| 17 | Preflight | `doctor.py` / `tableau-public-authoring doctor` (8 checks) | not on the board (kept out to stay calm) |
| 18 | Tests | pytest: 507 offline + 15 live | bottom right, lit at the overview |

Arrows: Claude Code -> server ("stdio") · spec -> validate_workbook_spec ("dry run") · validate -> Compiler · sites.csv -> Hyper extract ·
Compiler + Hyper extract -> Checks -> Package (".twbx") · Package -> Tableau Public ("open") · Tableau Public -> screenshot ("layer 4") ·
Tableau Public -> publish_to_tableau_public (dashed, "Command+Shift+S") · Guards -> publish · publish -> public.tableau.com (dashed, "public") ·
verify_published_workbook -> public URL ("HTTP 200").

## Real artifacts available

- Screenshots (untouched, generated from specs): `assets/artifacts/demo_dashboard.png`, `demo_map.png`, `demo_bar.png` (2582 x 1898 each).
- The map worksheet spec (README), the full EV example spec (README "Build a workbook", with the `Readiness Band` calculated field), `tests/fixtures/validation_spec.json`.
- Real tool responses (probe): dry run ok, the `Stauts` typo error, `build_workbook` result, `list_workbook_templates` (7 templates and their mark classes),
  both publish refusals, the `.twb`/`.twbx` hashes, the generated `.twb` lines with `semantic-role="[Geographical].[Latitude]"`.
- Tableau's five load-error strings and the 3C242D89 extract error (VALIDATION_REPORT).
- The `doctor` output block (README) with 8 PASS rows (shown in the README as an example from the author's machine; not reproduced here, Tableau absent).
- Test output: `507 passed, 15 deselected in 37.99s` (and the live-tier banner "live tier: 15 test(s) not selected ...").
