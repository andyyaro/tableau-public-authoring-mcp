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
    (
        "map",
        {
            "name": "Map Sites",
            "template": "map",
            "data_source": "sites",
            # latitude/longitude are deliberately NOT specified: inferring them
            # from the column names is the documented default, so the live tier
            # exercises the path callers will actually use.
            "detail": ["Site Name"],
            "color": "Status",
            "size": {"field": "Annual Sessions", "aggregation": "Sum"},
            "title": "Candidate sites",
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


# THE DRIFT CHECK OVER ``TEMPLATE_CASES`` IS NOT IN THIS FILE.
#
# ``test_every_supported_template_has_a_live_render_case`` lives in
# tests/unit/test_coverage_gaps.py and imports the table above. It is pure logic
# with no GUI dependency, and here it never ran: this module is marked ``live``,
# so a default ``pytest`` deselected it and the one test whose entire job is to
# notice a new template arriving without a live case only executed on the runs
# that were already driving Tableau. Anything else that only reads the table
# belongs there too - put a test here only if it opens a window.
