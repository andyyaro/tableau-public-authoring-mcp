"""Security tests — the mitigations named in docs/architecture/THREAT_MODEL.md."""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

from tableau_public_authoring.compiler.build import build_workbook
from tableau_public_authoring.security.paths import (
    PathSecurityError,
    contains_machine_identifiers,
    resolve_input_file,
    resolve_output_dir,
    safe_archive_name,
)

from .conftest_helpers import make_spec  # noqa: F401  (fixture helper)

# --- T3: path traversal ----------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "relative/path.csv",
        "/tmp/../etc/passwd",
        "",
        "/nonexistent/nope.csv",
    ],
)
def test_resolve_input_file_rejects_bad_paths(bad):
    with pytest.raises(PathSecurityError):
        resolve_input_file(bad, must_suffix=".csv")


def test_resolve_input_file_rejects_wrong_suffix(tmp_path):
    p = tmp_path / "data.txt"
    p.write_text("a,b\n1,2\n")
    with pytest.raises(PathSecurityError):
        resolve_input_file(str(p), must_suffix=".csv")


def test_resolve_output_dir_rejects_system_locations():
    with pytest.raises(PathSecurityError):
        resolve_output_dir("/System/Library/Nope")


# --- T2: ZIP slip ----------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    ["../evil.twb", "/absolute/evil.twb", "a/../../b.csv", "", "x\x00y"],
)
def test_safe_archive_name_rejects_zip_slip(bad):
    with pytest.raises(PathSecurityError):
        safe_archive_name(bad)


def test_safe_archive_name_accepts_normal_entries():
    assert safe_archive_name("Data/sites/x.csv") == "Data/sites/x.csv"


# --- T1: XML injection -----------------------------------------------------


def test_xml_metacharacters_are_escaped_not_injected(tmp_path):
    """A hostile name/formula must be escaped as text, never become markup."""
    csv = tmp_path / "d.csv"
    csv.write_text("Site,Score\nA,1\nB,2\n")
    out = tmp_path / "out"
    out.mkdir()

    hostile_title = 'Evil "quoted" & <injected/> ]]> title'
    hostile_formula = 'IF [Score] > 1 THEN "<script>&amp;" ELSE "b" END'

    spec = {
        "spec_version": "0.1",
        "workbook": {"name": "XML Injection Test"},
        "data_sources": [{"id": "d", "type": "csv", "path": str(csv)}],
        "calculated_fields": [
            {"name": "Band", "data_source": "d", "datatype": "string", "formula": hostile_formula}
        ],
        "worksheets": [
            {
                "name": "S1",
                "template": "bar",
                "data_source": "d",
                "rows": ["Site"],
                "columns": [{"field": "Score", "aggregation": "Sum"}],
                "title": hostile_title,
            }
        ],
        "output": {"directory": str(out)},
    }
    result = build_workbook(spec)

    # Still parses => nothing broke out of its node.
    root = ET.parse(result.twb_path).getroot()

    titles = [r.text for r in root.iter("run") if r.text]
    assert hostile_title in titles, "title must survive verbatim as text"

    formulas = [c.get("formula") for c in root.iter("calculation")]
    assert hostile_formula in formulas, "formula must survive verbatim as an attribute"

    # No injected element leaked into the tree.
    assert not list(root.iter("script")), "hostile markup must not become an element"
    assert not list(root.iter("injected"))


# --- T6: machine identifiers must not leak into published artifacts --------


def test_generated_twb_contains_no_machine_identifiers(tmp_path):
    csv = tmp_path / "d.csv"
    csv.write_text("Site,Score\nA,1\nB,2\n")
    out = tmp_path / "out"
    out.mkdir()
    result = build_workbook(
        {
            "spec_version": "0.1",
            "workbook": {"name": "Leak Check"},
            "data_sources": [{"id": "d", "type": "csv", "path": str(csv)}],
            "worksheets": [
                {
                    "name": "S1",
                    "template": "bar",
                    "data_source": "d",
                    "rows": ["Site"],
                    "columns": [{"field": "Score", "aggregation": "Sum"}],
                }
            ],
            "output": {"directory": str(out)},
        }
    )
    text = Path(result.twb_path).read_text(encoding="utf-8")
    assert contains_machine_identifiers(text) == []
    assert "/Users/" not in text


def test_contains_machine_identifiers_detects_home_path():
    assert contains_machine_identifiers(f"path is {Path.home()}/x") != []


# --- package integrity ------------------------------------------------------


def test_package_entries_are_all_safe(tmp_path):
    csv = tmp_path / "d.csv"
    csv.write_text("Site,Score\nA,1\n")
    out = tmp_path / "out"
    out.mkdir()
    result = build_workbook(
        {
            "spec_version": "0.1",
            "workbook": {"name": "Pkg Check"},
            "data_sources": [{"id": "d", "type": "csv", "path": str(csv)}],
            "worksheets": [
                {
                    "name": "S1",
                    "template": "bar",
                    "data_source": "d",
                    "rows": ["Site"],
                    "columns": [{"field": "Score", "aggregation": "Sum"}],
                }
            ],
            "output": {"directory": str(out)},
        }
    )
    with zipfile.ZipFile(result.twbx_path) as zf:
        for n in zf.namelist():
            safe_archive_name(n)  # must not raise
