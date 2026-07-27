"""The capabilities CAPABILITY_BOUNDARY.md calls VERIFIED that nothing tested.

WHY THIS FILE EXISTS
--------------------
"Verified" in that document means a human generated a workbook, opened it in
Tableau Public 2026.2.0 and looked at it. That is the strongest evidence this
project has and also the most perishable: nothing re-runs it, so a refactor can
take the capability away and every test still passes. Three rows had no
automated evidence at all.

* **The ``size`` encoding.** ``compiler/workbook.py`` emits ``<size>`` on the
  Marks card, and no test anywhere set ``size`` on a worksheet or looked for the
  element. The one thing that mentioned it was a list of *encoding names* in
  ``test_capability_drift``, which would still pass if the compiler had never
  emitted a single ``<size>``.
* **Multiple data sources.** Every spec in the suite declared exactly one. The
  only related test asserted that a *duplicate* id is rejected, which says
  nothing about two distinct ones. The claim is "two CSVs -> two ``.hyper``
  extracts under separate ``Data/<id>/``; both load in Tableau", and the part a
  unit test can settle is where the bytes and the connection strings point.
* **Worksheet titles and subtitles.** One fixture set both and asserted neither.
  ``test_security`` proves a *hostile* title is escaped rather than injected,
  which it would be even if the subtitle were dropped on the floor.

What a unit test can decide is decided here. What it cannot - "Tableau opened it
and drew marks" - is in ``tests/live/test_encodings_and_sources.py``: a viz can
compile perfectly and still render blank, which is the failure mode the live
tier exists to catch.

The last two sections guard the live tier from outside it. Both are pure logic
with no GUI dependency, so both belong in the tier that actually runs.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

import pytest

from tableau_public_authoring.compiler.build import build_workbook
from tableau_public_authoring.compiler.workbook import WorkbookCompiler
from tableau_public_authoring.models.spec import SUPPORTED_TEMPLATES, SpecError, parse_spec

from ..live import conftest as live_conftest
from ..live.test_render_templates import TEMPLATE_CASES

try:  # pragma: no cover - tomllib is stdlib from 3.11; the project targets 3.13
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The data ROOT handed to the compiler. Deliberately not ``Data``: the layout
#: under test is ``<root>/<data source id>``, and a root spelled the same as the
#: package's own would let a test pass that had confused the two halves.
ROOT_HINT = "RootHint"


# --------------------------------------------------------------- spec helpers


def write_sites_csv(path: Path) -> Path:
    """A dimension, two measures and a category. Enough for any encoding."""
    path.write_text(
        "Site,State,Score,Sessions\n"
        "Site A,IL,55,4300\n"
        "Site B,CO,58,3400\n"
        "Site C,IL,71,9100\n",
        encoding="utf-8",
    )
    return path


def write_usage_csv(path: Path) -> Path:
    """A second, structurally unrelated table: no column name is shared."""
    path.write_text(
        "Quarter,Region,Uptime Percent\n"
        "2026-Q1,West,99.3\n"
        "2026-Q1,Midwest,95.7\n"
        "2026-Q2,West,97.1\n",
        encoding="utf-8",
    )
    return path


def one_source_spec(csv: Path, out: Path, **worksheet: Any) -> dict:
    ws: dict[str, Any] = {
        "name": "Sheet One",
        "template": "circle",
        "data_source": "d",
        "rows": ["State"],
        "columns": [{"field": "Score", "aggregation": "Sum"}],
    }
    ws.update(worksheet)
    return {
        "spec_version": "0.1",
        "workbook": {"name": "Coverage Gap"},
        "data_sources": [{"id": "d", "type": "csv", "path": str(csv)}],
        "worksheets": [ws],
        "output": {"directory": str(out), "package_twbx": True},
    }


def two_source_spec(sites: Path, usage: Path, out: Path) -> dict:
    """Two CSVs, and a worksheet bound to each.

    The sheet on the SECOND source comes first so the maximized window a live
    run photographs belongs to it; see tests/live/test_encodings_and_sources.py.
    """
    return {
        "spec_version": "0.1",
        "workbook": {"name": "Two Sources"},
        "data_sources": [
            {"id": "sites", "type": "csv", "path": str(sites)},
            {"id": "usage", "type": "csv", "path": str(usage)},
        ],
        "worksheets": [
            {
                "name": "Uptime By Region",
                "template": "bar",
                "data_source": "usage",
                "rows": ["Region"],
                "columns": [{"field": "Uptime Percent", "aggregation": "Avg"}],
                "color": "Region",
            },
            {
                "name": "Score By State",
                "template": "bar",
                "data_source": "sites",
                "rows": ["State"],
                "columns": [{"field": "Score", "aggregation": "Sum"}],
            },
        ],
        "output": {"directory": str(out), "package_twbx": True},
    }


def compile_xml(spec: dict, *, data_dir_ref: str = ROOT_HINT) -> ET.Element:
    """Spec -> parsed .twb XML, without materialising a Hyper extract."""
    return ET.fromstring(WorkbookCompiler(parse_spec(spec)).to_bytes(data_dir_ref=data_dir_ref))


def worksheet(root: ET.Element, name: str) -> ET.Element:
    for ws in root.iter("worksheet"):
        if ws.get("name") == name:
            return ws
    have = [w.get("name") for w in root.iter("worksheet")]
    raise AssertionError(f"worksheet {name!r} not found; have {have}")


def encodings(root: ET.Element, name: str = "Sheet One") -> ET.Element:
    enc = worksheet(root, name).find(".//pane/encodings")
    assert enc is not None, f"worksheet {name!r} has no <encodings> element"
    return enc


@pytest.fixture
def out_dir(tmp_path: Path) -> Path:
    d = tmp_path / "out"
    d.mkdir()
    return d


@pytest.fixture
def sites_csv(tmp_path: Path) -> Path:
    return write_sites_csv(tmp_path / "sites.csv")


@pytest.fixture
def usage_csv(tmp_path: Path) -> Path:
    return write_usage_csv(tmp_path / "usage.csv")


# =========================================================== the size encoding
#
# CAPABILITY_BOUNDARY.md: "Size encoding | circle radii vary with SUM(Annual
# Sessions), screenshot-verified". Nothing tested it. A dropped <size> is
# invisible in every other assertion in the suite: the workbook still opens,
# still validates, and still draws marks - all of them the same size.


def test_size_encoding_reaches_the_marks_card(sites_csv, out_dir):
    """A `size` on the spec becomes <size> inside the sheet's <encodings>."""
    root = compile_xml(
        one_source_spec(sites_csv, out_dir, size={"field": "Sessions", "aggregation": "Sum"})
    )
    sizes = encodings(root).findall("size")
    assert len(sizes) == 1, "exactly one <size> encoding was requested"
    assert sizes[0].get("column").endswith(".[sum:Sessions:qk]"), sizes[0].get("column")
    assert sizes[0].get("column").startswith("[federated.")


