"""The publish mechanism, proven WITHOUT ever publishing.

THIS FILE MUST NEVER PUBLISH ANYTHING. Publishing is irreversible and
world-visible. Every test here stops at the "Save Workbook to Tableau Public"
dialog and dismisses it with Escape, and an autouse tripwire replaces every
function that could confirm that dialog with something that raises. The tests are
marked ``live`` AND ``publish`` so both marker filters exclude them.

What is actually asserted, and why each one is worth a GUI test:

1. ``assert_target_frontmost`` refuses when the named workbook is not the active
   document, and says "SAFETY ABORT" when it does. This is the guard standing
   between "publish this test workbook" and "publish whatever the user happens to
   have open", so its refusal path deserves a real test with real windows.
2. ``Command+Shift+S`` opens the save dialog. The keyboard shortcut replaced menu
   automation after clicking the menu item proved unworkable even with correct
   coordinates (docs/LIMITATIONS.md §9). Nothing but a live run can tell you that
   Tableau still maps that shortcut.
3. The dialog *settles*: it is first reported at ~126x100 while it animates and is
   then re-created with a DIFFERENT window id at ~382x191. Acting on the first
   sighting clicked a window that had already been destroyed
   (docs/LIMITATIONS.md §10), so ``wait_for_stable_dialog`` must still return a
   plausible, stable size.
4. ``cancel_save_dialog`` dismisses it. It presses Escape rather than clicking
   Cancel, because a measured Cancel click left the dialog on screen.
"""

from __future__ import annotations

from typing import Any

import pytest

from tableau_public_authoring.desktop import tableau_app, window_control
from tableau_public_authoring.publishing import publisher

from .conftest import make_live_spec

pytestmark = [pytest.mark.live, pytest.mark.publish]


PUBLISH_SHEET: dict[str, Any] = {
    # Tableau disables "Save to Tableau Public" for a viz with no fields on any
    # shelf, so the dialog under test would never appear for an empty worksheet.
    "name": "Publish Probe",
    "template": "bar",
    "data_source": "sites",
    "rows": ["Site Name"],
    "columns": [{"field": "Readiness Score", "aggregation": "Sum"}],
    "color": "Status",
    "title": "Publish-flow probe (never published)",
}


@pytest.fixture(autouse=True)
def never_confirm_the_dialog(monkeypatch):
    """Tripwire: make it impossible for this module to complete a publication.

    ``publish`` drives the whole flow, ``click_dialog_button`` is what presses
    Save, and ``set_dialog_title`` types into the dialog. None of them has any
    business running here, and a future edit that reaches for one should fail
    loudly rather than upload a workbook to a public profile.
    """

    def boom(*args, **kwargs):
        raise AssertionError(
            "the publish tier must never confirm the save dialog; it stops at the dialog "
            "and cancels with Escape"
        )

    monkeypatch.setattr(publisher, "publish", boom)
    monkeypatch.setattr(publisher, "click_dialog_button", boom)
    monkeypatch.setattr(publisher, "set_dialog_title", boom)


@pytest.fixture(scope="module")
def publish_target(live_env, open_and_capture):
    """One workbook, opened once, reused by every test in this module."""
    render = open_and_capture(make_live_spec(live_env, "publish", [PUBLISH_SHEET]))
    if not render.opened:
        pytest.fail(render.explain("the publish-flow probe workbook did not open"))
    return render


def _frontmost_application() -> str | None:
    """Name of the frontmost *application*, not the frontmost Tableau window.

    This distinction is the whole reason the function exists. ``real_key`` posts a
    genuine HID event to the system event tap, which is delivered to whatever
    application is active - if that is the terminal running pytest, Command+Shift+S
    is delivered to the terminal instead. Tableau's own window ordering says
    nothing about that, so it is checked separately before any key is sent.
    """
    try:
        return tableau_app.osascript(
            'tell application "System Events" to return name of first application process '
            "whose frontmost is true"
        )
    except tableau_app.DesktopError:
        return None


def _raise_target(render) -> None:
    """Make the probe workbook the active document, or fail without touching input."""
    ok, why = window_control.unminimize_and_raise(render.stem, file_path=render.workbook)
    if not ok:
        pytest.fail(
            f"could not make {render.stem!r} the frontmost document ({why}). Refusing to "
            f"continue: every later step in this module would be aimed at the wrong workbook."
        )


def test_frontmost_guard_confirms_the_intended_workbook(publish_target):
    """Positive control for the precondition that gates every publish."""
    _raise_target(publish_target)

    titles = [w["title"] for w in publisher.document_windows()]
    front = publisher.frontmost_window_title()
    assert front is not None, (
        f"no Tableau document window is on screen, yet the probe workbook was opened. "
        f"Windows seen: {titles}"
    )

    ok, why = publisher.assert_target_frontmost(publish_target.stem)
    assert ok, (
        f"the frontmost-workbook guard rejected the workbook that IS frontmost: {why}. "
        f"frontmost={front!r} stem={publish_target.stem!r} documents={titles}"
    )


