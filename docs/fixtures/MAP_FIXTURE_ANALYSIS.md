# Map fixture analysis

Source: a map sheet from a **reference workbook** - a real workbook published to
Tableau Public, downloaded and unpacked. It renders a working map, so its XML is
the specification for what the `map` template must emit. Nothing here is inferred
from documentation.

## 1. Three load-bearing pieces

A map differs from a scatter plot by exactly three things. Each fails *silently* -
no error dialog, just a wrong-looking sheet - which is why all three are pinned by
`tests/unit/test_maps.py` rather than left to a live screenshot.

| Piece | Missing it produces |
|---|---|
| `<mapsources><mapsource name="Tableau"/></mapsources>` | marks on blank white space, no coastline |
| `semantic-role="[Geographical].[Latitude]"` | an ordinary scatter plot of two measures |
| `aggregation="Avg"` on the coordinates | one mark, at the average of all coordinates |

## 2. `<mapsources>` placement

Inside `<worksheet><table><view>`, between `<datasources>` and
`<datasource-dependencies>`:

```xml
<view>
  <datasources>
    <datasource caption="sites" name="federated.abc123…" />
  </datasources>
  <mapsources>
    <mapsource name="Tableau" />
  </mapsources>
  <datasource-dependencies datasource="federated.abc123…">
```

Tableau's loader enforces a DTD content model and rejects misordered children, so
this position is a constraint, not a convention.

## 3. Coordinate columns

Declared identically in the data source and in `datasource-dependencies`:

```xml
<column aggregation="Avg" datatype="real" name="[Latitude]"  role="measure"
        semantic-role="[Geographical].[Latitude]"  type="quantitative" />
<column aggregation="Avg" datatype="real" name="[Longitude]" role="measure"
        semantic-role="[Geographical].[Longitude]" type="quantitative" />
```

The `aggregation` attribute is an **override**. The underlying
`<metadata-record>` still carries `<aggregation>Sum</aggregation>`, which is the
default that would otherwise apply.

Note that latitude and longitude take **different** semantic roles. An earlier
version of `compiler/fields.py` mapped both to `[Country].[Name]` - the role for a
country *name* column. Nothing ever called that function, so the error survived
until maps were implemented.

## 4. Column instances and shelves

```xml
<column-instance column="[Latitude]"  derivation="Avg" name="[avg:Latitude:qk]"  pivot="key" type="quantitative" />
<column-instance column="[Longitude]" derivation="Avg" name="[avg:Longitude:qk]" pivot="key" type="quantitative" />
…
<rows>[federated.abc123…].[avg:Latitude:qk]</rows>
<cols>[federated.abc123…].[avg:Longitude:qk]</cols>
```

**Latitude on rows, longitude on cols.** This is fixed by the projection, not a
preference - swapping them renders the transpose of the world without complaint.
The compiler therefore assigns the shelves itself and does not accept `rows`/
`columns` for a map.

## 5. Level of detail

```xml
<lod column="[federated.abc123…].[none:Site Name:nk]" />
```

Without a grouping key, `AVG(Latitude)` and `AVG(Longitude)` collapse every row
into a **single mark** at the centroid. The fixture puts the site label on Detail;
Tableau's own UI does this automatically when you drag a geographic field onto the
canvas. `parse_spec` therefore requires at least one dimension on
`detail`/`color`/`label` for a map, and says why when it is missing.

## 6. Marks

The fixture uses `<mark class="Shape" />` because it encodes a `shape` field,
which this compiler does not support. `Circle` is Tableau's default for a plain
symbol map and needs no shape palette, so the `map` template emits that.

## 7. Deliberately not copied

* **Saved viewport.** The fixture pins the visible extent with a `style-rule`
  carrying `projection="EPSG:3857"` and fixed min/max on both axes. Omitting it
  lets Tableau auto-fit to the data, which is the better default for generated
  workbooks - a pinned viewport computed from someone else's coordinates would
  show the wrong part of the world.
* **`<format attr="washout" value="0.0" />`** on the `map` style element -
  cosmetic basemap fade.
* **Filled maps, custom territories, map layers, spatial files, custom geocoding.**
  None appear in this fixture and none are generated.

## 8. Verified live

A generated `map` worksheet was opened in Tableau Public 2026.2.0: background map
present with state boundaries and Mapbox/OpenStreetMap attribution, **12 marks**
(one per site), coloured by a dimension, sized by a measure, with `Latitude` and
`Longitude` showing the globe icon in the Data pane. See
`docs/architecture/CAPABILITY_BOUNDARY.md`.
