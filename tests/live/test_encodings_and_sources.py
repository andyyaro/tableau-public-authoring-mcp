"""Two capabilities a unit test can describe but cannot confirm.

``tests/unit/test_coverage_gaps.py`` proves the compiler emits a ``<size>``
encoding and points each data source at its own ``Data/<id>/`` directory. Both
of those are statements about bytes. Neither settles the question
CAPABILITY_BOUNDARY.md actually claims - that Tableau Public *opened the file
and drew something* - and that gap is not hypothetical: two defects in this
project produced workbooks that loaded without a single complaint and rendered
an empty white pane. An encoding whose pill will not resolve is exactly that
shape of failure, and so is an extract the workbook looks for at a path the
package does not contain.

Both cases here therefore do what the template cases do: build, open, screenshot,
count ink in the canvas region.

Fields come from tests/fixtures/data/ev_site_readiness.csv (12 rows) and, for
the second source, ev_utilization.csv (16 rows). The two share no column name.
"""

from __future__ import annotations

import pytest

from .canvas import MIN_CHROMA_RATIO, MIN_INK_RATIO
from .conftest import FIXTURE_CSV_2, make_live_spec

pytestmark = pytest.mark.live


def _assert_drew_marks(render, what: str) -> None:
    """The same three-step judgement every live render case makes.

    Opened, no error dialog, and ink *with colour* on the canvas. The colour
    check is the one that matters here: a canvas carrying ink but no chroma is a
    sheet whose axes and headers drew and whose marks did not, which is what a
    pill that failed to resolve looks like.
    """
    assert render.opened, render.explain(f"Tableau did not open the {what} workbook.")
    assert render.error is None, render.explain(f"Tableau showed an error dialog for {what}.")
    assert render.stats is not None, render.explain(f"could not screenshot {what}.")

    stats = render.stats
    assert stats.ink_ratio >= MIN_INK_RATIO, render.explain(
        f"the canvas for {what} is blank: {stats.ink_ratio:.5f} of sampled pixels carry ink, "
        f"below the {MIN_INK_RATIO:.5f} floor. It opened and Tableau reported no error, so "
        f"this is the 'loads fine, renders nothing' failure. Open the screenshot and judge it "
        f"yourself before changing the threshold."
    )
    assert stats.chroma_ratio >= MIN_CHROMA_RATIO, render.explain(
        f"the canvas for {what} has ink but essentially no colour "
        f"({stats.chroma_ratio:.5f} < {MIN_CHROMA_RATIO:.5f}). Axis text and headers drew; the "
        f"marks did not."
    )


def test_a_size_encoded_worksheet_renders_its_marks(live_env, open_and_capture):
    """CAPABILITY_BOUNDARY.md: "circle radii vary with SUM(Annual Sessions)".

    The unit tier proves ``<size column='...[sum:Annual Sessions:qk]'/>`` is
    emitted and that the field it names is declared. What it cannot prove is
    that Tableau accepts the pill: an encoding referring to a field the sheet
    has not declared correctly renders red on the Marks card and the canvas
    stays empty, with no error dialog anywhere. That is a pixel question.

    Circle rather than map on purpose - a map draws a background tile layer, so
    its canvas has ink whether or not a single mark rendered.

    Twelve rows of states are what keeps these marks inside WORKSHEET_CANVAS
    under the default ``fit_width``; a shorter viz needs ``entire_view``, for
    the reason set out in the second-source case below.
    """
    render = open_and_capture(
        make_live_spec(
            live_env,
            "size",
            [
                {
                    "name": "Sized Circles",
                    "template": "circle",
                    "data_source": "sites",
                    "rows": ["State"],
                    "columns": [{"field": "Readiness Score", "aggregation": "Sum"}],
                    "size": {"field": "Annual Sessions", "aggregation": "Sum"},
                    "color": "Status",
                    "detail": ["Site Name"],
                    "title": "Readiness by state, sized by sessions",
                }
            ],
        )
    )
    _assert_drew_marks(render, "the size-encoded worksheet")


def test_a_second_data_source_loads_and_its_worksheet_renders(live_env, open_and_capture):
    """CAPABILITY_BOUNDARY.md: "two CSVs -> two .hyper extracts ...; both load".

    The sheet bound to the SECOND source is placed first, so it is the one
    Tableau maximizes and the one this screenshot judges. That is deliberate:
    the "Partially supported" table admits that the marks of a second-source
    sheet were never individually confirmed, because the first sheet is what a
    window screenshot shows and switching tabs is a GUI interaction this tier
    does not perform.

    The failure this is aimed at: every connection string built from
    ``data_sources[0]``, so the second source's extract is looked for at
    ``Data/sites/usage.hyper``. The package has no such entry, the workbook
    opens anyway, and the sheet renders nothing.
    """
    if not FIXTURE_CSV_2.exists():
        pytest.skip(f"the second fixture dataset is missing: {FIXTURE_CSV_2}")

    render = open_and_capture(
        make_live_spec(
            live_env,
            "twosources",
            [
                {
                    "name": "Uptime By Region",
                    "template": "bar",
                    "data_source": "usage",
                    "rows": ["Region"],
                    "columns": [{"field": "Uptime Percent", "aggregation": "Avg"}],
                    "color": "Region",
                    # Four bars under the default `fit_width` occupy a ~120px
                    # strip at the top of a 1100px pane, which lands ABOVE
                    # WORKSHEET_CANVAS's 0.30 top edge: measured 0.00214 ink and
                    # zero chroma on a screenshot that shows four correctly
                    # coloured bars, because the crop caught only the black axis
                    # labels underneath them. `entire_view` fills the pane, so
                    # the marks are where the analyser looks. The template cases
                    # do not need this only because twelve rows of sites are
                    # tall enough by accident.
                    "fit": "entire_view",
                    "title": "Uptime by region (second data source)",
                },
                {
                    "name": "Readiness By State",
                    "template": "bar",
                    "data_source": "sites",
                    "rows": ["State"],
                    "columns": [{"field": "Readiness Score", "aggregation": "Sum"}],
                    "title": "Readiness by state (first data source)",
                },
            ],
            data_sources=[
                {"id": "sites", "type": "csv", "path": str(live_env.csv)},
                {"id": "usage", "type": "csv", "path": str(FIXTURE_CSV_2)},
            ],
        )
    )
    _assert_drew_marks(render, "the worksheet bound to the second data source")