def test_no_size_in_the_spec_means_no_size_element(sites_csv, out_dir):
    """The discriminating half: <size> is not emitted unconditionally.

    Without this, the test above would still pass if the compiler put a <size>
    on every worksheet regardless of what the caller asked for.
    """
    root = compile_xml(one_source_spec(sites_csv, out_dir))
    assert encodings(root).findall("size") == []


def test_the_size_field_is_declared_as_a_column_and_a_column_instance(sites_csv, out_dir):
    """An encoding whose field is not declared renders as a red pill on a blank canvas.

    This is the same defect class as the tooltip-derivation bug in
    docs/LIMITATIONS.md: the XML is well-formed, Tableau opens it without a
    complaint, and the viz never draws. The <size> element is only half of the
    contract - the sheet must also declare the field it points at.
    """
    root = compile_xml(
        one_source_spec(sites_csv, out_dir, size={"field": "Sessions", "aggregation": "Sum"})
    )
    ws = worksheet(root, "Sheet One")
    referenced = encodings(root).find("size").get("column")

    declared = {c.get("name") for c in ws.iter("column")}
    assert "[Sessions]" in declared, f"the size field must be declared; have {declared}"

    instances = {ci.get("name"): ci for ci in ws.iter("column-instance")}
    assert referenced.endswith(".[sum:Sessions:qk]")
    assert "[sum:Sessions:qk]" in instances, f"unresolved size pill; have {sorted(instances)}"
    instance = instances["[sum:Sessions:qk]"]
    assert instance.get("derivation") == "Sum"
    assert instance.get("column") == "[Sessions]"


