"""Regressions for defects found by a repository audit.

Each test names the defect and the concrete damage it caused. None of these were
caught by the 263 tests that existed at the time: every one passed while the bug
was live, which is the point.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from tableau_public_authoring.compiler.build import build_workbook
from tableau_public_authoring.compiler.extract import build_hyper
from tableau_public_authoring.compiler.fields import bracket, infer_fields
from tableau_public_authoring.compiler.workbook import _instance_name
from tableau_public_authoring.models.spec import SpecError, parse_spec
from tableau_public_authoring.packaging.twbx import package_twbx
from tableau_public_authoring.security.paths import PathSecurityError

FIXTURE_CSV = Path(__file__).resolve().parents[1] / "fixtures/data/ev_site_readiness.csv"


def _spec(out_dir: Path, **output_overrides) -> dict:
    output = {"directory": str(out_dir)}
    output.update(output_overrides)
    return {
        "spec_version": "0.1",
        "workbook": {"name": "AuditCheck"},
        "data_sources": [{"id": "sites", "type": "csv", "path": str(FIXTURE_CSV)}],
        "worksheets": [
            {
                "name": "Bars",
                "template": "bar",
                "data_source": "sites",
                "rows": ["Site Name"],
                "columns": [{"field": "Readiness Score", "aggregation": "Sum"}],
            }
        ],
        "output": output,
    }


# --- Tableau identifier escaping --------------------------------------------
#
# The compiler never concatenates XML, so it is immune to XML injection. But
# Tableau identifiers are a SECOND grammar nested inside attribute values, and
# that one was built by f-string with no escaping at all.


def test_a_closing_bracket_in_a_column_name_is_escaped():
    """`[Val]ue]` parses as the field `Val` followed by garbage."""
    assert bracket("Val]ue") == "[Val]]ue]"
    assert bracket("Readiness Score") == "[Readiness Score]"


def test_the_escape_covers_composed_instance_names():
    from tableau_public_authoring.compiler.fields import Field

    f = Field(name="Val]ue", datatype="real", role="measure", type="quantitative", ordinal=0)
    assert _instance_name(f, "Sum") == "[sum:Val]]ue:qk]"


def test_a_crafted_header_cannot_redirect_a_shelf_reference(tmp_path):
    """`X]:nk].[sum:Other` was able to make one column resolve to another field."""
    csv_path = tmp_path / "crafted.csv"
    csv_path.write_text("Site,X]:nk].[sum:Other\nA,1\nB,2\n")
    fields = {f.name: f for f in infer_fields(csv_path)}
    hostile = fields["X]:nk].[sum:Other"]
    # BOTH closing brackets in the header are doubled, so the identifier
    # terminates exactly where it should instead of at the attacker's first ']'.
    assert hostile.reference_name == "[X]]:nk]].[sum:Other]"
    assert hostile.reference_name.count("]]") == 2


# --- destructive writes before the security guard ---------------------------


def test_package_twbx_validates_the_name_before_writing_anything(tmp_path):
    """The guard used to run AFTER write_bytes() and unlink().

    `base_name="../victim"` overwrote victim.twb one directory up, deleted
    victim.twbx, replaced it with an empty archive, and only then raised. The
    caller saw a clean exception with no way to know two files were gone.
    """
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    victim_twb = tmp_path / "victim.twb"
    victim_twbx = tmp_path / "victim.twbx"
    victim_twb.write_bytes(b"PRECIOUS")
    victim_twbx.write_bytes(b"ALSO PRECIOUS")

    spec = parse_spec(_spec(out_dir))
    with pytest.raises(PathSecurityError):
        package_twbx(spec, b"<workbook/>", out_dir, base_name="../victim")

    assert victim_twb.read_bytes() == b"PRECIOUS", "the guard ran after the write"
    assert victim_twbx.read_bytes() == b"ALSO PRECIOUS", "the guard ran after the unlink"


# --- flags that were parsed and then ignored --------------------------------


def test_package_twbx_false_really_skips_the_archive(tmp_path):
    result = build_workbook(_spec(tmp_path, package_twbx=False))
    assert result.twb_path.exists()
    assert result.twbx_path is None
    assert not list(tmp_path.glob("*.twbx")), "opted out of packaging but got an archive anyway"


def test_package_twbx_true_still_produces_one(tmp_path):
    result = build_workbook(_spec(tmp_path))
    assert result.twbx_path is not None and Path(result.twbx_path).exists()


def test_fit_is_accepted_and_reaches_the_worksheet():
    """`fit` was validated, dropped on the floor, AND rejected as an unknown key.

    So the documented canvas-fit option could not be used at all: passing it
    raised "unknown keys ['fit']", and had it been accepted it would have been
    discarded before reaching the compiler.
    """
    raw = _spec(Path(FIXTURE_CSV).parent)
    raw["worksheets"][0]["fit"] = "entire_view"
    spec = parse_spec(raw)
    assert spec.worksheets[0].fit == "entire_view"


def test_an_invalid_fit_is_still_rejected():
    raw = _spec(Path(FIXTURE_CSV).parent)
    raw["worksheets"][0]["fit"] = "gigantic"
    with pytest.raises(SpecError, match="fit must be one of"):
        parse_spec(raw)


def test_fit_changes_the_compiled_zoom(tmp_path):
    import xml.etree.ElementTree as ET

    raw = _spec(tmp_path)
    raw["worksheets"][0]["fit"] = "fit_height"
    result = build_workbook(raw)
    zooms = [z.get("type") for z in ET.parse(result.twb_path).getroot().iter("zoom")]
    assert zooms == ["fit-height"]


# --- data corruption ---------------------------------------------------------


def test_a_blank_csv_line_does_not_become_a_row_of_nulls(tmp_path):
    """csv.reader yields [] for a blank line; padding it made a full NULL row.

    A trailing blank line is enough, and the phantom row reaches the extract,
    the <approx-count>, and every viz as a null mark.
    """
    csv_path = tmp_path / "gappy.csv"
    csv_path.write_text("Site,Value\nA,1\n\nB,2\n\n")
    fields = infer_fields(csv_path)
    out = tmp_path / "gappy.hyper"
    count = build_hyper(csv_path, fields, out)
    assert count == 2, f"expected 2 real rows, got {count}"


def test_a_row_of_only_whitespace_is_also_dropped(tmp_path):
    csv_path = tmp_path / "ws.csv"
    csv_path.write_text("Site,Value\nA,1\n  ,  \nB,2\n")
    assert build_hyper(csv_path, infer_fields(csv_path), tmp_path / "ws.hyper") == 2


def test_real_data_is_not_dropped(tmp_path):
    """The blank-line filter must not eat a legitimately sparse row."""
    csv_path = tmp_path / "sparse.csv"
    csv_path.write_text("Site,Value\nA,1\n,5\nB,\n")
    assert build_hyper(csv_path, infer_fields(csv_path), tmp_path / "sparse.hyper") == 3


def test_the_shipped_fixture_has_no_blank_lines():
    """Guards the fixture the whole live tier measures mark counts against."""
    with FIXTURE_CSV.open() as fh:
        rows = [r for r in csv.reader(fh)][1:]
    assert all(any(c.strip() for c in r) for r in rows)
    assert len(rows) == 12
