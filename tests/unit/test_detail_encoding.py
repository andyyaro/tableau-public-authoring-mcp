"""Detail (level-of-detail) encoding tests.

Detail exists because Color alone establishes a viz's level of detail. A scatter
plot with ``Status`` on Color and nothing else discrete draws one mark per
Status value — three marks for a twelve-row table — which was observed on a real
render, not reasoned about. Tableau's own Marks card solves this with a Detail
shelf; the compiler serialises it as ``<lod>`` inside ``<encodings>``.

The element name is taken from the reference workbook
(docs/fixtures/REFERENCE_WORKBOOK_ANALYSIS.md), whose heat-map sheets carry
``<lod column='[federated.…].[none:Site ID:nk]' />`` beside their ``<color>``
and ``<tooltip>`` children. Note the ``none:`` derivation: unlike a dimension on
Tooltip, which must be promoted to ``attr:`` so it does NOT change the level of
detail, a dimension on Detail keeps ``none:`` precisely because changing the
level of detail is its whole purpose. That asymmetry is what these tests pin
down.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tableau_public_authoring.compiler.workbook import WorkbookCompiler
from tableau_public_authoring.models.spec import SpecError, parse_spec

DATA_DIR_REF = "Data/d"


@pytest.fixture
def csv_file(tmp_path: Path) -> Path:
    """Twelve rows, three Status values, four sites per city.

    The row/Status ratio is the point: any level-of-detail bug shows up as a
    mark count of 3 rather than 12.
    """
    path = tmp_path / "sites.csv"
    lines = ["Site Name,City,Status,Score,Cost"]
    statuses = ("Ready", "Blocked", "Planned")
    cities = ("Arlington", "Reston", "Fairfax")
    for i in range(12):
        lines.append(f"Site {i:02d},{cities[i % 3]},{statuses[i % 3]},{i * 10 + 5},{i * 250 + 100}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def out_dir(tmp_path: Path) -> Path:
    p = tmp_path / "out"
    p.mkdir()
    return p


def scatter_spec(csv_file: Path, out_dir: Path, **worksheet_overrides) -> dict:
    """A scatter sheet with Status on Color — the shape that exposed the defect."""
    ws: dict = {
        "name": "Site Scatter",
        "template": "scatter",
        "data_source": "d",
        "rows": [{"field": "Score", "aggregation": "Sum"}],
        "columns": [{"field": "Cost", "aggregation": "Sum"}],
        "color": "Status",
    }
    ws.update(worksheet_overrides)
    return {
        "spec_version": "0.1",
        "workbook": {"name": "Detail Test", "description": "detail encoding"},
        "data_sources": [{"id": "d", "type": "csv", "path": str(csv_file)}],
        "worksheets": [ws],
        "output": {"directory": str(out_dir), "package_twbx": True},
    }


def compile_xml(spec_dict: dict) -> ET.Element:
    return ET.fromstring(
        WorkbookCompiler(parse_spec(spec_dict)).to_bytes(data_dir_ref=DATA_DIR_REF)
    )


def encodings_of(root: ET.Element, sheet: str = "Site Scatter") -> ET.Element:
    for ws in root.iter("worksheet"):
        if ws.get("name") == sheet:
            enc = ws.find(".//pane/encodings")
            assert enc is not None, f"worksheet {sheet!r} has no <encodings>"
            return enc
    raise AssertionError(f"worksheet {sheet!r} not found")


def column_instances(root: ET.Element, sheet: str = "Site Scatter") -> set[str]:
    for ws in root.iter("worksheet"):
        if ws.get("name") == sheet:
            return {ci.get("name") for ci in ws.iter("column-instance")}
    raise AssertionError(f"worksheet {sheet!r} not found")


# --- emitted XML ------------------------------------------------------------


def test_dimension_on_detail_uses_none_derivation(csv_file, out_dir):
    """A dimension on Detail must NOT get the Attribute promotion tooltips use."""
    root = compile_xml(scatter_spec(csv_file, out_dir, detail=["Site Name"]))
    lods = encodings_of(root).findall("lod")
    assert len(lods) == 1
    column = lods[0].get("column")
    assert column.endswith(".[none:Site Name:nk]"), column
    assert ":attr:" not in column and "[attr:" not in column
    assert column.startswith("[federated.")


def test_measure_on_detail_aggregates_normally(csv_file, out_dir):
    """A measure on Detail keeps whatever aggregation the spec names."""
    root = compile_xml(
        scatter_spec(csv_file, out_dir, detail=[{"field": "Score", "aggregation": "Sum"}])
    )
    lods = encodings_of(root).findall("lod")
    assert len(lods) == 1
    assert lods[0].get("column").endswith(".[sum:Score:qk]")


def test_multiple_detail_fields_all_emit(csv_file, out_dir):
    root = compile_xml(scatter_spec(csv_file, out_dir, detail=["Site Name", "City"]))
    columns = [lod.get("column") for lod in encodings_of(root).findall("lod")]
    assert len(columns) == 2
    assert columns[0].endswith(".[none:Site Name:nk]")
    assert columns[1].endswith(".[none:City:nk]")


def test_lod_lives_inside_encodings_only(csv_file, out_dir):
    """<lod> is a Marks-card encoding; it must not leak into any other parent."""
    root = compile_xml(scatter_spec(csv_file, out_dir, detail=["Site Name", "City"]))
    parents_with_lod = {
        parent.tag for parent in root.iter() for child in parent if child.tag == "lod"
    }
    assert parents_with_lod == {"encodings"}
    assert len(list(root.iter("lod"))) == 2


def test_no_detail_emits_no_lod(csv_file, out_dir):
    root = compile_xml(scatter_spec(csv_file, out_dir))
    assert list(root.iter("lod")) == []


def test_detail_field_gets_column_and_column_instance(csv_file, out_dir):
    """Detail must go through the same use() path as every other encoding."""
    root = compile_xml(scatter_spec(csv_file, out_dir, detail=["Site Name"]))
    sheet = next(ws for ws in root.iter("worksheet") if ws.get("name") == "Site Scatter")
    deps = sheet.find(".//datasource-dependencies")
    assert deps is not None

    declared = {c.get("name"): c for c in deps.findall("column")}
    assert "[Site Name]" in declared
    assert declared["[Site Name]"].get("role") == "dimension"
    assert declared["[Site Name]"].get("type") == "nominal"

    instances = {ci.get("name"): ci for ci in deps.findall("column-instance")}
    assert "[none:Site Name:nk]" in instances
    inst = instances["[none:Site Name:nk]"]
    assert inst.get("derivation") == "None"
    assert inst.get("column") == "[Site Name]"
    assert inst.get("type") == "nominal"

    # The <lod> reference resolves against that declaration.
    lod_column = encodings_of(root).find("lod").get("column")
    assert lod_column.endswith(".[none:Site Name:nk]")


def test_detail_raises_the_level_of_detail(csv_file, out_dir):
    """The defect this feature fixes, expressed structurally.

    Without Detail the scatter sheet's only discrete field is Status, so Tableau
    groups the 12 rows into 3 marks. Adding ``Site Name`` on Detail introduces a
    second grouping key that is unique per row, so the same query returns 12
    marks. Structurally that is one additional distinct ``column-instance``
    carrying the None derivation, which is exactly what is asserted here.
    """
    without = compile_xml(scatter_spec(csv_file, out_dir))
    with_detail = compile_xml(scatter_spec(csv_file, out_dir, detail=["Site Name"]))

    before = column_instances(without)
    after = column_instances(with_detail)

    assert len(after) > len(before)
    assert after - before == {"[none:Site Name:nk]"}
    # Color alone was the sole grouping field before; now there are two.
    grouping_before = {i for i in before if i.startswith("[none:")}
    grouping_after = {i for i in after if i.startswith("[none:")}
    assert grouping_before == {"[none:Status:nk]"}
    assert grouping_after == {"[none:Status:nk]", "[none:Site Name:nk]"}


def test_detail_and_tooltip_derivations_differ(csv_file, out_dir):
    """Same dimension on both shelves: none: on Detail, attr: on Tooltip."""
    root = compile_xml(
        scatter_spec(csv_file, out_dir, detail=["Site Name"], tooltips=["Site Name"])
    )
    enc = encodings_of(root)
    assert enc.find("lod").get("column").endswith(".[none:Site Name:nk]")
    assert enc.find("tooltip").get("column").endswith(".[attr:Site Name:nk]")


def test_detail_is_deterministic(csv_file, out_dir):
    """Byte-identical output for the same spec (§13)."""
    spec_dict = scatter_spec(csv_file, out_dir, detail=["Site Name", "City"])
    first = WorkbookCompiler(parse_spec(spec_dict)).to_bytes(data_dir_ref=DATA_DIR_REF)
    second = WorkbookCompiler(parse_spec(spec_dict)).to_bytes(data_dir_ref=DATA_DIR_REF)
    assert first == second
    assert first.count(b"<lod ") == 2


# --- layer 1 validation -----------------------------------------------------


def test_unknown_detail_field_rejected(csv_file, out_dir):
    with pytest.raises(SpecError) as excinfo:
        parse_spec(scatter_spec(csv_file, out_dir, detail=["Nope"]))
    message = str(excinfo.value)
    assert "worksheets[0].detail" in message
    assert "'Nope'" in message
    assert "does not exist" in message
    # actionable: it names the data source and lists what is available
    assert "'d'" in message
    assert "Site Name" in message


def test_duplicate_detail_field_rejected(csv_file, out_dir):
    with pytest.raises(SpecError) as excinfo:
        parse_spec(scatter_spec(csv_file, out_dir, detail=["City", "City"]))
    message = str(excinfo.value)
    assert "worksheets[0].detail" in message
    assert "'City'" in message
    assert "more than once" in message


def test_duplicate_detail_field_rejected_across_forms(csv_file, out_dir):
    """The bare-name and object forms of the same field are still duplicates."""
    with pytest.raises(SpecError, match="more than once"):
        parse_spec(
            scatter_spec(
                csv_file, out_dir, detail=["City", {"field": "City", "aggregation": "None"}]
            )
        )


@pytest.mark.parametrize("value", ["City", {"field": "City"}, 7, True])
def test_non_array_detail_rejected(csv_file, out_dir, value):
    with pytest.raises(SpecError, match="detail must be an array"):
        parse_spec(scatter_spec(csv_file, out_dir, detail=value))


def test_unknown_key_inside_detail_ref_rejected(csv_file, out_dir):
    with pytest.raises(SpecError, match="unknown keys"):
        parse_spec(scatter_spec(csv_file, out_dir, detail=[{"field": "City", "shelf": "detail"}]))


def test_unsupported_aggregation_on_detail_rejected(csv_file, out_dir):
    with pytest.raises(SpecError, match="unsupported aggregation"):
        parse_spec(
            scatter_spec(csv_file, out_dir, detail=[{"field": "Score", "aggregation": "Med"}])
        )


def test_detail_defaults_to_empty(csv_file, out_dir):
    spec = parse_spec(scatter_spec(csv_file, out_dir))
    assert spec.worksheets[0].detail == []


def test_detail_parsed_in_order(csv_file, out_dir):
    spec = parse_spec(scatter_spec(csv_file, out_dir, detail=["Site Name", "City"]))
    detail = spec.worksheets[0].detail
    assert [(r.field, r.aggregation) for r in detail] == [
        ("Site Name", "None"),
        ("City", "None"),
    ]