def test_size_never_leaves_the_marks_card(sites_csv, out_dir):
    """<size> is a worksheet encoding; a dashboard's <size> is a different element.

    Scoped to the worksheet subtree on purpose: dashboards legitimately carry
    their own <size> (canvas bounds in pixels), and conflating the two is how a
    "size is emitted" assertion ends up passing on a workbook with no size
    encoding at all.
    """
    root = compile_xml(
        one_source_spec(sites_csv, out_dir, size={"field": "Sessions", "aggregation": "Sum"})
    )
    ws = worksheet(root, "Sheet One")
    parents = {parent.tag for parent in ws.iter() for child in parent if child.tag == "size"}
    assert parents == {"encodings"}


def test_size_and_color_can_encode_different_fields(sites_csv, out_dir):
    """The two quantitative encodings must not overwrite one another."""
    root = compile_xml(
        one_source_spec(
            sites_csv,
            out_dir,
            color="State",
            size={"field": "Sessions", "aggregation": "Sum"},
        )
    )
    enc = encodings(root)
    assert enc.find("color").get("column").endswith(".[none:State:nk]")
    assert enc.find("size").get("column").endswith(".[sum:Sessions:qk]")


def test_size_on_an_unaggregated_dimension_is_rejected(sites_csv, out_dir):
    """Tableau cannot scale a mark by a string. The spec layer says so first."""
    with pytest.raises(SpecError, match="size encoding needs a measure or an aggregation"):
        parse_spec(one_source_spec(sites_csv, out_dir, size="State"))


def test_size_on_an_aggregated_dimension_is_accepted(sites_csv, out_dir):
    """COUNT of a dimension is a number, so it is a legitimate size."""
    root = compile_xml(
        one_source_spec(sites_csv, out_dir, size={"field": "State", "aggregation": "Count"})
    )
    assert encodings(root).find("size").get("column").endswith(".[cnt:State:qk]")


def test_a_sized_worksheet_survives_the_whole_build(sites_csv, out_dir):
    """End to end, including layer-2 structural validation.

    The XML tests above use the compiler directly. This one proves the size
    encoding also passes ``validate_generated``, which is what would reject it
    at build time if the element were not in the accepted content model.
    """
    result = build_workbook(
        one_source_spec(sites_csv, out_dir, size={"field": "Sessions", "aggregation": "Sum"})
    )
    xml = ET.fromstring(result.twb_path.read_bytes())
    assert encodings(xml).findall("size"), "the built workbook lost its size encoding"


# ====================================================== multiple data sources
#
# CAPABILITY_BOUNDARY.md: "Multiple data sources | two CSVs -> two .hyper
# extracts under separate Data/<id>/; both load in Tableau". Every spec in the
# suite declared exactly one source, so nothing here was exercised: not the
# per-source directories, not the second extract, not the binding of a worksheet
# to anything other than data_sources[0].


def test_two_sources_produce_two_extracts_under_their_own_directories(
    sites_csv, usage_csv, out_dir
):
    """The packaged half of the claim: two ``.hyper`` files, one per source."""
    result = build_workbook(two_source_spec(sites_csv, usage_csv, out_dir))
    with zipfile.ZipFile(result.twbx_path) as zf:
        names = set(zf.namelist())
        assert {
            "Data/sites/sites.hyper",
            "Data/usage/usage.hyper",
            "Data/sites/sites.csv",
            "Data/usage/usage.csv",
        } <= names, sorted(names)
        # Distinct files, not one extract packaged under two names.
        assert zf.read("Data/sites/sites.hyper") != zf.read("Data/usage/usage.hyper")


