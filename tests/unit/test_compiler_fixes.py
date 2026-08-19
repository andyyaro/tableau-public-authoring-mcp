"""Regressions for four compiler defects that produced quiet, wrong output.

None of these failed loudly. A bare ``.twb`` named a data directory that existed
only inside the ``.twbx``; a text table rendered an empty grid; a filter on a
measure drew a checkbox list over a continuous field; and a build overwrote
whatever happened to share its file name. Every test here fails against the code
as it was.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

from tableau_public_authoring.compiler import build as build_module
from tableau_public_authoring.compiler import workbook as workbook_module
from tableau_public_authoring.compiler.build import (
    OutputCollisionError,
    build_workbook,
    safe_basename,
)
from tableau_public_authoring.compiler.workbook import CompileError, WorkbookCompiler
from tableau_public_authoring.models.spec import SpecError, parse_spec

from .conftest_helpers import make_spec, write_csv


@pytest.fixture
def csv_file(tmp_path):
    return write_csv(tmp_path / "d.csv", rows=4)


@pytest.fixture
def out_dir(tmp_path):
    p = tmp_path / "out"
    p.mkdir()
    return p


def _connections(root: ET.Element) -> tuple[dict[str, str], dict[str, str]]:
    """(textscan directory, hyper dbname) per data source caption."""
    dirs: dict[str, str] = {}
    dbnames: dict[str, str] = {}
    for ds in root.find("datasources"):
        for conn in ds.iter("connection"):
            if conn.get("class") == "textscan":
                dirs[ds.get("caption")] = f"{conn.get('directory')}/{conn.get('filename')}"
            elif conn.get("class") == "hyper":
                dbnames[ds.get("caption")] = conn.get("dbname")
    return dirs, dbnames


# --- 1. data_dir_ref was accepted, documented, and ignored -------------------


def test_data_dir_ref_reaches_the_generated_connections(csv_file, out_dir):
    """The parameter was threaded through ``_build_datasource(ds_id, _unused)``.

    The method recomputed ``data_dir_for(ds_id)`` internally, so the caller's
    value could not influence the output at all: whatever was passed, the file
    named the .twbx-internal layout.
    """
    spec = parse_spec(make_spec(csv_file, out_dir))
    root = ET.fromstring(WorkbookCompiler(spec).to_bytes(data_dir_ref="Elsewhere"))
    dirs, dbnames = _connections(root)
    assert dirs == {"d": "Elsewhere/d/d.csv"}
    assert dbnames == {"d": "Elsewhere/d/d.hyper"}


def test_each_data_source_still_gets_its_own_subdirectory(tmp_path, out_dir):
    """Honouring the caller must not collapse two sources into one directory."""
    a = write_csv(tmp_path / "a.csv", rows=3)
    b = write_csv(tmp_path / "b.csv", rows=3)
    raw = make_spec(a, out_dir)
    raw["data_sources"].append({"id": "second", "type": "csv", "path": str(b)})
    root = ET.fromstring(WorkbookCompiler(parse_spec(raw)).to_bytes(data_dir_ref="Root"))
    dirs, dbnames = _connections(root)
    assert dirs == {"d": "Root/d/a.csv", "second": "Root/second/b.csv"}
    assert dbnames == {"d": "Root/d/d.hyper", "second": "Root/second/second.hyper"}


@pytest.mark.parametrize("package", [True, False])
def test_the_generated_twb_can_find_its_data_on_disk(csv_file, out_dir, package):
    """The defect, on a real artifact: output/TplLine.twb says
    ``directory="Data/sites"`` and output/Data/ does not exist.

    A .twb resolves data relative to its own location, so every path it names
    has to be there next to it - the extract was staged in a hidden .extracts/
    directory nobody referenced.
    """
    result = build_workbook(
        make_spec(csv_file, out_dir, output={"directory": str(out_dir), "package_twbx": package})
    )
    root = ET.parse(result.twb_path).getroot()
    dirs, dbnames = _connections(root)
    for referenced in (*dirs.values(), *dbnames.values()):
        assert not Path(referenced).is_absolute(), referenced
        assert (out_dir / referenced).is_file(), f"{referenced} does not exist next to the .twb"


def test_the_packaged_twb_matches_the_archive_layout(csv_file, out_dir):
    """The same bytes are zipped AND left on disk, so the reference has to be
    valid in both places: inside the archive it is resolved from the root."""
    result = build_workbook(make_spec(csv_file, out_dir))
    dirs, dbnames = _connections(ET.parse(result.twb_path).getroot())
    with zipfile.ZipFile(result.twbx_path) as zf:
        names = set(zf.namelist())
    for referenced in (*dirs.values(), *dbnames.values()):
        assert referenced in names, f"{referenced} is not in the package: {sorted(names)}"


def test_write_twb_is_gone():
    """``write_twb`` had no callers and could not honour its own contract.

    Writing XML is not enough to produce an openable bare .twb: the extract and
    the CSV it names have to exist beside it, which only the build pipeline does.
    """
    assert not hasattr(workbook_module, "write_twb")


# --- 2. the text-table fallback keyed off the wrong shelf --------------------


def _encodings(root: ET.Element, sheet: str) -> ET.Element:
    for ws in root.iter("worksheet"):
        if ws.get("name") == sheet:
            return ws.find(".//encodings")
    raise AssertionError(f"no worksheet {sheet!r}")


def _text_table(csv_file, out_dir, **shelves) -> ET.Element:
    raw = make_spec(csv_file, out_dir)
    raw["worksheets"][0] = {
        "name": "Sheet One",
        "template": "text_table",
        "data_source": "d",
        **shelves,
    }
    return ET.fromstring(WorkbookCompiler(parse_spec(raw)).to_bytes(data_dir_ref="Data"))


def test_text_table_takes_its_measure_from_rows(csv_file, out_dir):
    """``_mark_requirements("text_table")`` is (rows=True, cols=False), so the
    canonical text table has NO columns - and the guard required ``col_refs``.

    This spec compiled to ``<encodings />``: no <text>, nothing to render.
    """
    root = _text_table(csv_file, out_dir, rows=["Site", {"field": "Score", "aggregation": "Sum"}])
    texts = [t.get("column") for t in _encodings(root, "Sheet One").findall("text")]
    assert len(texts) == 1 and texts[0].endswith(".[sum:Score:qk]"), texts


def test_text_table_does_not_put_a_dimension_on_text(csv_file, out_dir):
    """The fallback took ``col_refs[0]`` blindly, whatever the caller put there."""
    root = _text_table(
        csv_file,
        out_dir,
        rows=[{"field": "Score", "aggregation": "Sum"}],
        columns=["Status"],
    )
    texts = [t.get("column") for t in _encodings(root, "Sheet One").findall("text")]
    assert len(texts) == 1 and texts[0].endswith(".[sum:Score:qk]"), texts


def test_text_table_with_no_measure_labels_nothing(csv_file, out_dir):
    """mark-labels-show=true with an empty Text encoding switches labels on and
    leaves Tableau nothing to draw."""
    root = _text_table(csv_file, out_dir, rows=["Site"], columns=["Status"])
    assert _encodings(root, "Sheet One").findall("text") == []
    assert not [f for f in root.iter("format") if f.get("attr") == "mark-labels-show"]


def test_an_explicit_label_still_wins(csv_file, out_dir):
    """The fallback only fires when the caller named nothing."""
    root = _text_table(
        csv_file,
        out_dir,
        rows=["Site"],
        columns=[{"field": "Score", "aggregation": "Sum"}],
        label={"field": "Score", "aggregation": "Avg"},
    )
    texts = [t.get("column") for t in _encodings(root, "Sheet One").findall("text")]
    assert len(texts) == 1 and texts[0].endswith(".[avg:Score:qk]"), texts


# --- 3. every filter was hardcoded categorical -------------------------------


def test_the_compiler_refuses_a_filter_it_cannot_express(csv_file, out_dir):
    """It compiled to
    ``<filter class="categorical" column="[federated.…].[none:Score:qk]">``
    plus a checkdropdown card: a checkbox list over a continuous field, which
    Tableau loads without complaint and renders as nonsense.

    ``parse_spec`` rejects this at layer 1, so the spec is mutated afterwards to
    reach the compiler: ``WorkbookCompiler`` is a public class that can be handed
    a spec built any way at all, and the one thing it must never do is emit
    markup it knows is wrong.
    """
    spec = parse_spec(make_spec(csv_file, out_dir))
    spec.worksheets[0].filters = ["Score"]
    with pytest.raises(CompileError, match="cannot filter on 'Score'"):
        WorkbookCompiler(spec).to_bytes(data_dir_ref="Data")


def test_the_pipeline_writes_nothing_for_a_measure_filter(csv_file, out_dir):
    """End to end, either layer may catch it - but no file may appear."""
    raw = make_spec(csv_file, out_dir)
    raw["worksheets"][0]["filters"] = ["Score"]
    with pytest.raises((SpecError, CompileError), match="Score"):
        build_workbook(raw)
    assert list(out_dir.iterdir()) == []


def test_a_filter_on_a_dimension_is_untouched(csv_file, out_dir):
    """The verified shape stays exactly as it was."""
    raw = make_spec(csv_file, out_dir)
    raw["worksheets"][0]["filters"] = ["Status"]
    root = ET.parse(build_workbook(raw).twb_path).getroot()
    filters = list(root.iter("filter"))
    assert [f.get("class") for f in filters] == ["categorical"]
    assert filters[0].get("column").endswith(".[none:Status:nk]")
    assert [g.get("function") for g in filters[0]] == ["level-members"]
    cards = [c for c in root.iter("card") if c.get("type") == "filter"]
    assert [c.get("mode") for c in cards] == ["checkdropdown"]


# --- 4. builds overwrote anything that shared their file name ---------------


@pytest.mark.parametrize("victim", ["Test_Workbook.twb", "Test_Workbook.twbx"])
def test_a_foreign_file_is_not_overwritten(csv_file, out_dir, victim):
    """No ``overwrite``/``confirm`` parameter and no existence check, while
    ``publish_to_tableau_public`` gates on ``confirm_publish``. The .twbx was
    explicitly unlinked first, so the loss was unconditional."""
    planted = out_dir / victim
    planted.write_bytes(b"PRECIOUS")
    with pytest.raises(OutputCollisionError, match=victim):
        build_workbook(make_spec(csv_file, out_dir))
    assert planted.read_bytes() == b"PRECIOUS"
    # Nothing at all was written: the guard runs before the first byte.
    assert not (out_dir / "Data").exists()


def test_a_foreign_manifest_is_not_overwritten(csv_file, out_dir):
    planted = out_dir / "Test_Workbook.manifest.json"
    planted.write_text('{"workbook_name": "Someone Else"}', encoding="utf-8")
    with pytest.raises(OutputCollisionError, match="Someone Else"):
        build_workbook(make_spec(csv_file, out_dir))
    assert "Someone Else" in planted.read_text(encoding="utf-8")


@pytest.mark.parametrize("package", [True, False])
def test_rebuilding_the_same_spec_needs_no_ceremony(csv_file, out_dir, package):
    """A rebuild replaces only this pipeline's own output, which is regenerable
    from the spec, so it must stay a plain call."""
    raw = make_spec(csv_file, out_dir, output={"directory": str(out_dir), "package_twbx": package})
    first = build_workbook(raw)
    second = build_workbook(raw)
    assert first.twb_path.read_bytes() == second.twb_path.read_bytes()


def test_a_big_package_is_still_recognised_as_ours(csv_file, out_dir, monkeypatch):
    """The read cap bounds what the guard READS, not the archive it inspects.

    A .twbx carrying a real extract is routinely tens of megabytes; capping the
    container would disown our own package and demand ``overwrite`` on every
    rebuild of a real workbook. The cap is pushed between the inner .twb and the
    archive size so the distinction is what the test turns on.
    """
    raw = make_spec(csv_file, out_dir)
    first = build_workbook(raw)
    with zipfile.ZipFile(first.twbx_path) as zf:
        inner = max(i.file_size for i in zf.infolist() if i.filename.endswith(".twb"))
    # A four-row fixture compresses to less than its own .twb, so the archive is
    # padded with stored bytes to look like a package holding real data.
    with zipfile.ZipFile(first.twbx_path, "a") as zf:
        zf.writestr("Data/d/padding.bin", b"\0" * 200_000)
    archive = first.twbx_path.stat().st_size
    assert archive > inner + 1, (archive, inner)
    monkeypatch.setattr(build_module, "_PROBE_BYTES", (inner + archive) // 2)
    build_workbook(raw)


def test_overwrite_true_is_the_escape_hatch(csv_file, out_dir):
    planted = out_dir / "Test_Workbook.twb"
    planted.write_bytes(b"PRECIOUS")
    result = build_workbook(make_spec(csv_file, out_dir), overwrite=True)
    assert result.twb_path == planted
    assert planted.read_bytes() != b"PRECIOUS"


@pytest.mark.parametrize("package", [True, False])
def test_two_names_that_sanitise_alike_do_not_clobber(csv_file, out_dir, package):
    """``safe_basename`` is not injective: 'My/Report' and 'My Report' both map
    to 'My_Report', so two different workbooks silently shared three files."""
    assert safe_basename("My/Report") == safe_basename("My Report") == "My_Report"

    def spec(name):
        return make_spec(
            csv_file,
            out_dir,
            name=name,
            output={"directory": str(out_dir), "package_twbx": package},
        )

    first = build_workbook(spec("My Report"))
    original = first.twb_path.read_bytes()
    with pytest.raises(OutputCollisionError):
        build_workbook(spec("My/Report"))
    assert first.twb_path.read_bytes() == original
