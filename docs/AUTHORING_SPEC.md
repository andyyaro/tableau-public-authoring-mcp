# Authoring Specification (v0.1)

Machine-readable contract: `schemas/workbook-spec-v0.1.json`, which defines the
*shape* of a spec.

**That file is generated, not hand-written.** It is the output of
`models.spec.spec_json_schema()`, built from the same constants and dataclasses
`parse_spec` enforces, and `tests/unit/test_schema_contract.py` fails if the two
diverge — including if the schema is ever made *stricter* than the server, which
it silently was for a long time (it capped lengths and counts nobody enforces,
and omitted `fit` entirely while `additionalProperties: false` would have
rejected it). The same generated schema is what the MCP `build_workbook` and
`validate_workbook_spec` tools advertise as their input schema, so the contract a
caller is shown is the contract that runs.

Everything a schema cannot express — cross-references, field existence, encoding
compatibility, template shelf rules — is checked in `models/spec.py`. Unknown
properties are rejected at every level, so typos fail loudly rather than being
silently dropped.

## Top level

| Key | Required | Notes |
|---|---|---|
| `spec_version` | no | must be `"0.1"` |
| `workbook` | yes | `{ name, description? }` |
| `base_dir` | no | Absolute directory that every **relative** path in the spec is measured from. See below. |
| `data_sources` | yes | one or more CSV sources |
| `calculated_fields` | no | Tableau formula syntax |
| `worksheets` | yes | one or more |
| `dashboards` | no | supported and verified; see `dashboards[]` |
| `output` | yes | `{ directory, package_twbx? }` |

## `data_sources[]`

```json
{ "id": "sites", "type": "csv", "path": "/absolute/path/sites.csv" }
```

`id` is lowercase `[a-z][a-z0-9_]*`. `path` must be absolute, exist, end in `.csv`,
and be under 64 MB / 200k rows / 256 columns. Every CSV is converted to a `.hyper`
extract, because Tableau Public rejects non-extract sources.

Types are inferred from a 500-row sample: `integer`, `real`, `date`, `datetime`,
`boolean`, else `string`. Numerics become measures; everything else a dimension.
Duplicate headers get a numeric suffix.

## `calculated_fields[]`

```json
{ "name": "Readiness Band", "data_source": "sites", "datatype": "string",
  "formula": "IF [Readiness Score] >= 70 THEN \"High\" ELSE \"Low\" END" }
```

Reference physical fields by `[Bracketed Name]`. The name must not collide with an
existing column. Formulas are escaped by the XML serializer, never spliced.

## `worksheets[]`

| Key | Notes |
|---|---|
| `name` | unique within the workbook, and distinct from every dashboard name |
| `template` | `bar`, `line`, `text_table`, `heatmap`, `scatter`, `circle`, `map` |
| `data_source` | must match a declared id |
| `rows`, `columns` | arrays of encoding refs |
| `color`, `size`, `label` | single encoding ref |
| `detail` | array of encoding refs -> Tableau's **Detail** shelf, compiled to `<lod>` |
| `tooltips` | array of encoding refs |
| `filters` | array of **dimension** field names -> interactive filter cards. A measure is rejected: only a categorical filter can be emitted, and over a measure that is a picker listing every distinct number. Band it with a `calculated_field` and filter that. |
| `title`, `subtitle` | rendered above the viz |
| `fit` | `standard`, `fit_width`, `fit_height`, `entire_view` |
| `latitude`, `longitude` | `map` only; encoding refs naming the coordinate columns |

**`detail`** raises the level of detail. Each dimension placed there adds a
grouping key, which is how a sheet draws one mark per entity instead of one per
colour value: a scatter with `Status` on `color` alone draws 3 marks, and adding
`Site Name` to `detail` draws 12. A field may appear on `detail` at most once —
a second copy cannot subdivide the marks further and is always a mistake. Unlike
`tooltips`, dimensions on `detail` keep their `None` derivation rather than being
promoted to `Attribute`, because raising the level of detail is exactly what
Detail is for.

**`fit`** is how the viz fills its canvas. Omit it and each template gets the
default Tableau's own author chose for that shape: `entire_view` for
`text_table`, `heatmap` and `map`, `fit_width` for everything else. Setting
`standard` explicitly gives Tableau's Standard fit, which draws a small viz
tucked into the top-left corner.

**`latitude` / `longitude`** are the `map` template's axes, not encodings: the
compiler puts latitude on rows and longitude on columns itself, because that
order is a rule of Tableau's projection rather than a caller's choice. Both are
inferred when omitted, from columns whose names identify them as coordinates —
supply them explicitly only when inference is ambiguous, which it is when a data
source has more than one candidate column (that is an error, not a guess).
Coordinates are always **averaged**: asking for `Sum` is rejected, because
summing latitudes places every mark at one meaningless point.