def test_each_source_points_at_its_own_data_directory(sites_csv, usage_csv, out_dir):
    """``<data root>/<data source id>``, per source, for both the CSV and the extract.

    Two ways to get this wrong and still produce a workbook that opens. Share
    one directory between the sources and the second one's extract is looked for
    at ``<root>/sites/usage.hyper``, which the package does not contain. Ignore
    the caller's root and every path is the ``.twbx``-internal layout, which a
    bare ``.twb`` sitting next to its data does not have. Both leave Tableau
    finding no data and drawing nothing, and no other assertion in the suite
    notices — which is why the root here is deliberately not spelled ``Data``.
    """
    root = compile_xml(two_source_spec(sites_csv, usage_csv, out_dir))
    dirs, dbnames = {}, {}
    for ds in root.find("datasources"):
        for conn in ds.iter("connection"):
            if conn.get("class") == "textscan":
                dirs[ds.get("caption")] = conn.get("directory")
            elif conn.get("class") == "hyper":
                dbnames[ds.get("caption")] = conn.get("dbname")

    assert dirs == {"sites": f"{ROOT_HINT}/sites", "usage": f"{ROOT_HINT}/usage"}
    assert dbnames == {
        "sites": f"{ROOT_HINT}/sites/sites.hyper",
        "usage": f"{ROOT_HINT}/usage/usage.hyper",
    }


def test_the_two_sources_get_distinct_generated_names(sites_csv, usage_csv, out_dir):
    """Colliding federated names would make the second source shadow the first."""
    root = compile_xml(two_source_spec(sites_csv, usage_csv, out_dir))
    names = [ds.get("name") for ds in root.find("datasources")]
    captions = [ds.get("caption") for ds in root.find("datasources")]
    assert captions == ["sites", "usage"]
    assert len(set(names)) == 2, names
    assert all(n.startswith("federated.") for n in names)


def test_a_worksheet_binds_to_its_own_source_not_the_first(sites_csv, usage_csv, out_dir):
    """The sheet on the second source must reference the second source.

    A sheet whose pills are qualified with the *other* source's name is the
    "opens fine, renders nothing" failure in its purest form.
    """
    root = compile_xml(two_source_spec(sites_csv, usage_csv, out_dir))
    by_caption = {ds.get("caption"): ds.get("name") for ds in root.find("datasources")}

    ws = worksheet(root, "Uptime By Region")
    used = ws.find(".//view/datasources/datasource")
    assert used.get("caption") == "usage"
    assert used.get("name") == by_caption["usage"]

    rows = ws.find("table/rows").text
    assert rows.startswith(f"[{by_caption['usage']}]"), rows
    assert by_caption["sites"] not in ET.tostring(ws, encoding="unicode")


def test_a_worksheet_cannot_reference_a_field_of_the_other_source(sites_csv, usage_csv, out_dir):
    """Field resolution is per data source, and stays that way with two of them."""
    spec = two_source_spec(sites_csv, usage_csv, out_dir)
    spec["worksheets"][0]["rows"] = ["State"]  # exists in 'sites', not in 'usage'
    with pytest.raises(SpecError, match="does not exist in data source 'usage'"):
        parse_spec(spec)


def test_the_manifest_records_both_sources(sites_csv, usage_csv, out_dir):
    import json

    result = build_workbook(two_source_spec(sites_csv, usage_csv, out_dir))
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert [d["id"] for d in manifest["data_sources"]] == ["sites", "usage"]
    assert [d["csv"] for d in manifest["data_sources"]] == ["sites.csv", "usage.csv"]


def test_both_sources_are_extract_backed(sites_csv, usage_csv, out_dir):
    """Tableau Public rejects a workbook with any non-extract source (3C242D89).

    One extract out of two is as fatal as none.
    """
    root = compile_xml(two_source_spec(sites_csv, usage_csv, out_dir))
    for ds in root.find("datasources"):
        extract = ds.find("extract")
        assert extract is not None, f"data source {ds.get('caption')!r} has no <extract>"
        assert extract.find("connection").get("class") == "hyper"


# ================================================= worksheet titles + subtitles
#
# CAPABILITY_BOUNDARY.md: "Titles + subtitles | rendered in the live public
# viz". The only test that touched a title asserted that a hostile one is
# escaped rather than injected - true even if the subtitle were discarded.


