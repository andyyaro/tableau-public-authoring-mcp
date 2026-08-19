"""Dashboard generation tests (layer 1 spec, layer 2 structure, compiled XML).

EXPERIMENTAL / UNVERIFIED. These tests prove the compiler emits the structure
documented in docs/fixtures/DASHBOARD_FIXTURE_ANALYSIS.md. They cannot prove
Tableau Public 2026.2.0 opens it - no fixture written by that build was
available and no generated dashboard has been loaded by hand.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from tableau_public_authoring.compiler.build import build_workbook
from tableau_public_authoring.compiler.workbook import (
    ZONE_GRID,
    WorkbookCompiler,
    _tile,
    _ZoneIds,
)
from tableau_public_authoring.models.spec import (
    Dashboard,
    DashboardZone,
    SpecError,
    parse_spec,
)

from .conftest_helpers import make_spec, write_csv


@pytest.fixture
def csv_file(tmp_path):
    return write_csv(tmp_path / "d.csv", rows=5)


@pytest.fixture
def out_dir(tmp_path):
    p = tmp_path / "out"
    p.mkdir()
    return p


def two_sheet_spec(csv_file, out_dir, **dash_overrides) -> dict:
    """A spec with two worksheets and one dashboard placing both."""
    s = make_spec(csv_file, out_dir)
    s["worksheets"].append(
        {
            "name": "Sheet Two",
            "template": "text_table",
            "data_source": "d",
            "rows": ["Status"],
            "columns": [{"field": "Score", "aggregation": "Sum"}],
        }
    )
    dash = {"name": "Overview", "worksheets": ["Sheet One", "Sheet Two"]}
    dash.update(dash_overrides)
    s["dashboards"] = [dash]
    return s


# --- layer 1: spec parsing --------------------------------------------------


def test_valid_minimal_dashboard(csv_file, out_dir):
    spec = parse_spec(two_sheet_spec(csv_file, out_dir))
    assert len(spec.dashboards) == 1
    dash = spec.dashboards[0]
    assert dash.name == "Overview"
    assert dash.worksheet_names() == ["Sheet One", "Sheet Two"]
    # documented defaults
    assert dash.direction == "vertical"
    assert dash.sizing_mode == "fixed"
    assert (dash.width, dash.height) == (1200, 800)
    assert dash.title is None
    assert all(z.show_title for z in dash.worksheets)


def test_dashboard_zone_object_form(csv_file, out_dir):
    s = two_sheet_spec(csv_file, out_dir)
    s["dashboards"][0]["worksheets"] = [
        "Sheet One",
        {"worksheet": "Sheet Two", "show_title": False},
    ]
    dash = parse_spec(s).dashboards[0]
    assert [z.show_title for z in dash.worksheets] == [True, False]


def test_unknown_dashboard_key_rejected(csv_file, out_dir):
    s = two_sheet_spec(csv_file, out_dir, layout="grid")
    with pytest.raises(SpecError, match=r"dashboards\[0\]: unknown keys \['layout'\]"):
        parse_spec(s)


def test_unknown_dashboard_zone_key_rejected(csv_file, out_dir):
    s = two_sheet_spec(csv_file, out_dir)
    s["dashboards"][0]["worksheets"] = [{"worksheet": "Sheet One", "floating": True}]
    with pytest.raises(SpecError, match="unknown keys"):
        parse_spec(s)


def test_duplicate_dashboard_name_rejected(csv_file, out_dir):
    s = two_sheet_spec(csv_file, out_dir)
    s["dashboards"].append(
        {"name": "Overview", "worksheets": ["Sheet Two"]},
    )
    with pytest.raises(SpecError, match="duplicate dashboard name"):
        parse_spec(s)


def test_dashboard_name_colliding_with_worksheet_rejected(csv_file, out_dir):
    s = two_sheet_spec(csv_file, out_dir, name="Sheet One")
    with pytest.raises(SpecError, match="collides with a worksheet name"):
        parse_spec(s)


def test_unknown_worksheet_reference_rejected(csv_file, out_dir):
    s = two_sheet_spec(csv_file, out_dir)
    s["dashboards"][0]["worksheets"] = ["Sheet One", "Sheet Twoo"]
    with pytest.raises(SpecError, match=r"worksheet 'Sheet Twoo' does not exist"):
        parse_spec(s)


def test_same_worksheet_placed_twice_rejected(csv_file, out_dir):
    s = two_sheet_spec(csv_file, out_dir)
    s["dashboards"][0]["worksheets"] = ["Sheet One", "Sheet One"]
    with pytest.raises(SpecError, match="already placed on dashboard"):
        parse_spec(s)


def test_empty_worksheet_list_rejected(csv_file, out_dir):
    s = two_sheet_spec(csv_file, out_dir)
    s["dashboards"][0]["worksheets"] = []
    with pytest.raises(SpecError, match="must be a non-empty array"):
        parse_spec(s)


def test_bad_direction_rejected(csv_file, out_dir):
    s = two_sheet_spec(csv_file, out_dir, direction="diagonal")
    with pytest.raises(SpecError, match="unsupported direction"):
        parse_spec(s)


def test_bad_sizing_mode_rejected(csv_file, out_dir):
    """'vscroll' and 'Range' were never observed for a whole dashboard."""
    s = two_sheet_spec(csv_file, out_dir, sizing_mode="vscroll")
    with pytest.raises(SpecError, match="unsupported sizing_mode"):
        parse_spec(s)


@pytest.mark.parametrize("value", [0, 42, 99999, -800])
def test_out_of_range_size_rejected(csv_file, out_dir, value):
    s = two_sheet_spec(csv_file, out_dir, width=value)
    with pytest.raises(SpecError, match="must be between 100 and 10000 pixels"):
        parse_spec(s)


def test_non_integer_size_rejected(csv_file, out_dir):
    s = two_sheet_spec(csv_file, out_dir, height="800")
    with pytest.raises(SpecError, match="must be an integer number of pixels"):
        parse_spec(s)


def test_size_with_automatic_sizing_rejected(csv_file, out_dir):
    s = two_sheet_spec(csv_file, out_dir, sizing_mode="automatic", width=1200)
    with pytest.raises(SpecError, match="cannot be set when sizing_mode is 'automatic'"):
        parse_spec(s)


def test_no_dashboards_key_is_still_valid(csv_file, out_dir):
    spec = parse_spec(make_spec(csv_file, out_dir))
    assert spec.dashboards == []


# --- the tiling helper ------------------------------------------------------


@pytest.mark.parametrize("count", list(range(1, 8)))
def test_tile_spans_are_contiguous_and_exact(count):
    """Siblings must tile the parent exactly: no gap, no overlap (§4.1)."""
    spans = _tile(count, 94000, 6000)
    assert len(spans) == count
    assert spans[0][0] == 6000
    for (start, size), (next_start, _) in zip(spans, spans[1:], strict=False):
        assert start + size == next_start
    assert sum(size for _, size in spans) == 94000
    assert spans[-1][0] + spans[-1][1] == 100000


def test_zone_ids_are_small_sequential_integers():
    ids = _ZoneIds()
    assert [ids.take() for _ in range(4)] == ["1", "2", "3", "4"]


# --- layer 2 / compiled XML -------------------------------------------------


def build_root(spec: dict) -> ET.Element:
    return ET.parse(build_workbook(spec).twb_path).getroot()


def test_dashboards_element_sits_between_worksheets_and_windows(csv_file, out_dir):
    root = build_root(two_sheet_spec(csv_file, out_dir))
    tags = [c.tag for c in root]
    assert tags.index("worksheets") < tags.index("dashboards") < tags.index("windows")
    assert root.find("dashboards").attrib == {}


def test_no_dashboards_element_when_none_requested(csv_file, out_dir):
    root = build_root(make_spec(csv_file, out_dir))
    assert root.find("dashboards") is None


def test_dashboard_child_order_matches_content_model(csv_file, out_dir):
    """Tableau's loader enforces layout-options?, style, size, zones."""
    root = build_root(two_sheet_spec(csv_file, out_dir, title="Readiness"))
    dash = root.find("dashboards")[0]
    assert [c.tag for c in dash] == ["layout-options", "style", "size", "zones"]

    untitled = build_root(two_sheet_spec(csv_file, out_dir))
    assert [c.tag for c in untitled.find("dashboards")[0]] == ["style", "size", "zones"]


