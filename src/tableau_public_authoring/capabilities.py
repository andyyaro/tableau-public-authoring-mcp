"""Self-description of what this server can author.

**This module derives its answer from the code, not from a hand-written list.**

That is deliberate. The capability report previously hard-coded
``"dashboards": "not implemented in v0.1"`` and kept saying it long after
dashboards had been implemented and verified rendering in Tableau. A model calling
``get_authoring_capabilities`` would read that and refuse to generate a dashboard
the server was perfectly capable of producing.

Documentation drift is cosmetic. **Tool-surface drift changes behaviour.** So the
worksheet templates, encodings, aggregations and fit modes below are all read from
the spec model and compiler at call time. Adding a new encoding to
:class:`~tableau_public_authoring.models.spec.Worksheet` makes it appear here
automatically, and ``tests/unit/test_capability_drift.py`` fails if these ever
diverge again.

Only genuinely static facts - platform constraints, and features that are simply
not implemented - are written out by hand.
"""

from __future__ import annotations

from dataclasses import fields as dataclass_fields
from typing import Any

from .compiler.workbook import MARK_CLASS
from .models.spec import (
    AGGREGATIONS,
    FIT_MODES,
    SPEC_VERSION,
    SUPPORTED_TEMPLATES,
    Worksheet,
)

# Worksheet spec keys that are NOT visual encodings. Everything else on the
# Worksheet dataclass is treated as one, so a newly added encoding is reported
# without anyone remembering to update this file.
_NON_ENCODING_WORKSHEET_FIELDS = frozenset(
    {
        "name",
        "template",
        "data_source",
        "rows",
        "columns",
        "filters",
        "title",
        "subtitle",
        "fit",
        # A map's axes, not encodings: the compiler decides which shelf each goes
        # on, because latitude-on-rows is a rule of the projection.
        "latitude",
        "longitude",
    }
)

TEMPLATE_REQUIREMENTS = {
    "bar": "rows + columns; the measure normally goes on columns",
    "line": "rows + columns; a date or continuous field on columns",
    "text_table": "rows; a measure on columns or label",
    "heatmap": "rows + columns + a measure on color",
    "scatter": "aggregated measures on BOTH rows and columns",
    "circle": "rows + columns",
    "map": (
        "latitude + longitude (inferred from column names when omitted), plus at least "
        "one dimension on detail/color/label so each location gets its own mark"
    ),
}


def supported_encodings() -> list[str]:
    """Visual encodings, derived from the Worksheet spec model."""
    return sorted(
        f.name for f in dataclass_fields(Worksheet) if f.name not in _NON_ENCODING_WORKSHEET_FIELDS
    )


def dashboards_supported() -> bool:
    """True when the spec model can actually carry dashboards."""
    try:
        from .models.spec import Dashboard, WorkbookSpec  # noqa: F401
    except ImportError:
        return False
    return any(f.name == "dashboards" for f in dataclass_fields(WorkbookSpec))


def describe_capabilities() -> dict[str, Any]:
    """The payload behind ``get_authoring_capabilities``."""
    supported: dict[str, Any] = {
        "data_sources": ["csv (always materialised into a .hyper extract)"],
        "worksheet_templates": list(SUPPORTED_TEMPLATES),
        "mark_classes": {t: MARK_CLASS[t] for t in SUPPORTED_TEMPLATES},
        "encodings": supported_encodings(),
        "aggregations": list(AGGREGATIONS),
        "canvas_fit": list(FIT_MODES),
        "calculated_fields": True,
        "categorical_filters": (
            "dimensions only. A filter on a measure is rejected: the compiler can only "
            "emit a categorical filter, which over a measure produces a value picker "
            "listing every distinct number. Band the measure with a calculated_field "
            "and filter that instead."
        ),
        "geographic_roles": (
            "latitude/longitude columns are detected by name and tagged with the "
            "[Geographical] semantic role, which is what puts a background map "
            "behind the 'map' template"
        ),
        "titles_and_subtitles": True,
        "packaging": [".twb", ".twbx"],
    }
    if dashboards_supported():
        supported["dashboards"] = (
            "worksheets tiled in one horizontal or vertical container, optional title, "
            "fixed or automatic canvas size"
        )

    unsupported: dict[str, str] = {
        "stories": "not implemented",
        "parameters": "not implemented",
        "lod_expressions": "not implemented",
        "joins_and_custom_sql": "not implemented",
        "sets_groups_hierarchies": "not implemented",
        "table_calculations": "not implemented",
        "reference_lines": "not implemented",
        "live_connections": (
            "impossible: Tableau Public rejects non-extract data sources (Error 3C242D89)"
        ),
        "map_extras": (
            "filled/choropleth maps, custom territories, map layers, spatial files "
            "and custom geocoding are not generated; the 'map' template plots "
            "latitude/longitude symbol marks on Tableau's background map"
        ),
        "dashboard_extras": (
            "filter cards, colour legends, highlighters, parameter controls, images, "
            "floating zones, device layouts and dashboard actions are not generated"
        ),
    }
    if not dashboards_supported():
        unsupported["dashboards"] = "not implemented"

    return {
        "spec_version": SPEC_VERSION,
        "supported": supported,
        "unsupported": unsupported,
        "notes": [
            "Every capability listed as supported has been confirmed by opening a "
            "generated workbook in Tableau Public 2026.2.0, not merely by producing XML.",
            "Publishing requires the desktop app, a signed-in session, and macOS "
            "Accessibility permission. It cannot run headless or in CI.",
            "The .twb is byte-deterministic for an identical spec; the .twbx is not, "
            "because the embedded Hyper extract carries non-deterministic state.",
        ],
    }


def describe_templates() -> list[dict[str, str]]:
    """The payload behind ``list_workbook_templates``."""
    return [
        {
            "name": t,
            "mark_class": MARK_CLASS[t],
            "requires": TEMPLATE_REQUIREMENTS.get(t, "rows + columns"),
        }
        for t in SUPPORTED_TEMPLATES
    ]
