"""Map template: geographic roles, axes, and the background map.

Every structural assertion here is pinned to a published workbook that renders a
real map — the author's own `Quarterly_Sales_Review`, sheet
"Map - Review Burden by Candidate Site" (docs/fixtures/MAP_FIXTURE_ANALYSIS.md).
Three things in that fixture are load-bearing, and a map fails differently
depending on which one is missing:

* ``<mapsources><mapsource name="Tableau"/></mapsources>`` — without it the marks
  plot on blank white space with no coastline.
* ``semantic-role="[Geographical].[Latitude]"`` — without it the coordinates are
  ordinary measures and the sheet is a scatter plot.
* ``aggregation="Avg"`` — Tableau's default is Sum, and summed latitudes collapse
  every mark onto one meaningless point.

None of those produce an error dialog. They produce a plausible-looking wrong
answer, which is why they are asserted rather than left to a live screenshot.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tableau_public_authoring.compiler.fields import (
    GEO_LATITUDE,
    GEO_LONGITUDE,
    Field,
    geographic_role,
    infer_fields,
)
from tableau_public_authoring.compiler.workbook import MARK_CLASS, WorkbookCompiler
from tableau_public_authoring.models.spec import SUPPORTED_TEMPLATES, SpecError, parse_spec

FIXTURE_CSV = Path(__file__).resolve().parents[1] / "fixtures/data/ev_site_readiness.csv"


def _spec(**worksheet_overrides) -> dict:
    ws = {
        "name": "Site Map",
        "template": "map",
        "data_source": "sites",
        "detail": ["Site Name"],
    }
    ws.update(worksheet_overrides)
    return {
        "spec_version": "0.1",
        "workbook": {"name": "MapTest"},
        "data_sources": [{"id": "sites", "type": "csv", "path": str(FIXTURE_CSV)}],
        "worksheets": [ws],
        "output": {"directory": str(FIXTURE_CSV.parent)},
    }


DATA_DIR_REF = "Data/sites"


def _compile(**overrides) -> ET.Element:
    spec = parse_spec(_spec(**overrides))
    return WorkbookCompiler(spec).build(data_dir_ref=DATA_DIR_REF).getroot()


def _worksheet(root: ET.Element) -> ET.Element:
    return root.find(".//worksheet")


# --- geographic role inference ----------------------------------------------


def test_latitude_and_longitude_get_different_roles():
    """They were both mapped to '[Country].[Name]' before maps existed."""
    assert geographic_role("Latitude") == GEO_LATITUDE
    assert geographic_role("Longitude") == GEO_LONGITUDE
    assert GEO_LATITUDE != GEO_LONGITUDE


@pytest.mark.parametrize("name", ["lat", "LAT", " Latitude ", "latitude"])
def test_latitude_aliases_are_matched_case_and_space_insensitively(name):
    assert geographic_role(name) == GEO_LATITUDE


@pytest.mark.parametrize("name", ["long", "lon", "lng", "LONGITUDE"])
def test_longitude_aliases(name):
    assert geographic_role(name) == GEO_LONGITUDE


@pytest.mark.parametrize(
    "name", ["Longest Wait", "Latency", "Latest Review", "Longitudinal Study", "Platform"]
)
def test_geographic_roles_never_match_on_a_substring(name):
    """A substring rule would map 'Longest Wait' to longitude and plot the Atlantic."""
    assert geographic_role(name) is None


def test_inference_tags_coordinates_from_a_real_csv():
    fields = {f.name: f for f in infer_fields(FIXTURE_CSV)}
    assert fields["Latitude"].semantic_role == GEO_LATITUDE
    assert fields["Longitude"].semantic_role == GEO_LONGITUDE
    assert fields["Latitude"].is_coordinate
    assert not fields["Site Name"].is_geographic


def test_a_text_column_named_latitude_is_not_a_coordinate(tmp_path):
    """Tagging a text column as a coordinate yields a map that plots nothing."""
    csv = tmp_path / "text_lat.csv"
    csv.write_text("Site,Latitude\nA,unknown\nB,n/a\n")
    fields = {f.name: f for f in infer_fields(csv)}
    assert fields["Latitude"].datatype == "string"
    assert fields["Latitude"].semantic_role is None


def test_coordinates_default_to_average_not_sum():
    lat = Field(name="Latitude", datatype="real", role="measure", type="quantitative",
                ordinal=0, semantic_role=GEO_LATITUDE)
    plain = Field(name="Cost", datatype="real", role="measure", type="quantitative", ordinal=1)
    assert lat.default_aggregation == "Avg"
    assert plain.default_aggregation == "Sum"


# --- compiled structure -----------------------------------------------------


def test_map_is_an_advertised_template_with_a_mark_class():
    assert "map" in SUPPORTED_TEMPLATES
    assert MARK_CLASS["map"] == "Circle"


def test_background_map_is_requested():
    view = _worksheet(_compile()).find("table/view")
    src = view.find("mapsources/mapsource")
    assert src is not None, "no <mapsources>: marks would plot on blank white space"
    assert src.get("name") == "Tableau"


def test_mapsources_sits_between_datasources_and_dependencies():
    """Tableau's loader enforces a DTD content model and rejects misordered children."""
    view = _worksheet(_compile()).find("table/view")
    tags = [c.tag for c in view]
    assert tags.index("datasources") < tags.index("mapsources") < tags.index(
        "datasource-dependencies"
    )