def test_dashboard_size_is_fixed_pixels(csv_file, out_dir):
    root = build_root(two_sheet_spec(csv_file, out_dir, width=1400, height=900))
    size = root.find("dashboards")[0].find("size")
    assert size.attrib == {
        "maxheight": "900",
        "maxwidth": "1400",
        "minheight": "900",
        "minwidth": "1400",
        "sizing-mode": "fixed",
    }


def test_automatic_sizing_has_no_bounds(csv_file, out_dir):
    root = build_root(two_sheet_spec(csv_file, out_dir, sizing_mode="automatic"))
    assert root.find("dashboards")[0].find("size").attrib == {"sizing-mode": "automatic"}


def test_root_zone_is_full_grid_layout_basic(csv_file, out_dir):
    root = build_root(two_sheet_spec(csv_file, out_dir))
    zones = root.find("dashboards")[0].find("zones")
    assert len(zones) == 1
    rz = zones[0]
    assert rz.get("type") == "layout-basic"
    assert (rz.get("x"), rz.get("y"), rz.get("w"), rz.get("h")) == (
        "0",
        "0",
        str(ZONE_GRID),
        str(ZONE_GRID),
    )
    # zone-style is always the LAST child of a zone
    assert [c.tag for c in rz] == ["zone", "zone-style"]


