"""Regression guards for the Tableau loader's DTD content model.

Every constraint here was discovered the hard way - by generating a workbook,
opening it in Tableau Public 2026.2.0, and reading the error dialog. Each one
produced a file that Tableau REFUSED TO LOAD. They are cheap to re-break by
accident (they are all "just" an attribute or an element position), and the only
other way to catch them is a live GUI test, so they are pinned here.

Tableau's own writer emits `object-graph` and `extract/@object-id`; its *loader*
rejects both. The writer is more permissive than the reader, so "Tableau does it"
is not evidence that we may.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile

import pytest

from tableau_public_authoring.compiler.build import build_workbook

from .conftest_helpers import make_spec, write_csv


@pytest.fixture
def built(tmp_path):
    """A workbook exercising filters, tooltips, calculated fields and titles."""
    csv = write_csv(tmp_path / "d.csv", rows=6)
    out = tmp_path / "out"
    out.mkdir()
    spec = make_spec(csv, out, name="DTD Regression")
    spec["calculated_fields"] = [
        {
            "name": "Band",
            "data_source": "d",
            "datatype": "string",
            "formula": 'IF [Score] > 10 THEN "hi" ELSE "lo" END',
        }
    ]
    ws = spec["worksheets"][0]
    ws["color"] = "Band"
    ws["tooltips"] = ["Status"]
    ws["filters"] = ["Status"]
    ws["title"] = "Regression"
    ws["subtitle"] = "guards"
    result = build_workbook(spec)
    return result, result.twb_path.read_text(encoding="utf-8")


# --- the five load-blocking DTD violations ---------------------------------


def test_layout_declares_required_percentages(built):
    """Omitting these produced: missing required attribute 'dim-percentage'."""
    _, xml = built
    for layout in ET.fromstring(xml).iter("layout"):
        assert "dim-percentage" in layout.attrib
        assert "measure-percentage" in layout.attrib


def test_object_graph_is_never_emitted(built):
    """Produced: no declaration found for element 'object-graph'."""
    _, xml = built
    assert "<object-graph" not in xml
    assert not list(ET.fromstring(xml).iter("object-graph"))


def test_extract_carries_only_declared_attributes(built):
    """Produced: attribute 'object-id' is not declared for element 'extract'."""
    _, xml = built
    extracts = list(ET.fromstring(xml).iter("extract"))
    assert extracts, "Tableau Public requires an extract-backed data source"
    for ext in extracts:
        assert set(ext.attrib) == {"count", "enabled", "units"}, ext.attrib


def test_filter_and_slices_live_inside_view_not_table(built):
    """Produced: element 'filter' is not allowed for content model (view,style,...)."""
    root = ET.fromstring(built[1])
    for ws in root.find("worksheets"):
        table = ws.find("table")
        assert table.find("filter") is None, "<filter> must not be a direct child of <table>"
        assert table.find("slices") is None, "<slices> must not be a direct child of <table>"
        view = table.find("view")
        assert view.find("filter") is not None, "the filter should be inside <view>"
        assert view.find("slices") is not None


def test_table_child_order_matches_content_model(built):
    """Produced: element 'panes' is not allowed for content model (view,style,panes,...).

    The loader requires <style> between <view> and <panes>.
    """
    root = ET.fromstring(built[1])
    for ws in root.find("worksheets"):
        tags = [c.tag for c in ws.find("table")]
        assert tags[:3] == ["view", "style", "panes"], tags
        assert tags == ["view", "style", "panes", "rows", "cols"], tags


# --- the semantic failure that loaded but rendered blank --------------------


def test_tooltip_dimensions_use_attr_derivation(built):
    """derivation='None' on a tooltip dimension gave a red pill and a blank canvas.

    Scoped to the tooltip ENCODING specifically. The same field used as a filter
    correctly keeps the None derivation - that is how Tableau's own files express a
    categorical filter - so a workbook-wide ban on ``[none:Field:nk]`` would be wrong.
    """
    root = ET.fromstring(built[1])
    checked = 0
    for ws in root.find("worksheets"):
        for enc in ws.iter("encodings"):
            for tip in enc.findall("tooltip"):
                col = tip.get("column") or ""
                checked += 1
                assert ":" in col, col
                derivation = col.rsplit(".[", 1)[-1].split(":", 1)[0]
                assert derivation in ("attr", "sum", "avg", "min", "max", "cnt", "ctd"), (
                    f"tooltip references {col!r} with derivation {derivation!r}; a dimension "
                    f"on Tooltip must use attr: or Tableau renders the pill red and the "
                    f"canvas blank"
                )
    assert checked, "fixture should place at least one field on Tooltip"


# --- Tableau Public platform constraints ------------------------------------


def test_every_data_source_is_extract_backed(built):
    """Tableau Public rejects live connections with Error Code 3C242D89."""
    result, _ = built
    with zipfile.ZipFile(result.twbx_path) as zf:
        names = zf.namelist()
    assert any(n.endswith(".hyper") for n in names), names


def test_worksheet_has_fields_on_a_shelf(built):
    """Tableau disables 'Save to Tableau Public' for a viz with no fields."""
    root = ET.fromstring(built[1])
    for ws in root.find("worksheets"):
        rows = ws.find(".//rows")
        cols = ws.find(".//cols")
        assert (rows is not None and rows.text) or (cols is not None and cols.text)


def test_no_repository_location_or_simple_id(built):
    """These identify a *published* workbook and must never be generated."""
    _, xml = built
    assert "<repository-location" not in xml
    assert "<simple-id" not in xml


def test_generated_xml_has_no_absolute_paths(built):
    """A published workbook is world-readable; machine paths must not leak."""
    _, xml = built
    assert not re.search(r"/Users/[^/\"'<>]+", xml)
    assert "/private/tmp/" not in xml
    assert "/var/folders/" not in xml


# --- pane child order and canvas fit ---------------------------------------


def test_pane_style_is_the_last_child(built):
    """Produced: element 'encodings' is not allowed for content model.

    The loader's pane content model is
        (view, mark, mark-sizing?, encodings?, label-data*, dropline?,
         trendline?, reference-line, customized-tooltip, customized-label, style)
    so <style> must come AFTER <encodings>, not before it.
    """
    root = ET.fromstring(built[1])
    for ws in root.find("worksheets"):
        for pane in ws.find("table").find("panes"):
            tags = [c.tag for c in pane]
            assert tags[0] == "view" and tags[1] == "mark", tags
            if "style" in tags:
                assert tags[-1] == "style", tags
            if "encodings" in tags and "style" in tags:
                assert tags.index("encodings") < tags.index("style"), tags


def test_worksheet_declares_a_canvas_fit(built):
    """Without <viewpoint><zoom>, Tableau uses "Standard" and draws a small viz
    tucked into the top-left corner instead of filling the view."""
    root = ET.fromstring(built[1])
    windows = root.find("windows")
    worksheet_windows = [w for w in windows if w.get("class") == "worksheet"]
    assert worksheet_windows
    for win in worksheet_windows:
        zoom = win.find("./viewpoint/zoom")
        assert zoom is not None, f"{win.get('name')!r} has no <viewpoint><zoom>"
        assert zoom.get("type") in ("fit-width", "fit-height", "entire-view")


def test_label_pill_switches_mark_labels_on(tmp_path):
    """A field on Label draws nothing unless mark-labels-show is set.

    Builds its own workbook: the shared ``built`` fixture deliberately has no
    label, and must NOT emit the style rule.
    """
    csv = write_csv(tmp_path / "d.csv", rows=4)
    out = tmp_path / "out"
    out.mkdir()
    spec = make_spec(csv, out, name="Label Check")
    spec["worksheets"][0]["label"] = {"field": "Score", "aggregation": "Sum"}
    result = build_workbook(spec)
    xml = result.twb_path.read_text(encoding="utf-8")
    shown = [
        f.get("value")
        for f in ET.fromstring(xml).iter("format")
        if f.get("attr") == "mark-labels-show"
    ]
    assert shown == ["true"], shown


def test_unlabelled_sheet_does_not_force_mark_labels(built):
    """The style rule is only emitted where it is meaningful."""
    root = ET.fromstring(built[1])
    assert not [f for f in root.iter("format") if f.get("attr") == "mark-labels-show"]