def test_only_a_map_asks_for_a_background_map():
    spec = parse_spec(
        {
            "spec_version": "0.1",
            "workbook": {"name": "MapTest"},
            "data_sources": [{"id": "sites", "type": "csv", "path": str(FIXTURE_CSV)}],
            "worksheets": [
                {
                    "name": "Bars",
                    "template": "bar",
                    "data_source": "sites",
                    "rows": ["Site Name"],
                    "columns": [{"field": "Annual Sessions", "aggregation": "Sum"}],
                }
            ],
            "output": {"directory": str(FIXTURE_CSV.parent)},
        }
    )
    root = WorkbookCompiler(spec).build(data_dir_ref=DATA_DIR_REF).getroot()
    view = root.find(".//worksheet/table/view")
    assert view.find("mapsources") is None


def test_latitude_goes_on_rows_and_longitude_on_columns():
    """Swapping them plots the transpose of the world, with no error."""
    ws = _worksheet(_compile())
    assert ws.find("table/rows").text.endswith("[avg:Latitude:qk]")
    assert ws.find("table/cols").text.endswith("[avg:Longitude:qk]")


def test_coordinate_columns_carry_the_semantic_role_and_avg_aggregation():
    ws = _worksheet(_compile())
    cols = {
        c.get("name"): c for c in ws.findall("table/view/datasource-dependencies/column")
    }
    for name, role in (("[Latitude]", GEO_LATITUDE), ("[Longitude]", GEO_LONGITUDE)):
        assert cols[name].get("semantic-role") == role
        assert cols[name].get("aggregation") == "Avg", (
            f"{name} would be SUMmed, collapsing every mark onto one point"
        )


def test_the_datasource_declares_the_geographic_role_too():
    """Both the data source and the view declare columns; a map needs both tagged."""
    root = _compile()
    ds_cols = {c.get("name"): c for c in root.findall(".//datasources/datasource/column")}
    assert ds_cols["[Latitude]"].get("semantic-role") == GEO_LATITUDE
    assert ds_cols["[Longitude]"].get("aggregation") == "Avg"


def test_a_non_geographic_column_gets_neither_attribute():
    root = _compile()
    ds_cols = {c.get("name"): c for c in root.findall(".//datasources/datasource/column")}
    cost = ds_cols["[Estimated Cost]"]
    assert cost.get("semantic-role") is None
    assert cost.get("aggregation") is None


def test_map_fills_the_canvas_by_default():
    """A map at Standard fit is a postage stamp of coastline in the corner."""
    root = _compile()
    assert [z.get("type") for z in root.iter("zoom")] == ["entire-view"]


def test_detail_field_still_reaches_the_lod_shelf():
    enc = _worksheet(_compile()).find(".//encodings")
    assert [e.get("column") for e in enc.findall("lod")][0].endswith("[none:Site Name:nk]")


# --- validation -------------------------------------------------------------


def test_coordinates_are_inferred_when_not_specified():
    spec = parse_spec(_spec())
    ws = spec.worksheets[0]
    assert (ws.latitude.field, ws.longitude.field) == ("Latitude", "Longitude")
    assert ws.latitude.aggregation == "Avg"


def test_explicit_coordinates_win_over_inference():
    spec = parse_spec(_spec(latitude="Latitude", longitude="Longitude"))
    assert spec.worksheets[0].latitude.field == "Latitude"


def test_a_map_without_a_grouping_dimension_is_rejected():
    """One mark averaged from every row looks like a bug, so it is refused up front."""
    with pytest.raises(SpecError, match="at least one dimension"):
        parse_spec(_spec(detail=[]))


def test_color_alone_satisfies_the_grouping_requirement():
    spec = parse_spec(_spec(detail=[], color="Status"))
    assert spec.worksheets[0].color.field == "Status"


def test_a_measure_on_detail_does_not_satisfy_the_grouping_requirement():
    """Only a dimension subdivides marks; a measure on Detail aggregates."""
    with pytest.raises(SpecError, match="at least one dimension"):
        parse_spec(_spec(detail=[{"field": "Annual Sessions", "aggregation": "Sum"}]))


def test_summing_a_coordinate_is_rejected():
    with pytest.raises(SpecError, match="averaged, not aggregated"):
        parse_spec(_spec(latitude={"field": "Latitude", "aggregation": "Sum"}))


def test_a_text_coordinate_is_rejected():
    with pytest.raises(SpecError, match="must be\nnumeric|must be numeric"):
        parse_spec(_spec(latitude="Site Name"))


def test_the_same_column_cannot_be_both_axes():
    with pytest.raises(SpecError, match="two different coordinate columns"):
        parse_spec(_spec(latitude="Latitude", longitude="Latitude"))


def test_a_missing_coordinate_names_the_fix(tmp_path):
    csv = tmp_path / "nogeo.csv"
    csv.write_text("Site,Cost\nA,10\nB,20\n")
    spec = _spec()
    spec["data_sources"][0]["path"] = str(csv)
    spec["worksheets"][0]["detail"] = ["Site"]
    with pytest.raises(SpecError, match="needs a latitude field"):
        parse_spec(spec)


def test_latitude_is_rejected_on_a_non_map_template():
    """Silently ignoring it would produce a chart the caller did not ask for."""
    spec = _spec()
    spec["worksheets"][0].update(
        {
            "template": "bar",
            "rows": ["Site Name"],
            "columns": [{"field": "Annual Sessions", "aggregation": "Sum"}],
            "latitude": "Latitude",
        }
    )
    with pytest.raises(SpecError, match="only valid for the 'map' template"):
        parse_spec(spec)