@pytest.mark.parametrize(("direction", "param"), [("vertical", "vert"), ("horizontal", "horz")])
def test_layout_flow_direction(csv_file, out_dir, direction, param):
    root = build_root(two_sheet_spec(csv_file, out_dir, direction=direction))
    flows = [z for z in root.iter("zone") if z.get("type") == "layout-flow"]
    assert [f.get("param") for f in flows] == [param]


def test_worksheet_zone_has_name_and_no_type(csv_file, out_dir):
    """The only link to a worksheet is a bare name string with no @type (§4.4)."""
    root = build_root(two_sheet_spec(csv_file, out_dir))
    ws_zones = [z for z in root.iter("zone") if z.get("type") is None]
    assert [z.get("name") for z in ws_zones] == ["Sheet One", "Sheet Two"]
    for z in ws_zones:
        assert "type" not in z.attrib
        assert "worksheet" not in z.attrib


def test_show_title_false_is_emitted(csv_file, out_dir):
    s = two_sheet_spec(csv_file, out_dir)
    s["dashboards"][0]["worksheets"] = [
        "Sheet One",
        {"worksheet": "Sheet Two", "show_title": False},
    ]
    root = build_root(s)
    zones = {z.get("name"): z for z in root.iter("zone") if z.get("type") is None}
    assert "show-title" not in zones["Sheet One"].attrib
    assert zones["Sheet Two"].get("show-title") == "false"


def test_zone_ids_are_integers_and_unique(csv_file, out_dir):
    root = build_root(two_sheet_spec(csv_file, out_dir, title="T"))
    ids = [z.get("id") for z in root.find("dashboards")[0].iter("zone")]
    assert all(i.isdigit() for i in ids), ids
    assert len(set(ids)) == len(ids)
    # small sequential integers, NOT the 28-char base-36 ids from compiler/ids.py
    assert sorted(int(i) for i in ids) == list(range(1, len(ids) + 1))


@pytest.mark.parametrize("direction", ["vertical", "horizontal"])
@pytest.mark.parametrize("title", [None, "Site Readiness"])
def test_zone_coordinates_within_grid_and_tiling(csv_file, out_dir, direction, title):
    kwargs = {"direction": direction}
    if title:
        kwargs["title"] = title
    root = build_root(two_sheet_spec(csv_file, out_dir, **kwargs))
    for z in root.find("dashboards")[0].iter("zone"):
        box = {a: int(z.get(a)) for a in ("x", "y", "w", "h")}
        for attr, value in box.items():
            assert 0 <= value <= ZONE_GRID, f"{attr}={value} outside grid"
        assert box["x"] + box["w"] <= ZONE_GRID
        assert box["y"] + box["h"] <= ZONE_GRID

    # children of every layout-flow tile their parent exactly
    for flow in root.iter("zone"):
        if flow.get("type") != "layout-flow":
            continue
        vertical = flow.get("param") == "vert"
        start_key, size_key = ("y", "h") if vertical else ("x", "w")
        cursor = int(flow.get(start_key))
        for child in [c for c in flow if c.tag == "zone"]:
            assert int(child.get(start_key)) == cursor
            cursor += int(child.get(size_key))
        assert cursor == int(flow.get(start_key)) + int(flow.get(size_key))