def test_frontmost_guard_refuses_when_the_wrong_workbook_is_active(publish_target):
    """The refusal path, with the exact wording callers are told to look for.

    A name that is deliberately not open stands in for "the user's own workbook is
    in front". The guard must refuse, and must say SAFETY ABORT while doing it -
    the string is what makes an aborted publish legible in a tool response.
    """
    _raise_target(publish_target)

    absent = f"{publish_target.stem}_definitely_not_open"
    ok, why = publisher.assert_target_frontmost(absent)

    assert not ok, (
        f"the guard approved publishing {absent!r}, which is not open at all. "
        f"Frontmost is {publisher.frontmost_window_title()!r}. This guard is the only thing "
        f"stopping a publish command from being dispatched to the wrong document."
    )
    assert "SAFETY ABORT" in why, (
        f"the guard refused, but without the SAFETY ABORT marker callers match on. "
        f"Message was: {why!r}"
    )


def test_no_sign_in_window_is_reported_when_none_is_showing(publish_target):
    """A stale window-server entry must not resurrect a closed sign-in window.

    ``kCGWindowListOptionAll`` reports windows that no longer exist, which once
    produced a permanent false "sign-in required" by matching a 59x112 husk of a
    closed sign-in window (docs/LIMITATIONS.md §10). The detector now requires an
    on-screen window of a plausible size, so with no sign-in in progress it must
    say False.
    """
    assert publisher.detect_sign_in_required() is False, (
        "detect_sign_in_required() reported a sign-in window while none was in progress. "
        "If Tableau really is showing one, complete or dismiss it and re-run; otherwise the "
        "on-screen/min-area filter has regressed to matching destroyed windows."
    )


def test_shortcut_opens_a_stable_save_dialog_that_escape_dismisses(publish_target):
    """Command+Shift+S -> dialog appears -> dialog settles -> Escape closes it.

    NOTHING IS PUBLISHED. The Save button is never located, never clicked, and
    ``click_dialog_button`` is replaced by a tripwire for the duration.
    """
    _raise_target(publish_target)

    ok, why = publisher.assert_target_frontmost(publish_target.stem)
    assert ok, f"refusing to send a publish shortcut: {why}"

    front_app = _frontmost_application()
    assert front_app == tableau_app.PROCESS_NAME, (
        f"the frontmost application is {front_app!r}, not {tableau_app.PROCESS_NAME!r}. "
        f"Command+Shift+S is posted to the system event tap and would be delivered to "
        f"{front_app!r} instead. Refusing to send it."
    )

    dialog = None
    settled = None
    try:
        tableau_app.real_key(tableau_app.VK_ANSI_S, command=True, shift=True)

        dialog = publisher.wait_for_stable_dialog(publisher.SAVE_DIALOG_TITLE, timeout=40.0)
        if dialog is None and publisher.detect_sign_in_required():
            pytest.skip(
                "Tableau is asking for sign-in, so the save dialog never appeared. The "
                "publish tier needs an already signed-in Tableau Public session; sign in "
                "manually and re-run. This server never types credentials."
            )

        assert dialog is not None, (
            f"{publisher.SAVE_DIALOG_TITLE!r} did not appear within 40s of Command+Shift+S. "
            f"Either Tableau no longer maps that shortcut to 'Save to Tableau Public As...' "
            f"(the menu fallback in invoke_save_to_public is then the only path left), or the "
            f"workbook has no field on a shelf and Tableau disabled the command. "
            f"On-screen Tableau windows: {[w['title'] for w in publisher.onscreen_windows()]}"
        )

        area = int(dialog["width"]) * int(dialog["height"])
        assert area >= 20_000, (
            f"the save dialog was found at {dialog['width']}x{dialog['height']} "
            f"({area}px), which is the transient animating window, not the settled one. "
            f"Acting on that size previously aimed clicks at an already-destroyed window."
        )

        # Settled means the bounds stop changing. wait_for_stable_dialog only
        # returns after two matching reads; this re-read proves it is still that
        # size a moment later, i.e. the animation really has finished.
        settled = publisher.find_named_window(publisher.SAVE_DIALOG_TITLE, timeout=2.0)
        assert settled is not None, "the save dialog vanished immediately after settling"
        assert (int(settled["width"]), int(settled["height"])) == (
            int(dialog["width"]),
            int(dialog["height"]),
        ), (
            f"the save dialog is still resizing: {dialog['width']}x{dialog['height']} then "
            f"{settled['width']}x{settled['height']}"
        )
    finally:
        # Always dismiss, even if an assertion above failed: leaving a modal
        # publish dialog on a user's screen is not an acceptable failure mode.
        cancelled = publisher.cancel_save_dialog()

    assert cancelled, (
        "cancel_save_dialog() reported that the dialog was still on screen after Escape. "
        "It uses Escape precisely because clicking Cancel was measured to leave the dialog "
        "up; if Escape has stopped working there is no safe way to back out of the publish "
        "flow. Check Tableau for an open 'Save Workbook to Tableau Public' dialog NOW."
    )
    assert publisher.find_named_window(publisher.SAVE_DIALOG_TITLE, timeout=1.0) is None, (
        "the save dialog is still on screen after cancel_save_dialog() reported success."
    )