def test_title_and_subtitle_both_reach_the_layout_options(sites_csv, out_dir):
    root = compile_xml(
        one_source_spec(sites_csv, out_dir, title="Readiness", subtitle="synthetic data")
    )
    runs = worksheet(root, "Sheet One").findall("layout-options/title/formatted-text/run")
    assert [r.text for r in runs] == ["Readiness", "\n", "synthetic data"]
    assert runs[0].get("bold") == "true"
    # The subtitle is styled as a subtitle: smaller and grey, not a second title.
    assert runs[2].get("fontsize") == "10"
    assert int(runs[2].get("fontsize")) < int(runs[0].get("fontsize"))
    assert runs[2].get("fontcolor") == "#898989"


def test_a_subtitle_alone_still_produces_a_title_block(sites_csv, out_dir):
    """And no separator run, which would render as a leading blank line."""
    root = compile_xml(one_source_spec(sites_csv, out_dir, subtitle="synthetic data"))
    runs = worksheet(root, "Sheet One").findall("layout-options/title/formatted-text/run")
    assert [r.text for r in runs] == ["synthetic data"]


def test_a_title_alone_produces_exactly_one_run(sites_csv, out_dir):
    root = compile_xml(one_source_spec(sites_csv, out_dir, title="Readiness"))
    runs = worksheet(root, "Sheet One").findall("layout-options/title/formatted-text/run")
    assert [r.text for r in runs] == ["Readiness"]


def test_neither_means_no_layout_options_at_all(sites_csv, out_dir):
    """The discriminating half: an empty <layout-options> is not emitted."""
    ws = worksheet(compile_xml(one_source_spec(sites_csv, out_dir)), "Sheet One")
    assert ws.find("layout-options") is None


def test_layout_options_comes_before_the_table(sites_csv, out_dir):
    """Child order is a loader content model, not a style choice.

    ``<table>`` after ``<layout-options>`` is what every fixture shows; the
    reverse produced "element 'table' is not allowed for content model" for the
    dashboard equivalent (see tests/unit/test_dashboards.py).
    """
    ws = worksheet(
        compile_xml(one_source_spec(sites_csv, out_dir, title="Readiness")), "Sheet One"
    )
    assert [c.tag for c in ws] == ["layout-options", "table"]


# ================================================ the live tier, from outside it
#
# Both checks below are pure logic about the live tier with no GUI dependency,
# so they must run in the DEFAULT tier. The template drift check used to live in
# tests/live/test_render_templates.py under a module-level ``pytest.mark.live``,
# which meant the one test whose entire job is catching drift never executed in
# the tier that would notice.


def test_every_supported_template_has_a_live_render_case():
    """The live case table must not drift from what the spec model advertises.

    A template added to SUPPORTED_TEMPLATES without a live case would ship on
    the strength of unit tests alone, which is precisely how the two
    blank-render defects reached a human.
    """
    covered = {slug for slug, _, _ in TEMPLATE_CASES}
    assert covered == set(SUPPORTED_TEMPLATES), (
        f"live render coverage does not match SUPPORTED_TEMPLATES: "
        f"missing={sorted(set(SUPPORTED_TEMPLATES) - covered)}, "
        f"stale={sorted(covered - set(SUPPORTED_TEMPLATES))}"
    )


def test_each_live_case_names_the_template_it_claims_to_cover():
    """A case table entry whose slug and template disagree covers nothing."""
    for slug, worksheet_spec, _ in TEMPLATE_CASES:
        assert worksheet_spec["template"] == slug, (
            f"live case {slug!r} builds a {worksheet_spec['template']!r} worksheet, so the "
            f"drift check above is satisfied by a case that never exercises {slug!r}"
        )


LIVE_TIER = REPO_ROOT / "tests" / "live"


def test_every_live_test_module_is_marked_live():
    """The convention the collection hook enforces, checked at the source.

    ``tests/live/conftest.py`` re-marks anything it finds unmarked, but that is
    a net, not a licence: a module that forgets the marker is a mistake and this
    says so in the tier a developer actually runs.
    """
    modules = sorted(p.name for p in LIVE_TIER.glob("test_*.py"))
    assert modules, "no live test modules found; has the tier moved?"
    for name in modules:
        source = (LIVE_TIER / name).read_text(encoding="utf-8")
        assert "pytestmark" in source and "pytest.mark.live" in source, (
            f"tests/live/{name} does not declare a module-level live marker. Every test in "
            f"the tier drives the real Tableau GUI and must be excluded from a default run."
        )


