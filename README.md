# Tableau Public Authoring MCP

An MCP server that **authors** Tableau workbooks from a declarative spec, **validates**
them by opening them in the installed Tableau Public application, and **publishes**
through Tableau's own visible desktop workflow.

> This is the counterpart to the existing **reader** MCP (`tableau-public`), which
> inspects already-published content. The reader cannot create or publish anything.
> This server cannot browse public profiles. Keep both installed.

---

## What it does

| | Reader MCP (`tableau-public`) | This server (`tableau-public-authoring`) |
|---|---|---|
| Search / inspect public profiles | ✅ | ❌ |
| Download & unpack `.twbx` | ✅ | inspect only |
| **Create** a workbook | ❌ | ✅ |
| **Open** it in Tableau Public | ❌ | ✅ |
| **Publish** to your account | ❌ | ✅ (visible UI) |

## Verified capabilities

Everything below was confirmed by generating a workbook and **opening it in
Tableau Public 2026.2.0 on macOS**, not merely by producing XML.

**Supported**
- CSV data sources, automatically materialised into `.hyper` extracts
- Field type inference: string, integer, real, boolean, date, datetime
- Worksheet templates: `bar`, `line`, `text_table`, `heatmap`, `scatter`, `circle` (all six screenshot-verified)
- Dashboards: title, fixed or automatic canvas, worksheets tiled in one container
- Calculated fields (Tableau formula syntax)
- Categorical filters, rendered as interactive filter cards
- Encodings: color, size, label, tooltip
- Worksheet titles and subtitles
- `.twb` output and `.twbx` packaging, deterministic and reproducible

**Not supported in v0.1** — see `docs/architecture/CAPABILITY_BOUNDARY.md`
- Stories, parameters, LOD expressions, joins/custom SQL, live connections
- A `detail` encoding (so scatter aggregates by colour, not per row)
- Dashboard filter cards, legends, actions, floating zones, device layouts

## Two constraints that shape everything

1. **Tableau Public has no publishing API.** The REST API covers Server/Cloud only.
   The single documented path is `Server > Tableau Public > Save to Tableau Public`,
   so publishing is driven through the real UI.
2. **Tableau Public rejects non-extract data sources** (`Error Code: 3C242D89`).
   Every CSV is therefore converted to a Hyper extract at build time.

## Requirements

- macOS with Tableau Public installed (developed against 2026.2.0, Apple silicon)
- Python ≥ 3.10, [`uv`](https://docs.astral.sh/uv/)
- macOS **Accessibility** permission for the process running this server
- macOS **Screen Recording** permission (for validation screenshots)

See `docs/MACOS_PERMISSIONS.md`.

## Install

```bash
git clone <this repo> ~/dev/mcp-tableau-public-authoring
cd ~/dev/mcp-tableau-public-authoring
uv venv && uv pip install -e . && uv pip install tableauhyperapi pyobjc-framework-Quartz
```

## Register with Claude Code

```bash
claude mcp add --transport stdio --scope user tableau-public-authoring \
  -- /Users/<you>/dev/mcp-tableau-public-authoring/.venv/bin/python \
     -m tableau_public_authoring.server
```

Registering this server does **not** affect any existing MCP. Verify with
`claude mcp list`. A Claude Code restart is required before the new tools appear.

## Build a workbook

```json
{
  "spec_version": "0.1",
  "workbook": { "name": "EV Charging Readiness", "description": "Generated" },
  "data_sources": [{ "id": "sites", "type": "csv", "path": "/abs/path/sites.csv" }],
  "calculated_fields": [{
    "name": "Readiness Band", "data_source": "sites", "datatype": "string",
    "formula": "IF [Readiness Score] >= 70 THEN \"High\" ELSE \"Low\" END"
  }],
  "worksheets": [{
    "name": "Readiness by Site", "template": "bar", "data_source": "sites",
    "rows": ["Site Name"],
    "columns": [{ "field": "Readiness Score", "aggregation": "Sum" }],
    "color": "Readiness Band",
    "filters": ["Status"],
    "title": "EV Charging Readiness by Site"
  }],
  "output": { "directory": "/abs/path/output", "package_twbx": true }
}
```

Then: `validate_workbook_spec` (dry run) → `build_workbook` →
`validate_in_tableau_public` → `publish_to_tableau_public`.

Full schema: `schemas/workbook-spec-v0.1.json` and `docs/AUTHORING_SPEC.md`.

## Publishing

`publish_to_tableau_public` is marked destructive and requires
`confirm_publish: true`; `overwrite` defaults to `false`. It drives the visible
menu command and **never reads, types, or stores credentials** — it uses your
existing signed-in desktop session. If Tableau needs a sign-in, the tool stops and
tells you to sign in manually. Publication is irreversible and world-visible.

Use `dry_run: true` to see exactly what would happen first.

## Tests

```bash
uv run pytest                    # unit + integration (no Tableau needed)
uv run pytest -m live            # requires Tableau Public installed
uv run ruff check . && uv run ruff format --check .
```

`live` and `publish` tests are excluded from normal runs and must never run in CI.

## Security

No credentials are stored anywhere. XML is generated through `ElementTree`
(never string concatenation), archives are ZIP-slip guarded, paths are
traversal-checked, and generated workbooks are scanned for machine-identifying
data before packaging. See `docs/SECURITY.md` and
`docs/architecture/THREAT_MODEL.md`.

## Rollback

```bash
claude mcp remove --scope user tableau-public-authoring
```

This leaves all other MCP servers untouched. See `docs/ROLLBACK.md`.

## License

MIT — see `LICENSE`.
