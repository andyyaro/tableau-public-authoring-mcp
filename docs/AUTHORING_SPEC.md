# Authoring Specification (v0.1)

Machine-readable contract: `schemas/workbook-spec-v0.1.json`.
Unknown properties are rejected everywhere, so typos fail loudly.

## Top level

| Key | Required | Notes |
|---|---|---|
| `spec_version` | no | must be `"0.1"` |
| `workbook` | yes | `{ name, description? }` |
| `data_sources` | yes | 1-20 CSV sources |
| `calculated_fields` | no | Tableau formula syntax |
| `worksheets` | yes | 1-50 |
| `dashboards` | no | must be empty (not supported in v0.1) |
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
| `name` | unique within the workbook |
| `template` | `bar`, `line`, `text_table`, `heatmap`, `scatter`, `circle` |
| `data_source` | must match a declared id |
| `rows`, `columns` | arrays of encoding refs |
| `color`, `size`, `label` | single encoding ref |
| `tooltips` | array of encoding refs |
| `filters` | array of field names -> interactive filter cards |
| `title`, `subtitle` | rendered above the viz |

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

## Validation

`validate_workbook_spec` runs everything below without writing files:

1. structural (JSON Schema, unknown keys rejected)
2. path safety (absolute, no traversal, exists, size caps)
3. cross-references (every field exists in its data source)
4. encoding compatibility (e.g. `size` needs a measure)
5. template shelf requirements