@pytest.mark.parametrize(
    ("markexpr", "env", "expected"),
    [
        # A default run: pyproject's addopts filter is in force and does the work.
        ("not live", False, ("not live", False)),
        # The environment-variable route. addopts would otherwise deselect the
        # very tests the caller just asked for, so the default filter is dropped.
        ("not live", True, ("", False)),
        # An explicit -m always wins, with or without the environment variable.
        ("live", False, ("live", False)),
        ("live and not publish", False, ("live and not publish", False)),
        ("publish", False, ("publish", False)),
        ("live", True, ("live", False)),
        ("publish", True, ("publish", False)),
        # No marker filter at all (addopts removed or overridden with -m ""):
        # the belt is gone, so the conftest itself must deselect the tier.
        ("", False, ("", True)),
        ("  ", False, ("  ", True)),
        ("", True, ("", False)),
    ],
)
def test_live_tier_selection_rules(markexpr, env, expected):
    """The two independent defences, as a decision table.

    The bug this replaces: ``if "live" in markexpr`` treated the default
    ``"not live"`` as "the caller asked for the live tier", so the hook returned
    early on every single run and never deselected anything.
    """
    assert live_conftest.resolve_selection(markexpr, env_opt_in=env) == expected


def test_not_live_is_never_read_as_a_request_for_the_live_tier():
    """The specific substring confusion, pinned on its own."""
    markexpr, deselect = live_conftest.resolve_selection("not live", env_opt_in=False)
    assert markexpr == "not live", "pytest's own filter must be left alone to do the deselecting"
    assert deselect is False


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "on", " 1 "])
def test_the_opt_in_environment_variable_is_recognised(monkeypatch, raw):
    monkeypatch.setenv(live_conftest.OPT_IN_ENV, raw)
    assert live_conftest.env_opt_in() is True


@pytest.mark.parametrize("raw", ["", "0", "false", "no", "off", "maybe"])
def test_anything_else_is_not_an_opt_in(monkeypatch, raw):
    monkeypatch.setenv(live_conftest.OPT_IN_ENV, raw)
    assert live_conftest.env_opt_in() is False


# ============================================================== installability
#
# `uv sync && uv run pytest` must work on a clean checkout. It did not:
# tableauhyperapi is imported by compiler/extract.py and required by every
# build_workbook test, and it was in neither the project dependencies nor the
# dev group - it arrived only via a separate `uv pip install` line in README.md.


@pytest.mark.skipif(tomllib is None, reason="tomllib needs Python 3.11+")
def test_every_import_the_unit_tier_needs_is_declared():
    """A dependency the tests import must be installed by `uv sync`, not by hand."""
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = " ".join(
        config["project"]["dependencies"]
        + [d for group in config.get("dependency-groups", {}).values() for d in group]
    )
    for package in ("mcp", "jsonschema", "tableauhyperapi", "pytest"):
        assert package in declared, (
            f"{package} is imported by code this tier exercises but is not declared in "
            f"pyproject.toml, so `uv sync && uv run pytest` fails on a clean checkout"
        )


@pytest.mark.skipif(tomllib is None, reason="tomllib needs Python 3.11+")
def test_the_default_run_deselects_the_live_marker():
    """The belt, pinned. Removing it leaves only the conftest hook between a
    bare ``pytest`` and a run that launches Tableau on the developer's screen."""
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    addopts = config["tool"]["pytest"]["ini_options"]["addopts"]
    assert "-m" in addopts and "not live" in addopts, addopts
    markers = " ".join(config["tool"]["pytest"]["ini_options"]["markers"])
    assert "live:" in markers and "publish:" in markers


def test_the_hyper_api_is_importable_in_this_environment():
    """The import that `uv sync` was not installing, exercised rather than named.

    Every build_workbook test in the suite depends on it; without it they all
    error out at collection with a message about a missing module rather than
    about a missing dependency declaration.
    """
    from tableauhyperapi import SqlType

    assert callable(SqlType.big_int)
