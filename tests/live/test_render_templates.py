"""Every worksheet template, opened in Tableau Public, proven to draw marks.

This is the automated form of the check that found six load-blocking defects and
two "loads fine, renders blank" defects. Each case:

  spec -> .twbx -> `open -a Tableau Public` -> window appears -> no error dialog
       -> screenshot the window -> count ink in the canvas region

The last step is the one that cannot be replaced by a unit test. A workbook whose
data source silently resolves to nothing opens perfectly, reports no error, and
draws an empty white pane; only the pixels tell you.

Fields come from tests/fixtures/data/ev_site_readiness.csv (12 synthetic rows).
"""

from __future__ import annotations

from typing import Any

import pytest

from .canvas import MIN_CHROMA_RATIO, MIN_INK_RATIO
from .conftest import make_live_spec

pytestmark = pytest.mark.live


# (slug, worksheet, expects_colour)
#
# ``expects_colour`` says whether the template puts *coloured* pixels on the
# canvas. It is False only for text_table, whose marks are black text: for every
# other template a canvas with ink but no colour means the axes and headers drew
# and the marks did not, which is exactly the failure mode a plain "is it blank"
# check sails past.
TEMPLATE_CASES: list[tuple[str, dict[str, Any], bool]] = [
    (
        "bar",
        {
            "name": "Bar Readiness",
            "template": "bar",
            "data_source": "sites",
            "rows": ["Site Name"],
            "columns": [{"field": "Readiness Score", "aggregation": "Sum"}],
            "color": "Status",
            "label": {"field": "Readiness Score", "aggregation": "Sum"},
            "title": "Readiness by site",
        },
        True,
    ),
    (
        "line",
        {
            "name": "Line Sessions",
            "template": "line",
            "data_source": "sites",
            "rows": [{"field": "Annual Sessions", "aggregation": "Sum"}],
            "columns": ["Assessment Date"],
            "title": "Sessions over time",
        },
        True,
    ),
    (
        "text_table",
        {
            "name": "Table Chargers",
            "template": "text_table",
            "data_source": "sites",
            "rows": ["Site Name", "State"],
            "columns": [{"field": "Charger Count", "aggregation": "Sum"}],
            "title": "Chargers per site",
        },
        False,
    ),
    (
        "heatmap",
        {
            "name": "Heatmap Readiness",
            "template": "heatmap",
            "data_source": "sites",
            "rows": ["State"],
            "columns": ["Status"],
            "color": {"field": "Readiness Score", "aggregation": "Sum"},
            "title": "Readiness by state and status",
        },
        True,
    ),
    (
        "scatter",
        {
            "name": "Scatter Cost",
            "template": "scatter",
            "data_source": "sites",
            # Two aggregated measures alone would draw ONE dot for the whole
            # table. `detail` is what raises the level of detail to one mark per
            # site (docs/LIMITATIONS.md §6), and getting it wrong is invisible in
            # the XML but obvious on the canvas - 12 marks becomes 3, or 1.
            # This is also the sparsest canvas the tier measures, so it is the
            # calibration case for the pixel thresholds.
            "rows": [{"field": "Annual Sessions", "aggregation": "Sum"}],
            "columns": [{"field": "Estimated Cost", "aggregation": "Sum"}],
            "color": "Status",
            "detail": ["Site Name"],
            "title": "Cost against sessions",
        },
        True,
    ),
    (
        "circle",
        {
            "name": "Circle Readiness",
            "template": "circle",
            "data_source": "sites",
            "rows": ["State"],
            "columns": [{"field": "Readiness Score", "aggregation": "Sum"}],
            "title": "Readiness by state",
        },
        True,
    ),
]


@pytest.mark.parametrize(
    ("slug", "worksheet", "expects_colour"),
    TEMPLATE_CASES,
    ids=[case[0] for case in TEMPLATE_CASES],
)
def test_template_opens_and_renders(live_env, open_and_capture, slug, worksheet, expects_colour):
    """The template loads in Tableau Public and puts marks on the canvas."""
    render = open_and_capture(make_live_spec(live_env, slug, [worksheet]))

    assert render.opened, render.explain(
        f"Tableau did not open the {slug!r} workbook. If 'error' names an XML element or "
        f"attribute, the compiler has regressed against the loader's content model "
        f"(see tests/unit/test_dtd_regression.py and docs/LIMITATIONS.md §2)."
    )
    assert render.error is None, render.explain(
        f"Tableau showed an error dialog for the {slug!r} workbook."
    )
    assert render.stats is not None, render.explain(
        f"could not screenshot the {slug!r} workbook's window."
    )

    stats = render.stats
    assert stats.ink_ratio >= MIN_INK_RATIO, render.explain(
        f"the {slug!r} canvas is blank: {stats.ink_ratio:.5f} of sampled canvas pixels carry "
        f"ink, below the {MIN_INK_RATIO:.5f} floor. The workbook opened and Tableau reported "
        f"no error, so this is the 'loads fine, renders nothing' failure. Open the screenshot "
        f"and judge it yourself before changing the threshold."
    )
    if expects_colour:
        assert stats.chroma_ratio >= MIN_CHROMA_RATIO, render.explain(
            f"the {slug!r} canvas has ink but essentially no colour "
            f"({stats.chroma_ratio:.5f} < {MIN_CHROMA_RATIO:.5f}). Axis text and headers "
            f"drew; the marks did not."
        )


def test_all_supported_templates_are_covered():
    """The case table must not drift away from what the spec model advertises.

    A new template added to ``SUPPORTED_TEMPLATES`` without a live case here would
    be shipped on the strength of unit tests alone, which is precisely how the
    two blank-render defects reached a human.
    """
    from tableau_public_authoring.models.spec import SUPPORTED_TEMPLATES

    covered = {slug for slug, _, _ in TEMPLATE_CASES}
    assert covered == set(SUPPORTED_TEMPLATES), (
        f"live render coverage does not match SUPPORTED_TEMPLATES: "
        f"missing={sorted(set(SUPPORTED_TEMPLATES) - covered)}, "
        f"stale={sorted(covered - set(SUPPORTED_TEMPLATES))}"
    )
