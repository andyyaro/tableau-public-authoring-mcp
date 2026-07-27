"""Layer 1 (spec) and layer 2 (generated file) validation tests."""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile

import pytest

from tableau_public_authoring.compiler.build import build_workbook
from tableau_public_authoring.models.spec import SpecError, parse_spec

from .conftest_helpers import make_spec, write_csv


@pytest.fixture
def csv_file(tmp_path):
    return write_csv(tmp_path / "d.csv", rows=5)


@pytest.fixture
def out_dir(tmp_path):
    p = tmp_path / "out"
    p.mkdir()
    return p


def test_valid_minimal_spec(csv_file, out_dir):
    spec = parse_spec(make_spec(csv_file, out_dir))
    assert spec.name == "Test Workbook"
    assert len(spec.worksheets) == 1
    assert {f.name for f in spec.data_sources[0].fields} == {"Site", "Score", "Status"}


def test_field_types_are_inferred(csv_file, out_dir):
    spec = parse_spec(make_spec(csv_file, out_dir))
    fields = {f.name: f for f in spec.data_sources[0].fields}
    assert fields["Score"].datatype == "integer"
    assert fields["Score"].role == "measure"
    assert fields["Site"].datatype == "string"
    assert fields["Site"].role == "dimension"


def test_unknown_top_level_key_rejected(csv_file, out_dir):
    s = make_spec(csv_file, out_dir)
    s["surprise"] = 1
    with pytest.raises(SpecError, match="unknown top-level keys"):
        parse_spec(s)


def test_unknown_worksheet_key_rejected(csv_file, out_dir):
    s = make_spec(csv_file, out_dir)
    s["worksheets"][0]["bogus"] = True
    with pytest.raises(SpecError, match="unknown keys"):
        parse_spec(s)


def test_invalid_chart_type_rejected(csv_file, out_dir):
    s = make_spec(csv_file, out_dir)
    s["worksheets"][0]["template"] = "pie"
    with pytest.raises(SpecError, match="unsupported template"):
        parse_spec(s)


def test_missing_csv_rejected(tmp_path, out_dir):
    s = make_spec(tmp_path / "absent.csv", out_dir)
    with pytest.raises(Exception, match="does not exist"):
        parse_spec(s)


def test_duplicate_worksheet_name_rejected(csv_file, out_dir):
    s = make_spec(csv_file, out_dir)
    s["worksheets"].append(dict(s["worksheets"][0]))
    with pytest.raises(SpecError, match="duplicate worksheet name"):
        parse_spec(s)


def test_missing_field_reference_rejected(csv_file, out_dir):
    s = make_spec(csv_file, out_dir)
    s["worksheets"][0]["rows"] = ["NoSuchField"]
    with pytest.raises(SpecError, match="does not exist in data source"):
        parse_spec(s)


def test_duplicate_data_source_id_rejected(csv_file, out_dir):
    s = make_spec(csv_file, out_dir)
    s["data_sources"].append(dict(s["data_sources"][0]))
    with pytest.raises(SpecError, match="duplicate data source id"):
        parse_spec(s)


def test_malformed_dashboard_rejected_with_clear_message(csv_file, out_dir):
    """Dashboards are parsed now (EXPERIMENTAL), but a malformed one still fails loudly.

    This test previously asserted that *any* ``dashboards`` entry was rejected with
    "dashboards are not supported in v0.1". That rejection no longer exists — see
    tests/unit/test_dashboards.py for the full dashboard contract. A dashboard with
    no worksheets is still an error, so the same malformed input is used here.
    """
    s = make_spec(csv_file, out_dir)
    s["dashboards"] = [{"name": "D"}]
    with pytest.raises(SpecError, match="worksheets must be a non-empty array"):
        parse_spec(s)


def test_empty_dashboards_array_is_accepted(csv_file, out_dir):
    s = make_spec(csv_file, out_dir)
    s["dashboards"] = []
    assert parse_spec(s).dashboards == []


def test_bad_aggregation_rejected(csv_file, out_dir):
    s = make_spec(csv_file, out_dir)
    s["worksheets"][0]["columns"] = [{"field": "Score", "aggregation": "Median"}]
    with pytest.raises(SpecError, match="unsupported aggregation"):
        parse_spec(s)


def test_scatter_requires_aggregated_measures(csv_file, out_dir):
    s = make_spec(csv_file, out_dir)
    s["worksheets"][0]["template"] = "scatter"
    s["worksheets"][0]["rows"] = ["Site"]
    with pytest.raises(SpecError, match="needs aggregated measures"):
        parse_spec(s)


def test_bar_requires_rows_and_columns(csv_file, out_dir):
    s = make_spec(csv_file, out_dir)
    s["worksheets"][0]["columns"] = []
    with pytest.raises(SpecError, match="requires at least one 'columns'"):
        parse_spec(s)


def test_calculated_field_name_collision_rejected(csv_file, out_dir):
    s = make_spec(csv_file, out_dir)
    s["calculated_fields"] = [
        {"name": "Score", "data_source": "d", "formula": "1", "datatype": "integer"}
    ]
    with pytest.raises(SpecError, match="collides with an existing column"):
        parse_spec(s)


