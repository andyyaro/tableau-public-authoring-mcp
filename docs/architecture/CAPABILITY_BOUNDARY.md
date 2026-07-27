# Capability Boundary

Status of every capability, by evidence. **Verified** means a workbook using it was
generated, opened in Tableau Public 2026.2.0, and rendered marks.

## Fully supported (verified end-to-end, including live publication)

| Capability | Evidence |
|---|---|
| CSV data source -> Hyper extract | published workbook renders live |
| Field inference (string/integer/real/boolean/date/datetime) | correct icons + geo roles in Tableau's Data pane |
| `bar` template | 12 marks rendered; live public URL |
| `text_table` template | second sheet in the published workbook |
| `line` template | 11 marks, screenshot-verified |
| `heatmap` template | 12 marks in a State x Status grid, screenshot-verified |
| `scatter` template | renders; see the level-of-detail caveat below |
| `circle` template | 12 marks, screenshot-verified |
| **`map` template** | **VERIFIED** - background map with state boundaries and Mapbox/OpenStreetMap attribution; 12 symbol marks, one per site, each in its correct state; screenshot-verified |
| Geographic roles (lat/long) | `Latitude`/`Longitude` detected by name, tagged `[Geographical].[Latitude]`/`[Longitude]`, shown with the globe icon in Tableau's Data pane |
| Canvas fit (`fit`) | toolbar reads "Entire View"; viz fills the canvas |
| Mark labels | values drawn in the marks, screenshot-verified |
| **Dashboards** | **VERIFIED** - opened in Tableau Public 2026.2.0; title, both worksheets and fixed 1200x800 sizing all render |
| Calculated fields | `Readiness Band` colours the published bars |
| Categorical filters | interactive "Status (All)" filter card |
| Color / label / tooltip encodings | all pills resolve (blue, not red) |
| Size encoding | circle radii vary with a measure, screenshot-verified **by hand** during the v0.1 run |
| Detail encoding (`detail`) | `Site Name` on Detail raises a scatter from 3 marks to 12, screenshot-verified |
| Second-source worksheet marks | the sheet bound to the *second* data source is screenshot-verified rendering by `tests/live/test_encodings_and_sources.py` |
| Multiple data sources | two CSVs -> two `.hyper` extracts under separate `Data/<id>/`; both load in Tableau. Verified **by hand**; the marks of the sheet bound to the *second* source were never individually confirmed |
| Titles + subtitles | rendered in the live public viz |
| `.twb` generation, `.twbx` packaging | opens without repair dialog |
| Publish via visible desktop UI | workbook live on public.tableau.com, HTTP 200 |

## Partially supported (generated + opens; marks not individually verified)

| Capability | Gap |
|---|---|
| Map extras | Filled/choropleth maps, custom territories, map layers, spatial files and custom geocoding are not generated. The `map` template plots latitude/longitude symbol marks on Tableau's background map. A saved viewport is deliberately not emitted, so Tableau auto-fits to the data. |
| Dashboard extras | Filter cards, colour legends, highlighters, parameter controls, images, floating zones, device layouts and dashboard actions are not generated. Only worksheet zones in a single horizontal or vertical container are supported. |

## Unsupported (rejected with a clear error)

Stories, parameters, LOD expressions, joins, custom SQL, live (non-extract)
connections, sets/groups/hierarchies, table calculations, reference lines,
and workbook-level formatting.

`parse_spec` now parses `dashboards` (experimental, above). Dashboard **actions**,
filter/legend/highlighter cards, parameter controls, images, floating zones and
device layouts remain rejected.

## Environmental constraints (not fixable in code)

1. **Tableau Public requires extracts.** Live connections are rejected with
   `Error Code: 3C242D89`. Every CSV is converted to `.hyper`.
2. **A viz must contain at least one field** before Tableau enables
   "Save to Tableau Public".
3. **No publishing API exists.** Publishing needs the desktop app, a signed-in
   session, macOS Accessibility + Screen Recording, and a visible UI. It cannot
   run headless or in CI.
4. **Tableau is a Qt app.** Accessibility `click`/`AXPress` on its menus silently
   no-op. Only real `CGEvent` HID clicks work. See `docs/LIMITATIONS.md`.
