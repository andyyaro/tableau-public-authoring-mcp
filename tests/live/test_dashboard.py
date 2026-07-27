"""A generated dashboard, opened in the real Tableau Public.

WHY THIS TEST IS THE MOST VALUABLE ONE IN THE TIER
--------------------------------------------------
Dashboard XML is the only part of the compiler that was reverse-engineered from
*old* fixtures (document version 18.1, written by Tableau 2019.4.3-2023.1.0)
rather than from a workbook the target build wrote. The compiler's own docstring
names the single largest assumption:

    "The specific worry is ``type-v2``: the attribute appears in zero fixtures
     across document versions 8.3/10.4/18.1, so plain ``type`` is emitted; if
     2026.2.0 requires ``type-v2`` every zone here is rejected."

That assumption currently holds. Nothing in the unit suite can notice if a future
Tableau release stops honouring it, because the file would still be well-formed,
still pass structural validation, and still be byte-deterministic. It would just
refuse to load, or load with empty boxes where the worksheets should be.

So this file checks both halves of that:
  * the workbook opens with no error dialog (catches a rejected zone attribute);
  * EACH zone's slice of the canvas has marks in it (catches the quieter
    failure, where a zone's worksheet reference does not resolve and Tableau
    silently draws an empty rectangle - see docs/LIMITATIONS.md §8).

The compiler marks the first dashboard's ``<window>`` maximized whenever a
dashboard exists, so Tableau opens showing the dashboard rather than a worksheet.
That is what makes a screenshot of the document window a screenshot of the
dashboard.
"""

from __future__ import annotations

from typing import Any

import pytest

from .canvas import DASHBOARD_CANVAS, MIN_CHROMA_RATIO, MIN_INK_RATIO, CropBox, analyse_png
from .conftest import make_live_spec

pytestmark = pytest.mark.live


# Two side-by-side zones, each measured on its own. The gap between 0.61 and
# 0.66 is the seam between the zones plus their 4-unit margins; leaving it out
# keeps a mark that straddles the boundary from being counted twice, and keeps
# either half from borrowing evidence from the other.
LEFT_ZONE = CropBox(left=0.32, top=0.30, right=0.61, bottom=0.90)
RIGHT_ZONE = CropBox(left=0.66, top=0.30, right=0.96, bottom=0.90)

BAR_SHEET: dict[str, Any] = {
    "name": "Dash Bar",
    "template": "bar",
    "data_source": "sites",
    "rows": ["Site Name"],
    "columns": [{"field": "Readiness Score", "aggregation": "Sum"}],
    "color": "Status",
    "title": "Readiness by site",
}

HEATMAP_SHEET: dict[str, Any] = {
    "name": "Dash Heatmap",
    "template": "heatmap",
    "data_source": "sites",
    "rows": ["State"],
    "columns": ["Status"],
    "color": {"field": "Readiness Score", "aggregation": "Sum"},
    "title": "Readiness by state and status",
}


def _dashboard_spec(live_env, slug: str, **dashboard_overrides: Any) -> dict[str, Any]:
    dashboard: dict[str, Any] = {
        "name": "Readiness Overview",
        "title": "EV readiness overview",
        "direction": "horizontal",
        "worksheets": [BAR_SHEET["name"], HEATMAP_SHEET["name"]],
    }
    dashboard.update(dashboard_overrides)
    return make_live_spec(
        live_env,
        slug,
        [BAR_SHEET, HEATMAP_SHEET],
        dashboards=[dashboard],
    )


def test_dashboard_opens_and_both_zones_render(live_env, open_and_capture):
    """Two worksheets on one automatic-sized dashboard, both drawing marks.

    ``sizing_mode='automatic'`` is used rather than a fixed pixel canvas so the
    dashboard fits whatever window Tableau opens. A fixed 1200x800 canvas in a
    narrower window is shown at actual size with scrollbars, which clips the
    right-hand zone off screen and would make the per-zone check report a
    rendering failure that is really a viewport artefact.
    """
    render = open_and_capture(
        _dashboard_spec(live_env, "dashboard", sizing_mode="automatic"),
        crop=DASHBOARD_CANVAS,
    )

    assert render.opened, render.explain(
        "Tableau refused to open a workbook containing a generated dashboard. If the error "
        "names a zone attribute or element, the dashboard content model has changed - the "
        "prime suspect is 'type-v2' on <zone> (see this module's docstring)."
    )
    assert render.error is None, render.explain(
        "Tableau showed an error dialog for the dashboard workbook."
    )
    assert render.stats is not None, render.explain("could not screenshot the dashboard window.")

    stats = render.stats
    assert stats.ink_ratio >= MIN_INK_RATIO, render.explain(
        f"the dashboard canvas is blank: ink ratio {stats.ink_ratio:.5f} < "
        f"{MIN_INK_RATIO:.5f}. The workbook opened and Tableau reported no error, so the "
        f"zones were accepted and then drew nothing."
    )

    left = analyse_png(render.screenshot, LEFT_ZONE)
    right = analyse_png(render.screenshot, RIGHT_ZONE)
    for label, zone_stats in (("left", left), ("right", right)):
        assert zone_stats.ink_ratio >= MIN_INK_RATIO, render.explain(
            f"the {label} dashboard zone is empty ({zone_stats.describe()}). A zone whose "
            f"worksheet reference does not resolve loads without complaint and renders an "
            f"empty box - that is what this looks like."
        )
        assert zone_stats.chroma_ratio >= MIN_CHROMA_RATIO, render.explain(
            f"the {label} dashboard zone drew its frame and caption but no coloured marks "
            f"({zone_stats.describe()})."
        )


def test_fixed_size_dashboard_opens_and_renders(live_env, open_and_capture):
    """The documented shape: an explicit 1200x800 pixel canvas.

    Fixed sizing is worth its own case because it is the one place two different
    coordinate systems meet: ``<size>`` bounds are PIXELS while zone x/y/w/h are
    units of a 0..100000 grid. Confusing them puts zones off by two orders of
    magnitude, and Tableau reports that by drawing something wrong rather than by
    failing to load.

    Only the whole canvas is measured here, not the individual zones: a fixed
    canvas wider than the viewport is scrolled rather than scaled, so the right
    zone may legitimately sit off screen.
    """
    render = open_and_capture(
        _dashboard_spec(live_env, "dashfixed", sizing_mode="fixed", width=1200, height=800),
        crop=DASHBOARD_CANVAS,
    )

    assert render.opened, render.explain("Tableau refused to open the fixed-size dashboard.")
    assert render.error is None, render.explain(
        "Tableau showed an error dialog for the fixed-size dashboard workbook."
    )
    assert render.stats is not None, render.explain("could not screenshot the dashboard window.")
    assert render.stats.ink_ratio >= MIN_INK_RATIO, render.explain(
        f"the fixed-size dashboard canvas is blank: ink ratio "
        f"{render.stats.ink_ratio:.5f} < {MIN_INK_RATIO:.5f}."
    )
