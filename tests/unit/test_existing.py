"""Overwrite-protection tests for publishing.existing.

Every network call is mocked — a test suite must never touch the real Tableau
Public, and must certainly never publish. The primary fixtures below are the
**verbatim response bodies** captured from
``https://public.tableau.com/public/apis/workbooks?profileName=demo.analyst&start=0&count=2&visibility=NON_HIDDEN``
(and ``start=2``) on 2026-07-27, so the parser is exercised against the shape
the API really returns rather than an idealised one.
"""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from tableau_public_authoring.publishing import existing
from tableau_public_authoring.publishing.existing import (
    PROFILE_URL_TEMPLATE,
    CollisionResult,
    ProfileLookupError,
    PublishedWorkbook,
    assert_safe_to_publish,
    list_published_workbooks,
    name_collides,
    normalize_workbook_name,
)

PROFILE = "demo.analyst"

# --- real captured API responses -------------------------------------------
# Verbatim bytes from the live endpoint (start=0&count=2, then start=2&count=2).

REAL_PAGE_0 = (
    '{"contents":[{"workbookRepoUrl":"MCP_Authoring_Validation_-_20260727-0050",'
    '"title":"MCP_Authoring_Validation_-_20260727-0050",'
    '"defaultViewName":"Readiness by Site","viewCount":4,"numberOfFavorites":0,'
    '"authorDisplayName":"Demo Analyst",'
    '"authorProfileName":"demo.analyst",'
    '"defaultViewRepoUrl":"MCP_Authoring_Validation_-_20260727-0050/sheets/'
    'ReadinessbySite"},'
    '{"workbookRepoUrl":"Quarterly_Sales_Review",'
    '"title":"Quarterly_Sales_Review",'
    '"defaultViewName":"Matrix - Action Decision Quadrant","viewCount":1078,'
    '"numberOfFavorites":0,"authorDisplayName":"Demo Analyst",'
    '"authorProfileName":"demo.analyst",'
    '"defaultViewRepoUrl":"Quarterly_Sales_Review/sheets/'
    'Matrix-ActionDecisionQuadrant"}],'
    '"startIndex":0,"nextIndex":2,"next":2,"current":0}'
)

REAL_PAGE_1 = (
    '{"contents":[{"workbookRepoUrl":"FindingsbyEntityTypeFY2023-2024_17687247871180",'
    '"title":"Findings by Entity Type FY2023-2024",'
    '"defaultViewName":"Findings by Entity Type","viewCount":140,"numberOfFavorites":0,'
    '"authorDisplayName":"Demo Analyst",'
    '"authorProfileName":"demo.analyst",'
    '"defaultViewRepoUrl":"FindingsbyEntityTypeFY2023-2024_17687247871180/sheets/'
    'FindingsbyEntityType"},'
    '{"workbookRepoUrl":"CardA-Visuals1","title":"Card A -  Visuals1",'
    '"defaultViewName":"Top 10 States Receive 50.9% of All Federal Grants","viewCount":206,'
    '"numberOfFavorites":0,"authorDisplayName":"Demo Analyst",'
    '"authorProfileName":"demo.analyst",'
    '"defaultViewRepoUrl":"CardA-Visuals1/sheets/Top10StatesReceive50_9ofAllFederalGrants"}],'
    '"startIndex":2,"nextIndex":4,"next":4,"current":2}'
)

REAL_LAST_PAGE = '{"contents":[],"startIndex":4,"nextIndex":-1,"next":-1,"current":4}'

# The real 404 body for a profile that does not exist.
REAL_404_BODY = '{"error":{"message":"No entity found!","id":"e55d2239 jEZnbaSh"}}'


class _FakeResponse(io.BytesIO):
    """Minimal stand-in for the context manager urlopen returns."""

    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()
        return False


def install_pages(monkeypatch, bodies, *, recorder=None):
    """Serve ``bodies`` in order to successive urlopen calls."""
    queue = list(bodies)

    def fake_urlopen(req, timeout=None):
        if recorder is not None:
            recorder.append(req.full_url)
        if not queue:
            raise AssertionError(f"unexpected extra request: {req.full_url}")
        return _FakeResponse(queue.pop(0).encode("utf-8"))

    monkeypatch.setattr(existing.urllib.request, "urlopen", fake_urlopen)
    return queue


def install_failure(monkeypatch, exc):
    def fake_urlopen(req, timeout=None):
        raise exc

    monkeypatch.setattr(existing.urllib.request, "urlopen", fake_urlopen)


# --- parsing against the real response shape -------------------------------


