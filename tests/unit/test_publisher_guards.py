"""The guards standing between a tool call and an irreversible public upload.

Publishing cannot be undone: the workbook becomes world-readable, and an
overwrite replaces something the user already had online. Every check in this
file existed in some form and did not actually hold.

No test here touches the GUI or the network - every OS and HTTP call is patched.
"""

from __future__ import annotations

import pytest

from tableau_public_authoring.publishing import publisher


@pytest.fixture(autouse=True)
def no_real_os_calls(monkeypatch):
    """Any escape to the real OS layer fails loudly rather than driving Tableau."""

    def tripwire(name):
        def _boom(*_a, **_k):
            raise AssertionError(f"unit test reached the real OS layer via {name}()")

        return _boom

    for name in ("osascript", "real_click", "real_key", "screenshot_window", "activate_app"):
        monkeypatch.setattr(publisher, name, tripwire(name), raising=False)


# --- the frontmost precondition ---------------------------------------------


def test_a_longer_name_containing_the_target_is_refused(monkeypatch):
    """The wrong-workbook publish.

    'Q3_Sales' requested, 'Q3_Sales_Draft' frontmost. A substring test passes,
    and the draft goes to the public internet under the intended name -- reported
    as success. close_document already required an exact match for the
    *recoverable* operation of the two.
    """
    monkeypatch.setattr(
        publisher, "frontmost_window_title", lambda: "Tableau Public - Q3_Sales_Draft"
    )
    ok, why = publisher.assert_target_frontmost("Q3_Sales")
    assert ok is False
    assert "SAFETY ABORT" in why
    assert "differs only by a suffix" in why


def test_an_exact_match_is_accepted(monkeypatch):
    monkeypatch.setattr(publisher, "frontmost_window_title", lambda: "Tableau Public - Q3_Sales")
    assert publisher.assert_target_frontmost("Q3_Sales")[0] is True


def test_underscore_and_space_still_compare_equal(monkeypatch):
    """Tableau shows underscores in titles while humans type spaces."""
    monkeypatch.setattr(publisher, "frontmost_window_title", lambda: "Tableau Public - Q3_Sales")
    assert publisher.assert_target_frontmost("Q3 Sales")[0] is True


def test_an_unreadable_frontmost_window_refuses(monkeypatch):
    monkeypatch.setattr(publisher, "frontmost_window_title", lambda: None)
    assert publisher.assert_target_frontmost("Q3_Sales")[0] is False


def test_a_minimized_dock_tile_is_never_the_frontmost_document(monkeypatch):
    """A minimized document keeps its title and stays on-screen as a ~140x190 tile.

    It cannot receive the menu command, so treating it as frontmost lets the
    precondition "confirm" a workbook that cannot be published.
    """
    monkeypatch.setattr(
        publisher,
        "document_windows",
        lambda: [
            {"id": 1, "title": "Tableau Public - Minimized", "x": 16, "y": 142,
             "width": 140, "height": 190},
            {"id": 2, "title": "Tableau Public - Real", "x": 221, "y": 33,
             "width": 1291, "height": 949},
        ],
    )
    assert publisher.frontmost_window_title() == "Tableau Public - Real"


# --- sign-in detection -------------------------------------------------------


def test_a_workbook_named_like_a_sign_in_page_does_not_trigger_sign_in(monkeypatch):
    """'Customer_Log_In_Funnel' matched the 'log in' hint against its own window.

    Its document window is ~1.2M px^2, so it cleared the area test easily, and an
    already-authenticated user was told to authenticate -- forever.
    """

    class FakeQuartz:
        kCGWindowListOptionOnScreenOnly = 1
        kCGWindowListExcludeDesktopElements = 2
        kCGNullWindowID = 0

        @staticmethod
        def CGWindowListCopyWindowInfo(*_a):
            return [
                {
                    "kCGWindowOwnerName": "Tableau Public",
                    "kCGWindowName": "Tableau Public - Customer_Log_In_Funnel",
                    "kCGWindowBounds": {"Width": 1291, "Height": 949},
                }
            ]

    monkeypatch.setitem(__import__("sys").modules, "Quartz", FakeQuartz)
    assert publisher.detect_sign_in_required() is False


def test_a_real_sign_in_window_is_still_detected(monkeypatch):
    class FakeQuartz:
        kCGWindowListOptionOnScreenOnly = 1
        kCGWindowListExcludeDesktopElements = 2
        kCGNullWindowID = 0

        @staticmethod
        def CGWindowListCopyWindowInfo(*_a):
            return [
                {
                    "kCGWindowOwnerName": "Tableau Public",
                    "kCGWindowName": "Sign In to Tableau Public",
                    "kCGWindowBounds": {"Width": 500, "Height": 648},
                }
            ]

    monkeypatch.setitem(__import__("sys").modules, "Quartz", FakeQuartz)
    assert publisher.detect_sign_in_required() is True


# --- proving a publish actually happened ------------------------------------


class _WB:
    def __init__(self, title, repo_url):
        self.title = title
        self.repo_url = repo_url
        self.direct_url = f"https://public.tableau.com/views/{repo_url}"


def _patch_listing(monkeypatch, workbooks):
    import tableau_public_authoring.publishing.existing as existing

    monkeypatch.setattr(existing, "list_published_workbooks", lambda _p: workbooks)


def test_a_brand_new_workbook_is_confirmed(monkeypatch):
    _patch_listing(monkeypatch, [_WB("My Viz", "My_Viz_123")])
    url, proved = publisher._await_published_url(
        "someone", "My Viz", timeout=1, known_before=set()
    )
    assert url.endswith("My_Viz_123")
    assert proved is True


def test_a_preexisting_workbook_is_not_mistaken_for_a_fresh_upload(monkeypatch):
    """The false-success bug, and it fired on EVERY overwrite.

    The poll matched on title alone and returned the first hit, so a workbook that
    was already there satisfied the very first iteration. The caller got a
    verified URL and published=True whether or not the upload succeeded.
    """
    _patch_listing(monkeypatch, [_WB("My Viz", "My_Viz_123")])
    url, proved = publisher._await_published_url(
        "someone", "My Viz", timeout=1, known_before={"My_Viz_123"}
    )
    assert url is not None, "the URL is still reported - it is the CLAIM that changes"
    assert proved is False, "a pre-existing workbook must never count as proof"


def test_without_a_before_snapshot_nothing_is_claimed(monkeypatch):
    """A failed snapshot must not silently become 'nothing was published'."""
    _patch_listing(monkeypatch, [_WB("My Viz", "My_Viz_123")])
    _url, proved = publisher._await_published_url(
        "someone", "My Viz", timeout=1, known_before=None
    )
    assert proved is False


def test_a_profile_snapshot_failure_returns_none_not_an_empty_set(monkeypatch):
    """None means 'could not ask'. An empty set would mean 'nothing is published',
    and would make the next publish claim confirmation it has not earned."""
    import tableau_public_authoring.publishing.existing as existing

    def boom(_p):
        raise RuntimeError("network down")

    monkeypatch.setattr(existing, "list_published_workbooks", boom)
    assert publisher._profile_repo_urls("someone") is None


# --- the failure message must match the code ---------------------------------


def test_the_save_dialog_timeout_is_a_single_source_of_truth():
    """The wait used 90s while the failure message said 30s."""
    import inspect

    src = inspect.getsource(publisher.publish)
    assert "SAVE_DIALOG_TIMEOUT" in src
    assert "within 30s" not in src
