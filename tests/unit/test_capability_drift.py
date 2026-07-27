"""Guards against the server lying about what it can do.

This exists because of a real defect: ``get_authoring_capabilities`` reported
``"dashboards": "not implemented in v0.1"`` for some time AFTER dashboards had
been implemented and confirmed rendering in Tableau Public 2026.2.0.

That class of bug is worse than stale documentation. A model chooses what to
attempt based on this payload, so a false "unsupported" silently removes a working
feature, and a false "supported" produces confident failures. These tests pin the
report to the actual code.
"""

from __future__ import annotations

from dataclasses import fields as dataclass_fields

from tableau_public_authoring.capabilities import (
    TEMPLATE_REQUIREMENTS,
    dashboards_supported,
    describe_capabilities,
    describe_templates,
    supported_encodings,
)
from tableau_public_authoring.compiler.workbook import MARK_CLASS
from tableau_public_authoring.models.spec import (
    AGGREGATIONS,
    FIT_MODES,
    SUPPORTED_TEMPLATES,
    Worksheet,
)


def test_every_supported_template_is_reported():
    caps = describe_capabilities()
    assert set(caps["supported"]["worksheet_templates"]) == set(SUPPORTED_TEMPLATES)


def test_every_reported_template_can_actually_be_compiled():
    """A template the compiler has no mark class for must never be advertised."""
    for template in describe_capabilities()["supported"]["worksheet_templates"]:
        assert template in MARK_CLASS, f"{template!r} is advertised but has no mark class"


def test_template_listing_matches_supported_templates():
    listed = [t["name"] for t in describe_templates()]
    assert listed == list(SUPPORTED_TEMPLATES)
    for entry in describe_templates():
        assert entry["mark_class"] == MARK_CLASS[entry["name"]]
        assert entry["requires"], f"{entry['name']!r} has no shelf requirement text"


def test_every_template_has_requirement_text():
    missing = set(SUPPORTED_TEMPLATES) - set(TEMPLATE_REQUIREMENTS)
    assert not missing, f"templates with no documented requirements: {sorted(missing)}"


def test_encodings_are_derived_from_the_worksheet_model():
    """Adding an encoding to Worksheet must surface without editing the report."""
    reported = set(supported_encodings())
    model_fields = {f.name for f in dataclass_fields(Worksheet)}
    assert reported <= model_fields, (
        f"reported encodings not on the model: {reported - model_fields}"
    )
    # These are structural, not encodings, and must never be reported as such.
    for structural in ("name", "template", "data_source", "rows", "columns", "title", "fit"):
        assert structural not in reported


def test_known_encodings_are_reported():
    reported = set(describe_capabilities()["supported"]["encodings"])
    for expected in ("color", "size", "label", "tooltips"):
        assert expected in reported, f"{expected!r} is implemented but not reported"


def test_dashboard_claim_matches_the_model():
    """The exact bug this module exists for."""
    caps = describe_capabilities()
    if dashboards_supported():
        assert "dashboards" in caps["supported"]
        assert "dashboards" not in caps["unsupported"], (
            "dashboards are implemented but still reported as unsupported"
        )
    else:
        assert "dashboards" in caps["unsupported"]
        assert "dashboards" not in caps["supported"]


def test_nothing_is_both_supported_and_unsupported():
    caps = describe_capabilities()
    overlap = set(caps["supported"]) & set(caps["unsupported"])
    assert not overlap, f"contradictory capability keys: {sorted(overlap)}"


def test_aggregations_and_fit_modes_come_from_the_model():
    caps = describe_capabilities()
    assert set(caps["supported"]["aggregations"]) == set(AGGREGATIONS)
    assert set(caps["supported"]["canvas_fit"]) == set(FIT_MODES)


def test_live_connections_are_reported_as_impossible_not_merely_missing():
    """Tableau Public rejects them outright; that is a platform limit, not a TODO."""
    reason = describe_capabilities()["unsupported"]["live_connections"]
    assert "3C242D89" in reason


def test_report_is_json_serialisable():
    import json

    json.dumps(describe_capabilities())
    json.dumps(describe_templates())