def test_parses_real_api_response_shape(monkeypatch):
    install_pages(monkeypatch, [REAL_PAGE_0, REAL_LAST_PAGE.replace('"startIndex":4', '"x":4')])
    # Page 0's nextIndex is 2, so a second request happens; serve an empty page.
    books = list_published_workbooks(PROFILE)

    assert [b.title for b in books] == [
        "MCP_Authoring_Validation_-_20260727-0050",
        "Quarterly_Sales_Review",
    ]
    ev = books[1]
    assert isinstance(ev, PublishedWorkbook)
    assert ev.repo_url == "Quarterly_Sales_Review"
    assert ev.default_view_name == "Matrix - Action Decision Quadrant"
    assert ev.view_count == 1078
    assert ev.direct_url == (
        "https://public.tableau.com/app/profile/demo.analyst/viz/"
        "Quarterly_Sales_Review/Matrix-ActionDecisionQuadrant"
    )
    assert ev.to_dict()["view_count"] == 1078


def test_pagination_walks_every_page(monkeypatch):
    seen: list[str] = []
    install_pages(monkeypatch, [REAL_PAGE_0, REAL_PAGE_1, REAL_LAST_PAGE], recorder=seen)

    books = list_published_workbooks(PROFILE)

    assert len(books) == 4, "all three pages must be consumed, not just the first"
    assert [b.repo_url for b in books] == [
        "MCP_Authoring_Validation_-_20260727-0050",
        "Quarterly_Sales_Review",
        "FindingsbyEntityTypeFY2023-2024_17687247871180",
        "CardA-Visuals1",
    ]
    assert len(seen) == 3
    assert "start=0" in seen[0] and "start=2" in seen[1] and "start=4" in seen[2]
    assert all(u.startswith("https://public.tableau.com/public/apis/workbooks?") for u in seen)


# --- normalization ---------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        # Every pair below was observed live on public.tableau.com.
        ("Card A -  Visuals1", "CardA-Visuals1"),
        ("Findings by Entity Type FY2023-2024", "FindingsbyEntityTypeFY2023-2024"),
        ("Quarterly_Sales_Review", "Quarterly_Sales_Review"),
        ("Comet_DataRevelations_2019.1", "Comet_DataRevelations_2019_1"),
        ("2.9 SuperStore Demo", "2_9SuperStoreDemo"),
        ("It's Groundhog Day...again", "ItsGroundhogDay___again"),
        (
            "NATO Military Spending by Country as a % of GDP",
            "NATOMilitarySpendingbyCountryasaofGDP",
        ),
        (
            "Part-to-Whole Waterfall Chart That Shifts & Slides",
            "Part-to-WholeWaterfallChartThatShiftsSlides",
        ),
        ("Beyoncé's Grammys", "BeyoncesGrammys"),
        (
            "たぶ郎果物店 売上実績ダッシュボード For Tableau 9.0 Roadshow B",
            "ForTableau9_0RoadshowB",
        ),
    ],
)
def test_normalize_workbook_name_matches_observed_repo_urls(title, expected):
    assert normalize_workbook_name(title) == expected


# --- collision detection ---------------------------------------------------


def test_collides_on_exact_title(monkeypatch):
    install_pages(monkeypatch, [REAL_PAGE_0, REAL_LAST_PAGE])

    res = name_collides(PROFILE, "Quarterly_Sales_Review")

    assert isinstance(res, CollisionResult)
    assert res.collides is True
    assert res.matched_title == "Quarterly_Sales_Review"
    assert res.matched_url and res.matched_url.startswith("https://public.tableau.com/")
    assert res.checked_count == 2
    assert "exact title" in res.reason
    assert res.to_dict()["collides"] is True


@pytest.mark.parametrize("proposed", ["Card A - Visuals 1", "Card A - Visuals: 1!"])
def test_collides_on_normalized_form_when_titles_differ(monkeypatch, proposed):
    """'Card A -  Visuals1' is live; visually different titles normalise onto it."""
    install_pages(monkeypatch, [REAL_PAGE_1, REAL_LAST_PAGE])

    res = name_collides(PROFILE, proposed)

    assert proposed != "Card A -  Visuals1", "the titles must genuinely differ"
    assert res.collides is True
    assert res.matched_title == "Card A -  Visuals1"
    assert "CardA-Visuals1" in res.reason
    assert res.matched_url == (
        "https://public.tableau.com/app/profile/demo.analyst/viz/"
        "CardA-Visuals1/Top10StatesReceive50_9ofAllFederalGrants"
    )


def test_collides_when_repo_url_carries_a_uniquifier_suffix(monkeypatch):
    """The live repo URL has a ``_17687247871180`` suffix; the base still collides."""
    install_pages(monkeypatch, [REAL_PAGE_1, REAL_LAST_PAGE])

    res = name_collides(PROFILE, "Findings by Entity Type FY2023-2024")

    assert res.collides is True
    assert res.matched_title == "Findings by Entity Type FY2023-2024"