### Encoding reference

Either a bare field name, or an object:

```json
"Site Name"
{ "field": "Readiness Score", "aggregation": "Sum" }
```

Aggregations: `Sum`, `Avg`, `Min`, `Max`, `Count`, `CountD`, `None`, `Attribute`.

**Dimensions placed on `tooltips` are automatically promoted to `Attribute`.** With
`None` they become level-of-detail fields, Tableau cannot resolve the reference, and
the sheet renders blank with a red pill. This is applied for you.

### Template requirements

| Template | Requires |
|---|---|
| `bar`, `line`, `heatmap`, `scatter`, `circle` | rows **and** columns |
| `text_table` | rows |
| `scatter` | aggregated measures on both shelves |
| `map` | **neither** rows nor columns — its axes are its coordinates. Needs at least one dimension on `detail`, `color` or `label`, or every row averages into a single point. `rows`/`columns` are not offered as a second pair of axes. |

`latitude` and `longitude` are rejected on every template except `map`.

## `dashboards[]`

```json
{ "name": "Overview", "title": "EV Charging Overview", "direction": "horizontal",
  "sizing_mode": "fixed", "width": 1200, "height": 800,
  "worksheets": ["Readiness by Site", { "worksheet": "Chargers", "show_title": false }] }
```

| Key | Notes |
|---|---|
| `name` | required; unique, and must not collide with a worksheet name — both are registered in `<windows>` by name |
| `title` | optional, 1-300 chars |
| `direction` | `vertical` (default) or `horizontal` |
| `sizing_mode` | `fixed` (default) or `automatic` |
| `width`, `height` | pixels, 100-10000, default 1200x800. **Rejected** when `sizing_mode` is `automatic`, which has no declared canvas at all — accepting a size there would silently discard it |
| `worksheets` | required, up to 20 zones. Each is a worksheet name, or `{ worksheet, show_title }` |

Scope is deliberately the smallest thing that is verified: worksheets tiled in
**one** horizontal or vertical container, plus an optional title. A worksheet may
appear at most once per dashboard. Filter cards, colour legends, highlighters,
parameter controls, images, floating zones, device layouts and dashboard actions
are understood but **not generated** — see
`docs/architecture/CAPABILITY_BOUNDARY.md`.

A zone references its worksheet by bare name; there is no id behind it, so an
unresolvable name would produce a file that loads without complaint and draws an
empty box. That is why the reference is checked in layer 1 *and* again against
the generated file in layer 2 (`validation.structure.unresolved_zone_worksheet`).

## Paths

Every path may be absolute, a `~` path, or **relative to `base_dir`**:

```json
{
  "base_dir": "/Users/you/analysis",
  "data_sources": [{ "id": "sites", "type": "csv", "path": "data/sites.csv" }],
  "output": { "directory": "out" }
}
```

That is the ergonomic reason — one absolute path instead of N. The security
property runs the other way, and is why relative paths are accepted at all:

> **A relative path is contained. An absolute path is not.**

A relative path is resolved against `base_dir` and then required to still be
inside it, so it can address nothing the spec author did not put there. The
check runs **after** symlinks are resolved, so `data/../../etc/passwd` and a
symlink inside the base pointing out of it are both rejected. An absolute path
keeps its existing meaning and reach — confining it would silently break specs
that mix the two.

A relative path with no `base_dir` is an error. It is never resolved against the
process working directory: an MCP server inherits that from whichever client
launched it, so the same spec would address different files on different
machines. Set `base_dir` in the spec, or `TABLEAU_MCP_WORKSPACE` in the
environment to supply a default.

Setting `TABLEAU_MCP_WORKSPACE` and using only relative paths is the strongest
posture available: nothing outside that directory is reachable.

## Validation

`validate_workbook_spec` runs everything below without writing files:

1. structural — the spec's shape, against the generated JSON Schema;
   unknown keys rejected at every level
2. path safety (absolute, no traversal, exists, size caps)
3. cross-references (every field exists in its data source; every dashboard zone
   names a real worksheet)
4. encoding compatibility (e.g. `size` needs a measure; a map coordinate must be
   numeric)
5. template shelf requirements

Steps 2-5 are semantic and live in `models/spec.py`, because a JSON Schema cannot
express them: whether a field name resolves depends on the CSV on disk, not on
the document. `build_workbook` runs all of it and then a second, independent
layer over the *generated* file (`validation/structure.py`) — see
`docs/VALIDATION_REPORT.md` for what each layer caught.