# --- layer 2: generated file ------------------------------------------------


def test_build_produces_valid_package(csv_file, out_dir):
    r = build_workbook(make_spec(csv_file, out_dir))
    assert r.twb_path.exists() and r.twbx_path.exists()
    root = ET.parse(r.twb_path).getroot()
    assert root.tag == "workbook"
    assert root.get("version") == "18.1"
    with zipfile.ZipFile(r.twbx_path) as zf:
        names = zf.namelist()
    assert any(n.endswith(".twb") for n in names)
    assert any(n.endswith(".hyper") for n in names), "Tableau Public requires an extract"
    assert any(n.endswith(".csv") for n in names)


def test_worksheet_has_shelves_and_marks(csv_file, out_dir):
    r = build_workbook(make_spec(csv_file, out_dir))
    root = ET.parse(r.twb_path).getroot()
    ws = root.find("worksheets")[0]
    assert ws.find(".//mark").get("class") == "Bar"
    assert ws.find(".//rows").text
    assert ws.find(".//cols").text


def test_table_element_order_matches_tableau_content_model(csv_file, out_dir):
    """Tableau's loader requires (view, style, panes, rows, cols)."""
    r = build_workbook(make_spec(csv_file, out_dir))
    root = ET.parse(r.twb_path).getroot()
    table = root.find("worksheets")[0].find("table")
    tags = [c.tag for c in table]
    assert tags == ["view", "style", "panes", "rows", "cols"], tags


def test_extract_has_only_declared_attributes(csv_file, out_dir):
    """object-id / user-specific are rejected by the loader's DTD."""
    r = build_workbook(make_spec(csv_file, out_dir))
    root = ET.parse(r.twb_path).getroot()
    ext = root.find("datasources")[0].find("extract")
    assert set(ext.attrib) == {"count", "enabled", "units"}


def test_layout_has_required_percentage_attributes(csv_file, out_dir):
    r = build_workbook(make_spec(csv_file, out_dir))
    root = ET.parse(r.twb_path).getroot()
    layout = root.find("datasources")[0].find("layout")
    assert "dim-percentage" in layout.attrib
    assert "measure-percentage" in layout.attrib


def test_tooltip_dimension_uses_attr_derivation(csv_file, out_dir):
    """derivation='None' on a tooltip dimension yields a red pill / blank viz."""
    s = make_spec(csv_file, out_dir)
    s["worksheets"][0]["tooltips"] = ["Status"]
    r = build_workbook(s)
    root = ET.parse(r.twb_path).getroot()
    instances = [ci.get("name") for ci in root.iter("column-instance")]
    assert any(n.startswith("[attr:Status") for n in instances), instances


def test_twb_generation_is_byte_deterministic(csv_file, out_dir):
    """The compiled .twb must be byte-identical for an identical spec.

    This is the determinism guarantee this project actually makes: generated IDs
    are derived from a SHA-256 of stable inputs, so nothing varies run to run.
    """
    a = build_workbook(make_spec(csv_file, out_dir))
    first = a.twb_path.read_bytes()
    b = build_workbook(make_spec(csv_file, out_dir))
    assert first == b.twb_path.read_bytes()


def test_twbx_hash_is_not_guaranteed_stable(csv_file, out_dir):
    """Documents a real limitation: .twbx bytes are NOT reproducible.

    ZIP entries use a fixed timestamp and fixed ordering, but the embedded
    ``.hyper`` extract is produced by Tableau's Hyper engine, which writes
    non-deterministic internal state. The .twb inside the package is stable
    (see the test above); the package digest is not. Recorded in
    docs/LIMITATIONS.md rather than papered over.
    """
    a = build_workbook(make_spec(csv_file, out_dir))
    # Snapshot before the second build: both write to the same path, so comparing
    # the two BuildResults afterwards would compare the file to itself.
    first_twb = a.twb_path.read_bytes()
    first_sha = a.sha256
    b = build_workbook(make_spec(csv_file, out_dir))

    # The .twb IS stable. That half is a guarantee and is asserted as one.
    assert first_twb == b.twb_path.read_bytes()

    # The .twbx is not, because Hyper writes non-deterministic internal state.
    # This is recorded, not asserted: an equal digest would mean Hyper happened to
    # be stable on this run, which is allowed. Asserting inequality would make the
    # suite fail on the *better* outcome. What must never happen is code or docs
    # claiming the package digest is reproducible -- see the twbx.py docstring.
    if first_sha == b.sha256:
        pytest.skip("Hyper produced identical bytes on this run; that is permitted, not promised")


def test_calculated_field_appears_in_output(csv_file, out_dir):
    s = make_spec(csv_file, out_dir)
    s["calculated_fields"] = [
        {
            "name": "Band",
            "data_source": "d",
            "datatype": "string",
            "formula": 'IF [Score] > 10 THEN "hi" ELSE "lo" END',
        }
    ]
    s["worksheets"][0]["color"] = "Band"
    r = build_workbook(s)
    root = ET.parse(r.twb_path).getroot()
    formulas = [c.get("formula") for c in root.iter("calculation")]
    assert any("THEN" in (f or "") for f in formulas)