def test_no_collision_on_a_genuinely_new_name(monkeypatch):
    install_pages(monkeypatch, [REAL_PAGE_0, REAL_PAGE_1, REAL_LAST_PAGE])

    res = name_collides(PROFILE, "Quarterly Fleet Utilisation 2027")

    assert res.collides is False
    assert res.matched_title is None
    assert res.matched_url is None
    assert res.checked_count == 4


def test_assert_safe_to_publish_blocks_a_collision(monkeypatch):
    install_pages(monkeypatch, [REAL_PAGE_0, REAL_LAST_PAGE])

    ok, message = assert_safe_to_publish(
        PROFILE, "Quarterly_Sales_Review", overwrite=False
    )

    assert ok is False
    assert "Quarterly_Sales_Review" in message
    assert "https://public.tableau.com/app/profile/" in message, "must name the live URL"
    assert "overwrite=true" in message, "must tell the user their options"
    assert "different name" in message


def test_overwrite_true_permits_a_collision(monkeypatch):
    install_pages(monkeypatch, [REAL_PAGE_0, REAL_LAST_PAGE])

    ok, message = assert_safe_to_publish(
        PROFILE, "Quarterly_Sales_Review", overwrite=True
    )

    assert ok is True
    assert "REPLACED" in message


def test_assert_safe_to_publish_allows_a_new_name(monkeypatch):
    install_pages(monkeypatch, [REAL_PAGE_0, REAL_PAGE_1, REAL_LAST_PAGE])

    ok, message = assert_safe_to_publish(PROFILE, "Totally New Workbook", overwrite=False)

    assert ok is True
    assert "no published workbook" in message


# --- fail-closed behaviour -------------------------------------------------


@pytest.mark.parametrize(
    "failure",
    [
        urllib.error.URLError("nodename nor servname provided"),
        TimeoutError("timed out"),
        urllib.error.HTTPError(
            "https://public.tableau.com/x", 503, "Service Unavailable", {}, None
        ),
    ],
)
def test_network_failure_fails_closed(monkeypatch, failure):
    install_failure(monkeypatch, failure)

    with pytest.raises(ProfileLookupError):
        list_published_workbooks(PROFILE)

    ok, message = assert_safe_to_publish(PROFILE, "Anything At All", overwrite=False)

    assert ok is False, "a failed lookup must never be reported as safe"
    assert "UNABLE TO VERIFY" in message
    assert "safe" not in message.lower(), "must not claim safety when the check did not run"
    assert "Refusing to publish" in message
    assert PROFILE_URL_TEMPLATE.format(profile=PROFILE) in message


def test_unknown_profile_fails_closed(monkeypatch):
    install_failure(
        monkeypatch,
        urllib.error.HTTPError(
            "https://public.tableau.com/public/apis/workbooks?profileName=nope",
            404,
            "Not Found",
            {},
            io.BytesIO(REAL_404_BODY.encode("utf-8")),
        ),
    )

    ok, message = assert_safe_to_publish("nope", "Anything", overwrite=False)

    assert ok is False
    assert "UNABLE TO VERIFY" in message


def test_malformed_body_fails_closed(monkeypatch):
    install_pages(monkeypatch, ["<html>maintenance</html>"])

    with pytest.raises(ProfileLookupError):
        list_published_workbooks(PROFILE)


def test_api_error_payload_fails_closed(monkeypatch):
    install_pages(monkeypatch, [json.dumps({"error": {"message": "must be <= 50"}})])

    with pytest.raises(ProfileLookupError) as exc:
        list_published_workbooks(PROFILE)
    assert "must be <= 50" in str(exc.value)


def test_overwrite_true_still_proceeds_when_lookup_fails(monkeypatch):
    install_failure(monkeypatch, urllib.error.URLError("offline"))

    ok, message = assert_safe_to_publish(PROFILE, "Anything", overwrite=True)

    assert ok is True
    assert "could not verify" in message


# --- transport safety ------------------------------------------------------


def test_non_https_url_is_rejected(monkeypatch):
    monkeypatch.setattr(
        existing, "WORKBOOKS_ENDPOINT", "http://public.tableau.com/public/apis/workbooks"
    )

    def fail(*_args, **_kwargs):
        raise AssertionError("urlopen must not be reached for a non-https URL")

    monkeypatch.setattr(existing.urllib.request, "urlopen", fail)

    with pytest.raises(ValueError, match="only https URLs"):
        list_published_workbooks(PROFILE)


def test_empty_profile_is_rejected():
    with pytest.raises(ProfileLookupError):
        list_published_workbooks("")