def test_title_emits_both_layout_options_and_title_zone(csv_file, out_dir):
    """Either piece alone is a silent no-op (§6)."""
    root = build_root(two_sheet_spec(csv_file, out_dir, title="Site Readiness"))
    dash = root.find("dashboards")[0]

    runs = [r.text for r in dash.findall("layout-options/title/formatted-text/run")]
    assert runs == ["Site Readiness"]

    title_zones = [z for z in dash.iter("zone") if z.get("type") == "title"]
    assert len(title_zones) == 1
    assert int(title_zones[0].get("h")) > 0


def test_no_title_means_neither_piece(csv_file, out_dir):
    root = build_root(two_sheet_spec(csv_file, out_dir))
    dash = root.find("dashboards")[0]
    assert dash.find("layout-options") is None
    assert not [z for z in dash.iter("zone") if z.get("type") == "title"]


def test_zone_style_is_always_the_last_child(csv_file, out_dir):
    root = build_root(two_sheet_spec(csv_file, out_dir, title="T"))
    for z in root.find("dashboards")[0].iter("zone"):
        tags = [c.tag for c in z]
        if "zone-style" in tags:
            assert tags[-1] == "zone-style", tags


def test_dashboard_window_has_viewpoints_and_no_cards(csv_file, out_dir):
    root = build_root(two_sheet_spec(csv_file, out_dir))
    windows = root.find("windows")
    dash_wins = [w for w in windows if w.get("class") == "dashboard"]
    assert len(dash_wins) == 1
    win = dash_wins[0]
    assert win.get("name") == "Overview"
    assert win.get("maximized") == "true"
    assert win.find("cards") is None
    assert [v.get("name") for v in win.findall("viewpoints/viewpoint")] == [
        "Sheet One",
        "Sheet Two",
    ]
    assert win.find("active").get("id") == "-1"
    # exactly one maximized window: the dashboard takes it from the first sheet
    assert [w.get("name") for w in windows if w.get("maximized") == "true"] == ["Overview"]


def test_no_published_only_elements_or_type_v2(csv_file, out_dir):
    """type-v2 appears in zero fixtures at any doc version; we emit plain type."""
    result = build_workbook(two_sheet_spec(csv_file, out_dir, title="T"))
    raw = result.twb_path.read_text(encoding="utf-8")
    for forbidden in (
        "type-v2",
        "repository-location",
        "simple-id",
        "devicelayout",
        "layout-cache",
    ):
        assert forbidden not in raw, forbidden


def test_multiple_dashboards(csv_file, out_dir):
    s = two_sheet_spec(csv_file, out_dir)
    s["dashboards"].append(
        {"name": "Detail", "worksheets": ["Sheet Two"], "direction": "horizontal"}
    )
    root = build_root(s)
    assert [d.get("name") for d in root.find("dashboards")] == ["Overview", "Detail"]
    # zone ids restart per dashboard: they are dashboard-scoped (§4.5)
    for dash in root.find("dashboards"):
        assert dash.find("zones")[0].get("id") == "1"


def test_dashboard_build_is_byte_deterministic(csv_file, out_dir):
    """Same spec -> byte-identical .twb, including every zone id.

    The bytes MUST be snapshotted before the second build. Both builds use the
    same workbook name and output directory, so they write to the same path --
    an earlier version compared the file to itself and could not fail even if
    every zone id were random.
    """
    a = build_workbook(two_sheet_spec(csv_file, out_dir, title="Site Readiness"))
    first = a.twb_path.read_bytes()
    b = build_workbook(two_sheet_spec(csv_file, out_dir, title="Site Readiness"))
    assert first == b.twb_path.read_bytes()


# --- layer 2 validation catches what layer 1 cannot -------------------------


def test_layer2_catches_unresolved_zone_worksheet(csv_file, out_dir):
    """A renamed sheet loads fine and renders an empty box - only layer 2 sees it."""
    from tableau_public_authoring.validation.structure import _check_dashboards

    s = two_sheet_spec(csv_file, out_dir)
    result = build_workbook(s)
    root = ET.parse(result.twb_path).getroot()
    spec = parse_spec(s)

    issues = _check_dashboards(root, spec, {"Sheet One"})  # 'Sheet Two' renamed away
    codes = [i.code for i in issues]
    assert "unresolved_zone_worksheet" in codes
    assert all(i.severity == "error" for i in issues if i.code == "unresolved_zone_worksheet")


