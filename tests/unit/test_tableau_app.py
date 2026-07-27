"""Desktop-control tests for ``desktop.tableau_app`` — every OS call is faked.

Nothing here touches Quartz, osascript, the pasteboard, `open`, `screencapture`
or the Tableau GUI: the window server is a fake ``Quartz`` module injected into
``sys.modules``, and every subprocess/AppleScript entry point is replaced by a
tripwire (see :func:`no_real_os_calls`). Reaching the real OS layer is a test
failure, not a silent side effect on whatever window happens to be frontmost.

The window geometry below is the geometry documented in ``window_control.py``:
a restored document is 1291x949 at (221, 33); a husk of a CLOSED document is
218x161 at (-234, 367) and appears only in the all-windows list.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from tableau_public_authoring.desktop import tableau_app as app

# --- tripwires --------------------------------------------------------------


#: Captured before the tripwire fixture replaces them, so the two tests that check
#: the pasteboard wrappers themselves can still reach the real implementations.
REAL_PBPASTE = app._pbpaste
REAL_PBCOPY = app._pbcopy


class QuartzTripwire:
    """Stands in for the pyobjc ``Quartz`` module until a test supplies a fake."""

    def __getattr__(self, name):
        # `import Quartz` asks the sys.modules entry for __spec__ and friends; only
        # a real CoreGraphics call is a test failure.
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        raise AssertionError(f"unit test reached the real window server via Quartz.{name}")


@pytest.fixture(autouse=True)
def no_real_os_calls(monkeypatch):
    """Hard guarantee that no test in this file can touch the GUI or clipboard.

    Every real entry point becomes a tripwire, so a code path that falls back to a
    default instead of the injected fake fails loudly here rather than running
    AppleScript against the user's Tableau, reading their pasteboard, or posting a
    genuine HID event.
    """

    def tripwire(name):
        def _boom(*args, **kwargs):
            raise AssertionError(f"unit test reached the real OS layer via {name}()")

        return _boom

    for name in (
        "_run",
        "osascript",
        "_pbpaste",
        "_pbcopy",
        "real_click",
        "real_key",
        "is_running",
        "dismiss_dialogs",
    ):
        monkeypatch.setattr(app, name, tripwire(name))
    # subprocess.run is the floor underneath all of the above: _pbcopy calls it
    # directly, so leaving it live would let a bug spawn a real `pbcopy`.
    monkeypatch.setattr(subprocess, "run", tripwire("subprocess.run"))
    monkeypatch.setitem(sys.modules, "Quartz", QuartzTripwire())
    # Unit tests never wait on the real clock; the pasteboard poll would otherwise
    # add a second per test for no information.
    monkeypatch.setattr(app.time, "sleep", lambda *_: None)


# --- fake window server -----------------------------------------------------


def cg_record(title: str, *, wid: int, width=1291, height=949, x=221.0, y=33.0, owner="Tableau"):
    """One CGWindowListCopyWindowInfo record, in the shape CoreGraphics returns."""
    return {
        "kCGWindowNumber": wid,
        "kCGWindowOwnerName": owner,
        "kCGWindowName": title,
        "kCGWindowBounds": {"X": x, "Y": y, "Width": width, "Height": height},
    }


def husk_record(title: str, *, wid: int):
    """A destroyed document the window server has not reaped: 218x161 at (-234, 367)."""
    return cg_record(title, wid=wid, width=218, height=161, x=-234.0, y=367.0)


def dock_tile_record(title: str, *, wid: int):
    """A MINIMIZED document. It keeps a Dock tile, and the tile is on-screen."""
    return cg_record(title, wid=wid, width=140, height=161, x=16.0, y=332.0)


class FakeQuartz:
    """Minimal stand-in for the Quartz module, faithful to the two list options.

    The real constants matter: ``kCGWindowListOptionAll`` is 0 and
    ``kCGWindowListOptionOnScreenOnly`` is 1, so the option word has to be read
    bitwise. The all-windows list is a SUPERSET — it returns the husks *plus*
    everything on screen — which is why :func:`list_windows` has to de-duplicate.
    """

    kCGWindowListOptionAll = 0
    kCGWindowListOptionOnScreenOnly = 1
    kCGWindowListExcludeDesktopElements = 16
    kCGNullWindowID = 0

    def __init__(self, on_screen, husks=()):
        self.on_screen = list(on_screen)
        self.husks = list(husks)
        self.options_queried: list[int] = []

    # Named exactly as the CoreGraphics function it stands in for.
    def CGWindowListCopyWindowInfo(self, option, relative_to):
        self.options_queried.append(option)
        if option & self.kCGWindowListOptionOnScreenOnly:
            return list(self.on_screen)
        return list(self.on_screen) + list(self.husks)


@pytest.fixture
def window_server(monkeypatch):
    """Install a fake window server and report Tableau as running."""

    def install(on_screen, husks=()):
        fake = FakeQuartz(on_screen, husks)
        monkeypatch.setitem(sys.modules, "Quartz", fake)
        monkeypatch.setattr(app, "is_running", lambda: True)
        return fake

    return install


def win_row(title: str, *, wid: int, width=1291, height=949, on_screen=True):
    """A row as :func:`list_windows` returns it, for tests that fake it directly."""
    return {
        "id": wid,
        "title": title,
        "width": width,
        "height": height,
        "area": width * height,
        "on_screen": on_screen,
        "is_stale": not on_screen,
    }


LIVE_TITLE = "Tableau Public - Probe_Alpha"


# --- fix 1: liveness, not the all-windows list ------------------------------


def test_list_windows_excludes_husks_of_closed_documents(window_server):
    """A husk is a DESTROYED window, and reporting it as open is the bug.

    Every workbook Tableau has ever opened leaves one behind; the old
    implementation queried kCGWindowListOptionAll only, so one real document
    looked like three open workbooks.
    """
    window_server(
        [cg_record(LIVE_TITLE, wid=1)],
        husks=[
            husk_record("Tableau Public - Probe", wid=2),
            husk_record("Tableau Public - Old", wid=3),
        ],
    )
    assert [w["title"] for w in app.list_windows()] == [LIVE_TITLE]
    assert app.window_names() == [LIVE_TITLE]


def test_minimized_documents_are_still_reported_open(window_server):
    """The on-screen list is enough: a minimized document keeps a Dock tile."""
    window_server([dock_tile_record("Tableau Public - Probe", wid=7)])
    assert app.window_names() == ["Tableau Public - Probe"]
    assert app.list_windows()[0]["is_stale"] is False


def test_husks_remain_available_for_diagnostics(window_server):
    """Husk information is downgraded, not deleted: it answers "already closed?"."""
    window_server(
        [cg_record(LIVE_TITLE, wid=1)],
        husks=[husk_record("Tableau Public - Probe", wid=2)],
    )
    rows = app.list_windows(include_stale=True)
    assert [(w["title"], w["is_stale"]) for w in rows] == [
        (LIVE_TITLE, False),
        ("Tableau Public - Probe", True),
    ]
    assert app.stale_window_names() == ["Tableau Public - Probe"]


def test_all_windows_list_is_deduplicated_against_the_onscreen_one(window_server):
    """The all-windows list repeats every live window; it must not be double-counted."""
    fake = window_server([cg_record(LIVE_TITLE, wid=1)], husks=[husk_record("x", wid=2)])
    rows = app.list_windows(include_stale=True)
    assert [w["id"] for w in rows] == [1, 2]
    # Both lists really were consulted (on-screen first).
    assert fake.options_queried == [
        FakeQuartz.kCGWindowListOptionOnScreenOnly | FakeQuartz.kCGWindowListExcludeDesktopElements,
        FakeQuartz.kCGWindowListOptionAll | FakeQuartz.kCGWindowListExcludeDesktopElements,
    ]


def test_windows_of_other_apps_are_ignored(window_server):
    window_server([cg_record("Some Browser Window", wid=9, owner="Safari")])
    assert app.list_windows() == []


def test_list_windows_is_empty_when_tableau_is_not_running(monkeypatch):
    monkeypatch.setattr(app, "is_running", lambda: False)
    # The Quartz tripwire is still armed: a not-running check must short-circuit
    # before the window server is queried at all.
    assert app.list_windows() == []


def test_status_does_not_report_closed_workbooks_as_open(window_server, monkeypatch):
    """`get_tableau_public_app_status` is the tool that surfaced this to the user."""
    window_server(
        [cg_record(LIVE_TITLE, wid=1)],
        husks=[husk_record("Tableau Public - Probe", wid=2)],
    )
    monkeypatch.setattr(app, "find_app", lambda: "/Applications/Tableau Public.app")
    monkeypatch.setattr(app, "app_version", lambda p: "2026.2.0")
    monkeypatch.setattr(app, "app_bundle_id", lambda p: app.BUNDLE_ID)
    monkeypatch.setattr(app, "check_accessibility", lambda: True)

    payload = app.status().to_dict()
    assert payload["windows"] == [LIVE_TITLE]
    assert payload["stale_windows"] == ["Tableau Public - Probe"]
    assert any("already CLOSED" in n for n in payload["notes"])


def test_status_has_no_husk_note_when_there_are_none(window_server, monkeypatch):
    window_server([cg_record(LIVE_TITLE, wid=1)])
    monkeypatch.setattr(app, "find_app", lambda: "/Applications/Tableau Public.app")
    monkeypatch.setattr(app, "app_version", lambda p: "2026.2.0")
    monkeypatch.setattr(app, "app_bundle_id", lambda p: app.BUNDLE_ID)
    monkeypatch.setattr(app, "check_accessibility", lambda: True)
    status = app.status()
    assert status.stale_windows == []
    assert status.notes == []


# --- fix 2: exact stem match, never substring -------------------------------


def test_find_window_refuses_a_substring_match(monkeypatch):
    """The concrete failure: Probe.twbx fails to load, Probe_Alpha is open.

    A substring match returned Probe_Alpha's window, so the caller reported
    ``opened=True`` and screenshotted the wrong workbook as proof.
    """
    monkeypatch.setattr(app, "list_windows", lambda **kw: [win_row(LIVE_TITLE, wid=1)])
    assert app.find_window("Probe") is None


def test_find_window_matches_the_exact_stem(monkeypatch):
    monkeypatch.setattr(
        app,
        "list_windows",
        lambda **kw: [win_row(LIVE_TITLE, wid=1), win_row("Tableau Public - Probe", wid=2)],
    )
    hit = app.find_window("Probe")
    assert hit is not None
    assert hit["title"] == "Tableau Public - Probe"
    assert hit["id"] == 2


def test_find_window_normalises_underscores_and_case(monkeypatch):
    """`normalise_stem` is the one canonical comparison used across the codebase."""
    monkeypatch.setattr(app, "list_windows", lambda **kw: [win_row(LIVE_TITLE, wid=1)])
    assert app.find_window("probe alpha")["id"] == 1
    assert app.find_window("Probe_Alpha.twbx")["id"] == 1
    assert app.find_window(LIVE_TITLE)["id"] == 1


def test_find_window_ignores_the_longer_sibling_workbook(monkeypatch):
    """`Full_Feature_Check` must not resolve to `Full_Feature_Check_v2`."""
    monkeypatch.setattr(
        app,
        "list_windows",
        lambda **kw: [win_row("Tableau Public - Full_Feature_Check_v2", wid=5)],
    )
    assert app.find_window("Full_Feature_Check") is None


def test_find_window_never_returns_a_husk(window_server):
    """min_area=0 isolates liveness: a closed workbook must not look open."""
    window_server([], husks=[husk_record("Tableau Public - Probe", wid=2)])
    assert app.find_window("Probe", min_area=0) is None


def test_find_window_still_filters_transient_progress_dialogs(monkeypatch):
    """The min_area guard is retained, not weakened."""
    monkeypatch.setattr(
        app,
        "list_windows",
        lambda **kw: [win_row("Tableau Public - Probe", wid=3, width=530, height=151)],
    )
    assert app.find_window("Probe") is None
    assert app.find_window("Probe", min_area=0)["id"] == 3


def test_find_window_rejects_an_empty_name(monkeypatch):
    monkeypatch.setattr(app, "list_windows", lambda **kw: [win_row(LIVE_TITLE, wid=1)])
    assert app.find_window("   ") is None


def test_open_workbook_reports_the_error_instead_of_a_sibling_window(tmp_path, monkeypatch):
    """End to end: the false green validation this fix exists to prevent.

    Probe.twbx fails to load while Probe_Alpha is open. The old substring match
    made open_workbook return opened=True with Probe_Alpha's window id, and the
    screenshot "proving" Probe.twbx rendered was a picture of Probe_Alpha.
    """
    workbook = tmp_path / "Probe.twbx"
    workbook.write_bytes(b"PK\x03\x04")
    monkeypatch.setattr(app, "find_app", lambda: "/Applications/Tableau Public.app")
    monkeypatch.setattr(
        app, "_run", lambda args, **kw: subprocess.CompletedProcess(args, 0, "", "")
    )
    monkeypatch.setattr(app, "list_windows", lambda **kw: [win_row(LIVE_TITLE, wid=1)])
    monkeypatch.setattr(app, "read_error_dialog", lambda **kw: "Unable to complete action")
    dismissed: list[int] = []
    monkeypatch.setattr(app, "dismiss_dialogs", lambda: dismissed.append(1))

    result = app.open_workbook(workbook, timeout=5.0, poll=0.0)
    assert result["opened"] is False
    assert result["window"] is None
    assert result["error"] == "Unable to complete action"
    assert dismissed == [1]


def test_open_workbook_finds_its_own_window(tmp_path, monkeypatch):
    workbook = tmp_path / "Probe.twbx"
    workbook.write_bytes(b"PK\x03\x04")
    monkeypatch.setattr(app, "find_app", lambda: "/Applications/Tableau Public.app")
    monkeypatch.setattr(
        app, "_run", lambda args, **kw: subprocess.CompletedProcess(args, 0, "", "")
    )
    monkeypatch.setattr(
        app,
        "list_windows",
        lambda **kw: [win_row(LIVE_TITLE, wid=1), win_row("Tableau Public - Probe", wid=2)],
    )
    result = app.open_workbook(workbook, timeout=5.0, poll=0.0)
    assert result["opened"] is True
    assert result["window"] == "Tableau Public - Probe"
    assert result["window_id"] == 2


# --- fix 3: the error dialog's text must come from Tableau ------------------


class FakeDesktopScripts:
    """Fakes ``osascript`` and the pasteboard for :func:`read_error_dialog`.

    ``clipboard`` is what pbpaste returns. ``copies_on_click`` is what Tableau
    writes to the pasteboard when the 'Copy Error Message' click actually works;
    ``None`` models the documented Qt no-op — the click is accepted and nothing
    happens.
    """

    def __init__(self, *, dialog_present=True, clipboard="", copies_on_click=None, ax_text=""):
        self.dialog_present = dialog_present
        self.clipboard = clipboard
        self.copies_on_click = copies_on_click
        self.ax_text = ax_text
        self.scripts: list[str] = []
        self.restored: list[str] = []
        self.dismissed = 0

    def osascript(self, script, **kwargs):
        self.scripts.append(script)
        if "static texts" in script:
            return self.ax_text
        # The detect-and-click script.
        if self.dialog_present and self.copies_on_click is not None:
            self.clipboard = self.copies_on_click
        return "true" if self.dialog_present else "false"

    def pbpaste(self):
        return self.clipboard

    def pbcopy(self, text):
        self.restored.append(text)
        self.clipboard = text

    def dismiss(self):
        self.dismissed += 1

    def install(self, monkeypatch):
        monkeypatch.setattr(app, "is_running", lambda: True)
        monkeypatch.setattr(app, "osascript", self.osascript)
        monkeypatch.setattr(app, "_pbpaste", self.pbpaste)
        monkeypatch.setattr(app, "_pbcopy", self.pbcopy)
        monkeypatch.setattr(app, "dismiss_dialogs", self.dismiss)
        return self


def test_no_dialog_returns_none(monkeypatch):
    fake = FakeDesktopScripts(dialog_present=False, clipboard="user's notes").install(monkeypatch)
    assert app.read_error_dialog() is None
    assert fake.dismissed == 0
    assert fake.clipboard == "user's notes"


def test_unchanged_clipboard_is_never_reported_as_a_tableau_error(monkeypatch):
    """The click no-ops on Qt; the user's clipboard is not evidence of anything.

    Returning it aborted publishes that had already succeeded, and leaked whatever
    the user last copied into an MCP tool response.
    """
    secret = "sk-live-not-a-tableau-error"
    fake = FakeDesktopScripts(clipboard=secret, copies_on_click=None).install(monkeypatch)
    text = app.read_error_dialog()
    assert secret not in text
    assert text == app.DIALOG_TEXT_UNREADABLE
    # Nothing was clobbered, so nothing was restored.
    assert fake.restored == []
    assert fake.clipboard == secret


def test_copied_text_is_returned_and_the_clipboard_is_restored(monkeypatch):
    fake = FakeDesktopScripts(
        clipboard="the user's shopping list",
        copies_on_click="Unable to complete action\nThe data source is missing.",
    ).install(monkeypatch)
    text = app.read_error_dialog()
    assert text == "Unable to complete action\nThe data source is missing."
    assert fake.restored == ["the user's shopping list"]
    assert fake.clipboard == "the user's shopping list"
    assert fake.dismissed == 1


def test_empty_clipboard_falls_back_to_the_dialog_text_instead_of_none(monkeypatch):
    """Escape has already been pressed, so None would destroy the only evidence."""
    fake = FakeDesktopScripts(
        clipboard="",
        copies_on_click=None,
        ax_text="Unable to complete action\nThe file is not a valid workbook.",
    ).install(monkeypatch)
    text = app.read_error_dialog(dismiss=True)
    assert text == "Unable to complete action\nThe file is not a valid workbook."
    assert fake.dismissed == 1
    assert any("static texts" in s for s in fake.scripts)


def test_whitespace_only_copy_is_not_treated_as_a_message(monkeypatch):
    FakeDesktopScripts(clipboard="", copies_on_click="   \n ", ax_text="").install(monkeypatch)
    assert app.read_error_dialog() == app.DIALOG_TEXT_UNREADABLE


def test_a_confirmed_dialog_never_returns_none(monkeypatch):
    """Nothing readable anywhere: still an error, never silence."""
    FakeDesktopScripts(clipboard="", copies_on_click=None, ax_text="").install(monkeypatch)
    assert app.read_error_dialog() is not None


def test_non_text_clipboard_is_not_overwritten_with_an_empty_string(monkeypatch):
    """pbpaste returns '' for an image; writing that back would recover nothing."""
    fake = FakeDesktopScripts(clipboard="", copies_on_click="Tableau error text").install(
        monkeypatch
    )
    assert app.read_error_dialog() == "Tableau error text"
    assert fake.restored == []


def test_dialog_text_is_deduplicated_and_empty_means_none(monkeypatch):
    monkeypatch.setattr(app, "osascript", lambda s, **kw: "Error\nError\n\n  Details  ")
    assert app._dialog_text() == "Error\nDetails"
    monkeypatch.setattr(app, "osascript", lambda s, **kw: "\n  \n")
    assert app._dialog_text() is None


def test_dialog_text_survives_an_osascript_failure(monkeypatch):
    def boom(script, **kwargs):
        raise app.DesktopError("System Events got an error")

    monkeypatch.setattr(app, "osascript", boom)
    assert app._dialog_text() is None


def test_read_error_dialog_is_silent_when_tableau_is_not_running(monkeypatch):
    monkeypatch.setattr(app, "is_running", lambda: False)
    # The osascript and pasteboard tripwires stay armed.
    assert app.read_error_dialog() is None


def test_pasteboard_helpers_shell_out_correctly(monkeypatch):
    """The one place the pasteboard wrapper's argv is checked, still without pbpaste."""
    calls: list[tuple] = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs.get("input")))
        return subprocess.CompletedProcess(args, 0, "clip contents", "")

    monkeypatch.setattr(app, "_run", fake_run)
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert REAL_PBPASTE() == "clip contents"
    REAL_PBCOPY("restore me")
    assert calls == [(["pbpaste"], None), (["pbcopy"], "restore me")]


def test_pbcopy_never_raises(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("pbcopy is missing")

    monkeypatch.setattr(subprocess, "run", boom)
    REAL_PBCOPY("anything")  # must not propagate: restoring is best effort


# --- fix 4: the unverifiable close path is gone -----------------------------


def test_close_window_no_longer_exists():
    """It returned True whenever an AXCloseButton click did not throw.

    Qt ignores System Events clicks, so True meant nothing, and it selected its
    target by substring — `close_window("Probe")` could close Probe_Alpha and
    destroy unsaved work. It had no callers, and window_control.close_document
    already does the job with verification, so it was deleted rather than
    duplicated.
    """
    assert not hasattr(app, "close_window")

    from tableau_public_authoring.desktop import window_control

    assert callable(window_control.close_document)