def test_layer2_catches_unexpected_dashboards_element(csv_file, out_dir):
    from tableau_public_authoring.validation.structure import _check_dashboards

    s = two_sheet_spec(csv_file, out_dir)
    root = ET.parse(build_workbook(s).twb_path).getroot()
    no_dash_spec = parse_spec(make_spec(csv_file, out_dir))

    codes = [i.code for i in _check_dashboards(root, no_dash_spec, {"Sheet One"})]
    assert codes == ["unexpected_dashboards"]


def test_layer2_catches_out_of_range_and_tiling(csv_file, out_dir):
    from tableau_public_authoring.validation.structure import _check_dashboards

    s = two_sheet_spec(csv_file, out_dir)
    spec = parse_spec(s)
    root = ET.parse(build_workbook(s).twb_path).getroot()

    victim = [z for z in root.iter("zone") if z.get("type") is None][0]
    victim.set("h", str(ZONE_GRID + 1))
    codes = [i.code for i in _check_dashboards(root, spec, {"Sheet One", "Sheet Two"})]
    assert "zone_out_of_range" in codes
    assert "zone_tiling" in codes


def test_layer2_catches_missing_dashboard_window(csv_file, out_dir):
    from tableau_public_authoring.validation.structure import _check_dashboards

    s = two_sheet_spec(csv_file, out_dir)
    spec = parse_spec(s)
    root = ET.parse(build_workbook(s).twb_path).getroot()
    windows = root.find("windows")
    for w in [w for w in windows if w.get("class") == "dashboard"]:
        windows.remove(w)

    codes = [i.code for i in _check_dashboards(root, spec, {"Sheet One", "Sheet Two"})]
    assert "missing_dashboard_window" in codes


def test_layer2_catches_half_a_title(csv_file, out_dir):
    from tableau_public_authoring.validation.structure import _check_dashboards

    s = two_sheet_spec(csv_file, out_dir, title="Site Readiness")
    spec = parse_spec(s)
    root = ET.parse(build_workbook(s).twb_path).getroot()
    dash = root.find("dashboards")[0]
    dash.remove(dash.find("layout-options"))  # text gone, card remains

    codes = [i.code for i in _check_dashboards(root, spec, {"Sheet One", "Sheet Two"})]
    assert "dashboard_title_halfway" in codes


def test_layer2_catches_misordered_dashboard_children(csv_file, out_dir):
    from tableau_public_authoring.validation.structure import _check_dashboards

    s = two_sheet_spec(csv_file, out_dir)
    spec = parse_spec(s)
    root = ET.parse(build_workbook(s).twb_path).getroot()
    dash = root.find("dashboards")[0]
    size = dash.find("size")
    dash.remove(size)
    dash.insert(0, size)  # size before style

    codes = [i.code for i in _check_dashboards(root, spec, {"Sheet One", "Sheet Two"})]
    assert "dashboard_child_order" in codes


# --- T1: XML injection ------------------------------------------------------


def test_hostile_dashboard_name_is_escaped_not_injected(csv_file, out_dir):
    """A hostile name must become escaped attribute text, never markup.

    The compiler builds every node with ElementTree, so the mitigation holds even
    when layer-1's name regex is bypassed entirely - which is what this test does
    by constructing the Dashboard directly.
    """
    hostile = 'Evil" onload="x"><injected/><!-- & ]]> '
    base = parse_spec(two_sheet_spec(csv_file, out_dir))
    base.dashboards = [
        Dashboard(
            name=hostile,
            worksheets=[DashboardZone(worksheet="Sheet One")],
            title='Title & <script>alert("x")</script> ]]>',
        )
    ]

    raw = WorkbookCompiler(base).to_bytes(data_dir_ref="Data/d")
    root = ET.fromstring(raw)  # still well-formed => nothing broke out of its node

    assert root.find("dashboards")[0].get("name") == hostile
    assert b"<injected/>" not in raw
    assert root.find(".//injected") is None
    assert b"&lt;injected/&gt;" in raw

    runs = [r.text for r in root.iter("run") if r.text]
    assert 'Title & <script>alert("x")</script> ]]>' in runs
    assert root.find(".//script") is None

    win = [w for w in root.find("windows") if w.get("class") == "dashboard"][0]
    assert win.get("name") == hostile


def test_hostile_dashboard_name_is_also_rejected_by_layer_1(csv_file, out_dir):
    """Defence in depth: the name regex refuses markup characters up front."""
    s = two_sheet_spec(csv_file, out_dir, name='Evil"><injected/>')
    with pytest.raises(SpecError, match="contains unsupported characters"):
        parse_spec(s)
