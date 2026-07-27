"""Window-management tests — every OS interaction is faked.

No test here touches Quartz, osascript, `open` or the Tableau GUI: the enumerator,
clicker, key sender, activator and opener are all injected. The window geometry in
the fixtures is not invented — it was captured read-only from a live Tableau
Public 2026.2.0 session with several test workbooks open and minimized.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tableau_public_authoring.desktop import window_control as wc


@pytest.fixture(autouse=True)
def no_real_os_calls(monkeypatch):
    """Hard guarantee that no test in this file can touch the GUI.

    Every real entry point is replaced with a tripwire. If a code path ever falls
    back to a default instead of the injected fake, the test fails loudly here
    rather than posting a genuine HID event at whatever Tableau window happens to
    be frontmost.
    """

    def tripwire(name):
        def _boom(*args, **kwargs):
            raise AssertionError(f"unit test reached the real OS layer via {name}()")

        return _boom

    for name in (
        "quartz_windows",
        "real_click",
        "post_command_key",
        "activate_app",
        "open_with_tableau",
        "osascript",
        "find_app",
    ):
        monkeypatch.setattr(wc, name, tripwire(name))


# --- fixtures captured from a live session ---------------------------------

# A restored document window.
RESTORED = {
    "id": 271933,
    "title": "Tableau Public - MCP_Authoring_Validation_-_20260727-0050",
    "x": 221.0,
    "y": 33.0,
    "width": 1291.0,
    "height": 949.0,
    "on_screen": True,
}
# Minimized into the Dock: still on-screen, shrunk to a tile at the Dock's x.
DOCK_TILE_EV = {
    "id": 271404,
    "title": "Tableau Public - Quarterly_Sales_Review",
    "x": 16.0,
    "y": 332.0,
    "width": 140.0,
    "height": 161.0,
    "on_screen": True,
}
DOCK_TILE_FFC = {
    "id": 271872,
    "title": "Tableau Public - Full_Feature_Check",
    "x": 16.0,
    "y": 142.0,
    "width": 140.0,
    "height": 184.0,
    "on_screen": True,
}
DOCK_TILE_FFC_V2 = {
    "id": 271888,
    "title": "Tableau Public - Full_Feature_Check_v2",
    "x": 16.0,
    "y": 685.0,
    "width": 140.0,
    "height": 188.0,
    "on_screen": True,
}
# Minimized while hidden: parked off-screen at a negative x, absent on-screen.
OFFSCREEN_PROBE_A = {
    "id": 271811,
    "title": "Tableau Public - ProbeA_FilterOnly",
    "x": -234.0,
    "y": 367.0,
    "width": 218.0,
    "height": 161.0,
    "on_screen": False,
}
OFFSCREEN_NOFILTER = {
    "id": 271750,
    "title": "Tableau Public - NoFilter_Probe",
    "x": -234.0,
    "y": 367.0,
    "width": 218.0,
    "height": 161.0,
    "on_screen": False,
}
# Not documents.
PROGRESS_DIALOG = {
    "id": 271771,
    "title": "Opening workbook 'NoFilter_Probe.twbx'...",
    "x": 591.0,
    "y": 400.0,
    "width": 530.0,
    "height": 151.0,
    "on_screen": False,
}
ERROR_DIALOG = {
    "id": 271563,
    "title": "Unable to complete action",
    "x": 616.0,
    "y": 421.0,
    "width": 502.0,
    "height": 201.0,
    "on_screen": True,
}
SAVE_PROMPT = {
    "id": 999001,
    "title": "Do you want to save the changes made to Probe_Alpha?",
    "x": 600.0,
    "y": 400.0,
    "width": 520.0,
    "height": 180.0,
    "on_screen": True,
}


def doc(stem: str, *, wid: int, minimized: bool = False, offscreen: bool = False) -> dict:
    """A synthetic document window with realistic bounds."""
    if offscreen:
        return {
            "id": wid,
            "title": f"{wc.DOC_TITLE_PREFIX}{stem}",
            "x": -234.0,
            "y": 367.0,
            "width": 218.0,
            "height": 161.0,
            "on_screen": False,
        }
    if minimized:
        return {
            "id": wid,
            "title": f"{wc.DOC_TITLE_PREFIX}{stem}",
            "x": 16.0,
            "y": 142.0,
            "width": 140.0,
            "height": 161.0,
            "on_screen": True,
        }
    return {
        "id": wid,
        "title": f"{wc.DOC_TITLE_PREFIX}{stem}",
        "x": 221.0,
        "y": 33.0,
        "width": 1291.0,
        "height": 949.0,
        "on_screen": True,
    }


class FakeDesktop:
    """A mutable stand-in for the window server plus the HID event layer.

    Records every event it is asked to send, so tests can assert that a code path
    sent *nothing* — which is the whole point of dry-run mode.
    """

    def __init__(self, windows, *, on_key=None, on_click=None, on_open=None):
        self.windows = [dict(w) for w in windows]
        self.clicks: list[tuple[int, int]] = []
        self.keys: list[str] = []
        self.opened: list[Path] = []
        self.activations = 0
        self.sleeps: list[float] = []
        self._on_key = on_key
        self._on_click = on_click
        self._on_open = on_open

    # -- injected callables -------------------------------------------------
    def enumerate(self) -> list[dict]:
        return [dict(w) for w in self.windows]

    def click(self, x, y) -> None:
        self.clicks.append((int(x), int(y)))
        if self._on_click:
            self._on_click(self)

    def send_key(self, key: str) -> None:
        self.keys.append(key)
        if self._on_key:
            self._on_key(self)

    def activate(self) -> None:
        self.activations += 1

    def open_file(self, path: Path) -> None:
        self.opened.append(Path(path))
        if self._on_open:
            self._on_open(self)

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    # -- state helpers ------------------------------------------------------
    def _index(self, stem: str) -> int | None:
        needle = wc.normalise_stem(stem)
        for i, w in enumerate(self.windows):
            title = w["title"]
            if title.startswith(wc.DOC_TITLE_PREFIX) and wc.normalise_stem(title) == needle:
                return i
        return None

    def restore_and_front(self, stem: str) -> bool:
        i = self._index(stem)
        if i is None:
            return False
        w = self.windows.pop(i)
        w.update({"x": 221.0, "y": 33.0, "width": 1291.0, "height": 949.0, "on_screen": True})
        self.windows.insert(0, w)
        return True

    def raiser(self, stem: str) -> tuple[bool, str]:
        if self.restore_and_front(stem):
            return True, f"fake-raised {stem}"
        return False, f"fake could not raise {stem}"

    def remove_stem(self, stem: str) -> None:
        i = self._index(stem)
        if i is not None:
            self.windows.pop(i)

    def remove_frontmost_document(self) -> None:
        for i, w in enumerate(self.windows):
            if w["title"].startswith(wc.DOC_TITLE_PREFIX) and w["on_screen"]:
                self.windows.pop(i)
                return

    def add(self, window: dict) -> None:
        self.windows.insert(0, dict(window))

    def titles(self) -> list[str]:
        return [w["title"] for w in self.windows]


def classify(fake: FakeDesktop):
    return wc.classify_windows(enumerator=fake.enumerate)


def by_id(windows, wid: int):
    return next(w for w in windows if w.id == wid)


# --- classification ---------------------------------------------------------


def test_restored_document_is_not_minimized():
    fake = FakeDesktop([RESTORED])
    w = classify(fake)[0]
    assert w.is_document
    assert w.workbook_stem == "MCP_Authoring_Validation_-_20260727-0050"
    assert not w.is_minimized


def test_dock_tile_is_classified_minimized():
    """140x161 on-screen at the Dock edge is a minimized window's Dock tile."""
    w = classify(FakeDesktop([DOCK_TILE_EV]))[0]
    assert w.is_document
    assert w.is_minimized
    assert w.on_screen


def test_offscreen_window_is_classified_minimized():
    """Absent from the on-screen list and parked at a negative x."""
    w = classify(FakeDesktop([OFFSCREEN_PROBE_A]))[0]
    assert w.is_minimized
    assert not w.on_screen


def test_absence_from_onscreen_list_alone_marks_minimized():
    """Full-size bounds but missing on-screen: still reported minimized."""
    hidden = dict(RESTORED, on_screen=False, id=424242)
    assert classify(FakeDesktop([hidden]))[0].is_minimized


def test_dialogs_are_not_documents():
    windows = classify(FakeDesktop([PROGRESS_DIALOG, ERROR_DIALOG, RESTORED]))
    assert [w.is_document for w in windows] == [False, False, True]
    assert by_id(windows, PROGRESS_DIALOG["id"]).workbook_stem is None


def test_bare_app_window_is_not_a_document():
    bare = {
        "id": 271648,
        "title": "Tableau Public",
        "x": -234.0,
        "y": 367.0,
        "width": 218.0,
        "height": 161.0,
        "on_screen": False,
    }
    assert not classify(FakeDesktop([bare]))[0].is_document


def test_frontmost_document_skips_minimized_windows():
    fake = FakeDesktop([DOCK_TILE_FFC, OFFSCREEN_PROBE_A, RESTORED])
    front = wc.frontmost_document(enumerator=fake.enumerate)
    assert front is not None
    assert front.id == RESTORED["id"]


# --- name normalisation and matching ---------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Full_Feature_Check", "full feature check"),
        ("Full Feature Check", "full feature check"),
        ("full_feature_check.twbx", "full feature check"),
        ("Full_Feature_Check.twb", "full feature check"),
        ("Tableau Public - Full_Feature_Check", "full feature check"),
        ("  Full   Feature_Check  ", "full feature check"),
    ],
)
def test_normalise_stem(raw, expected):
    assert wc.normalise_stem(raw) == expected


def test_find_document_tolerates_underscore_versus_space():
    fake = FakeDesktop([DOCK_TILE_FFC])
    assert wc.find_document("Full Feature Check", enumerator=fake.enumerate) is not None
    assert wc.find_document("full_feature_check", enumerator=fake.enumerate) is not None
    assert wc.find_document("FULL FEATURE CHECK", enumerator=fake.enumerate) is not None


def test_find_document_accepts_a_filename_or_a_full_title():
    fake = FakeDesktop([DOCK_TILE_FFC])
    assert wc.find_document("Full_Feature_Check.twbx", enumerator=fake.enumerate) is not None
    assert (
        wc.find_document("Tableau Public - Full_Feature_Check", enumerator=fake.enumerate)
        is not None
    )


def test_find_document_prefers_exact_match_over_substring():
    """Full_Feature_Check must not resolve to Full_Feature_Check_v2."""
    fake = FakeDesktop([DOCK_TILE_FFC_V2, DOCK_TILE_FFC])
    hit = wc.find_document("Full_Feature_Check", enumerator=fake.enumerate)
    assert hit is not None
    assert hit.workbook_stem == "Full_Feature_Check"


def test_find_document_returns_largest_match_when_duplicates_exist():
    """One workbook, two windows (Dock tile + restored): pick the restored one."""
    tile = doc("Probe_Alpha", wid=1, minimized=True)
    restored = doc("Probe_Alpha", wid=2)
    fake = FakeDesktop([tile, restored])
    hit = wc.find_document("Probe_Alpha", enumerator=fake.enumerate)
    assert hit is not None
    assert hit.id == 2
    assert hit.area > tile["width"] * tile["height"]


def test_find_document_returns_none_when_absent():
    fake = FakeDesktop([DOCK_TILE_EV, PROGRESS_DIALOG])
    assert wc.find_document("Nope_Not_Here", enumerator=fake.enumerate) is None
    assert wc.find_document("", enumerator=fake.enumerate) is None


def test_find_document_ignores_the_progress_dialog_for_the_same_workbook():
    fake = FakeDesktop([PROGRESS_DIALOG, OFFSCREEN_NOFILTER])
    hit = wc.find_document("NoFilter_Probe", enumerator=fake.enumerate)
    assert hit is not None
    assert hit.id == OFFSCREEN_NOFILTER["id"]


# --- click geometry ---------------------------------------------------------


def test_click_point_uses_live_bounds_not_constants():
    tile = classify(FakeDesktop([DOCK_TILE_EV]))[0]
    assert wc.click_point(tile) == (86, 412)  # centre of the live Dock tile
    restored = classify(FakeDesktop([RESTORED]))[0]
    assert wc.click_point(restored) == (866, 45)  # title bar of the live window


def test_click_point_refuses_offscreen_windows():
    offscreen = classify(FakeDesktop([OFFSCREEN_PROBE_A]))[0]
    assert wc.click_point(offscreen) is None


# --- raising ----------------------------------------------------------------


def test_unminimize_and_raise_reports_missing_window_without_acting():
    fake = FakeDesktop([DOCK_TILE_EV])
    ok, message = wc.unminimize_and_raise(
        "Ghost_Workbook",
        enumerator=fake.enumerate,
        clicker=fake.click,
        activator=fake.activate,
        opener=fake.open_file,
        sleeper=fake.sleep,
    )
    assert ok is False
    assert "Ghost_Workbook" in message
    assert "Quarterly_Sales_Review" in message  # actionable: lists what IS open
    assert fake.clicks == []
    assert fake.activations == 0


def test_unminimize_and_raise_prefers_the_open_path_when_a_file_is_known(tmp_path):
    path = tmp_path / "Probe_Alpha.twbx"
    path.write_bytes(b"not really a workbook")
    fake = FakeDesktop(
        [doc("Probe_Alpha", wid=7, offscreen=True)],
        on_open=lambda f: f.restore_and_front("Probe_Alpha"),
    )
    ok, message = wc.unminimize_and_raise(
        "Probe_Alpha",
        file_path=path,
        enumerator=fake.enumerate,
        clicker=fake.click,
        activator=fake.activate,
        opener=fake.open_file,
        sleeper=fake.sleep,
    )
    assert ok is True
    assert fake.opened == [path]
    assert fake.activations == 1  # activate must precede open -a
    assert fake.clicks == []  # no blind clicking when the file path is known
    assert "open -a" in message


def test_unminimize_and_raise_clicks_the_live_dock_tile_as_a_fallback():
    fake = FakeDesktop(
        [doc("Probe_Alpha", wid=7, minimized=True)],
        on_click=lambda f: f.restore_and_front("Probe_Alpha"),
    )
    ok, _ = wc.unminimize_and_raise(
        "Probe_Alpha",
        enumerator=fake.enumerate,
        clicker=fake.click,
        activator=fake.activate,
        opener=fake.open_file,
        sleeper=fake.sleep,
    )
    assert ok is True
    assert fake.clicks == [(86, 222)]  # centre of the tile's live bounds
    assert fake.opened == []


def test_unminimize_and_raise_refuses_offscreen_window_without_a_file_path():
    fake = FakeDesktop([OFFSCREEN_PROBE_A])
    ok, message = wc.unminimize_and_raise(
        "ProbeA_FilterOnly",
        enumerator=fake.enumerate,
        clicker=fake.click,
        activator=fake.activate,
        opener=fake.open_file,
        sleeper=fake.sleep,
    )
    assert ok is False
    assert "file_path" in message
    assert fake.clicks == []  # never click at a guessed coordinate


def test_unminimize_and_raise_is_a_no_op_when_already_frontmost():
    fake = FakeDesktop([RESTORED])
    ok, message = wc.unminimize_and_raise(
        "MCP_Authoring_Validation_-_20260727-0050",
        enumerator=fake.enumerate,
        clicker=fake.click,
        activator=fake.activate,
        opener=fake.open_file,
        sleeper=fake.sleep,
    )
    assert ok is True
    assert "already the frontmost" in message
    assert fake.clicks == []
    assert fake.activations == 0


def test_unminimize_and_raise_reports_failure_when_nothing_moves():
    fake = FakeDesktop([doc("Probe_Alpha", wid=7, minimized=True), RESTORED])
    ok, message = wc.unminimize_and_raise(
        "Probe_Alpha",
        enumerator=fake.enumerate,
        clicker=fake.click,
        activator=fake.activate,
        opener=fake.open_file,
        sleeper=fake.sleep,
        timeout=2.0,
    )
    assert ok is False
    assert "frontmost document is still" in message


# --- close_document ---------------------------------------------------------


def test_close_document_refuses_an_unknown_workbook():
    fake = FakeDesktop([DOCK_TILE_EV])
    ok, message = wc.close_document(
        "Ghost_Workbook",
        enumerator=fake.enumerate,
        key_sender=fake.send_key,
        raiser=fake.raiser,
        sleeper=fake.sleep,
    )
    assert ok is False
    assert fake.keys == []
    assert "no Tableau document window" in message


def test_close_document_refuses_a_substring_only_match():
    """Asking for Full_Feature_Check must never close Full_Feature_Check_v2."""
    fake = FakeDesktop([DOCK_TILE_FFC_V2])
    ok, message = wc.close_document(
        "Full_Feature_Check",
        enumerator=fake.enumerate,
        key_sender=fake.send_key,
        raiser=fake.raiser,
        sleeper=fake.sleep,
    )
    assert ok is False
    assert fake.keys == []
    assert "Full_Feature_Check_v2" in message
    assert "exact" in message


def test_close_document_rejects_save_true_instead_of_silently_ignoring_it():
    fake = FakeDesktop([doc("Probe_Alpha", wid=7)])
    ok, message = wc.close_document(
        "Probe_Alpha",
        save=True,
        enumerator=fake.enumerate,
        key_sender=fake.send_key,
        raiser=fake.raiser,
        sleeper=fake.sleep,
    )
    assert ok is False
    assert "not supported" in message
    assert fake.keys == []


def test_close_document_refuses_when_a_save_prompt_is_already_showing():
    fake = FakeDesktop([SAVE_PROMPT, doc("Probe_Alpha", wid=7)])
    ok, message = wc.close_document(
        "Probe_Alpha",
        enumerator=fake.enumerate,
        key_sender=fake.send_key,
        raiser=fake.raiser,
        sleeper=fake.sleep,
    )
    assert ok is False
    assert fake.keys == []
    assert "Answer it in Tableau" in message


def test_close_document_bails_out_when_a_save_prompt_appears():
    """The safety-critical path: never answer a 'save changes?' question."""

    def on_key(f: FakeDesktop) -> None:
        f.add(SAVE_PROMPT)  # workbook stays open, Tableau asks about unsaved work

    fake = FakeDesktop([doc("Probe_Alpha", wid=7)], on_key=on_key)
    ok, message = wc.close_document(
        "Probe_Alpha",
        enumerator=fake.enumerate,
        key_sender=fake.send_key,
        raiser=fake.raiser,
        sleeper=fake.sleep,
    )
    assert ok is False
    assert "BAILED OUT" in message
    assert "will not answer a save prompt" in message
    # One Command-W and nothing else: the prompt itself was never answered.
    assert fake.keys == ["w"]
    assert fake.clicks == []
    assert SAVE_PROMPT["title"] in fake.titles()  # left on screen for the human


def test_close_document_bails_out_on_an_unrecognised_new_dialog():
    """An unnamed dialog is treated as dangerous, not as success."""

    def on_key(f: FakeDesktop) -> None:
        f.add(ERROR_DIALOG)

    fake = FakeDesktop([doc("Probe_Alpha", wid=7)], on_key=on_key)
    ok, message = wc.close_document(
        "Probe_Alpha",
        enumerator=fake.enumerate,
        key_sender=fake.send_key,
        raiser=fake.raiser,
        sleeper=fake.sleep,
    )
    assert ok is False
    assert "BAILED OUT" in message
    assert ERROR_DIALOG["title"] in message


def test_close_document_reports_failure_when_the_window_survives():
    fake = FakeDesktop([doc("Probe_Alpha", wid=7)], on_key=lambda f: None)
    ok, message = wc.close_document(
        "Probe_Alpha",
        enumerator=fake.enumerate,
        key_sender=fake.send_key,
        raiser=fake.raiser,
        sleeper=fake.sleep,
    )
    assert ok is False
    assert "still open" in message
    assert "Nothing was forced" in message


def test_close_document_succeeds_only_when_the_window_is_gone():
    fake = FakeDesktop(
        [doc("Probe_Alpha", wid=7), DOCK_TILE_EV],
        on_key=lambda f: f.remove_stem("Probe_Alpha"),
    )
    ok, message = wc.close_document(
        "Probe_Alpha",
        enumerator=fake.enumerate,
        key_sender=fake.send_key,
        raiser=fake.raiser,
        sleeper=fake.sleep,
    )
    assert ok is True
    assert "closed" in message
    assert fake.keys == ["w"]
    # The user's workbook is untouched.
    assert DOCK_TILE_EV["title"] in fake.titles()


def test_close_document_refuses_when_the_target_cannot_be_raised():
    fake = FakeDesktop([doc("Probe_Alpha", wid=7, offscreen=True), RESTORED])
    ok, message = wc.close_document(
        "Probe_Alpha",
        enumerator=fake.enumerate,
        key_sender=fake.send_key,
        raiser=lambda stem: (False, "stub refuses to raise"),
        sleeper=fake.sleep,
    )
    assert ok is False
    assert fake.keys == []  # Command-W would have hit the wrong workbook
    assert "could not make it frontmost" in message


def test_close_document_aborts_if_the_raise_left_another_window_in_front():
    """A lying raiser must not be enough to make Command-W fire."""
    fake = FakeDesktop([RESTORED, doc("Probe_Alpha", wid=7, offscreen=True)])
    ok, message = wc.close_document(
        "Probe_Alpha",
        enumerator=fake.enumerate,
        key_sender=fake.send_key,
        raiser=lambda stem: (True, "stub claims success but changed nothing"),
        sleeper=fake.sleep,
    )
    assert ok is False
    assert "SAFETY ABORT" in message
    assert fake.keys == []


# --- close_all_generated ----------------------------------------------------


def _debris_desktop(**kwargs) -> FakeDesktop:
    """The real mess from a test session, including the user's own workbook."""
    return FakeDesktop(
        [
            DOCK_TILE_EV,  # the user's real workbook - MUST SURVIVE
            RESTORED,  # a validation run's workbook, not covered by a prefix
            DOCK_TILE_FFC,
            DOCK_TILE_FFC_V2,
            OFFSCREEN_PROBE_A,
            OFFSCREEN_NOFILTER,
            doc("ProbeB_CalcColor", wid=271840, offscreen=True),
            doc("Quarterly_Sales_Review_QA_ready", wid=271424, offscreen=True),
            PROGRESS_DIALOG,
            ERROR_DIALOG,
        ],
        **kwargs,
    )


def test_close_all_generated_never_matches_outside_its_prefixes():
    """SAFETY CRITICAL: the user's Quarterly_Sales_Review is open.

    It must not be selected by any of the test-debris prefixes, nor must the
    ``_QA_ready`` variant, nor the unrelated validation workbook.
    """
    fake = _debris_desktop()
    report = wc.close_all_generated(
        ["Probe", "Full_Feature_Check", "NoFilter_Probe"],
        enumerator=fake.enumerate,
        clicker=fake.click,
        key_sender=fake.send_key,
    )
    assert sorted(report["would_close"]) == [
        "Full_Feature_Check",
        "Full_Feature_Check_v2",
        "NoFilter_Probe",
        "ProbeA_FilterOnly",
        "ProbeB_CalcColor",
    ]
    assert "Quarterly_Sales_Review" not in report["would_close"]
    assert "Quarterly_Sales_Review_QA_ready" not in report["would_close"]
    assert RESTORED["title"].removeprefix(wc.DOC_TITLE_PREFIX) not in report["would_close"]
    skipped = [s["stem"] for s in report["skipped"]]
    assert "Quarterly_Sales_Review" in skipped
    assert "Quarterly_Sales_Review_QA_ready" in skipped
    # Non-document windows are never candidates at all.
    assert PROGRESS_DIALOG["title"] not in report["would_close"]


def test_close_all_generated_matches_on_prefix_not_on_substring():
    fake = FakeDesktop([doc("Nightly_Probe_Report", wid=1), doc("Probe_Alpha", wid=2)])
    report = wc.close_all_generated(["Probe"], enumerator=fake.enumerate)
    assert report["would_close"] == ["Probe_Alpha"]


def test_close_all_generated_dry_run_sends_no_events():
    fake = _debris_desktop()
    report = wc.close_all_generated(
        ["Probe", "Full_Feature_Check", "NoFilter_Probe"],
        enumerator=fake.enumerate,
        clicker=fake.click,
        key_sender=fake.send_key,
        activator=fake.activate,
        opener=fake.open_file,
    )
    assert report["dry_run"] is True
    assert report["closed"] == []
    assert fake.clicks == [], "dry run must not click anything"
    assert fake.keys == [], "dry run must not send a keystroke"
    assert fake.activations == 0
    assert fake.opened == []
    assert len(fake.windows) == 10, "dry run must not change window state"


@pytest.mark.parametrize("bad", [[], [""], ["   "], ["Probe", ""]])
def test_close_all_generated_rejects_prefixes_that_match_everything(bad):
    fake = _debris_desktop()
    if bad == ["Probe", ""]:
        # An empty entry is dropped, and the remaining specific prefix still works.
        assert wc.close_all_generated(bad, enumerator=fake.enumerate)["prefixes"] == ["Probe"]
        return
    with pytest.raises(ValueError):
        wc.close_all_generated(bad, enumerator=fake.enumerate)


@pytest.mark.parametrize("short", ["E", "EV"])
def test_close_all_generated_rejects_dangerously_short_prefixes(short):
    fake = _debris_desktop()
    with pytest.raises(ValueError, match="too short"):
        wc.close_all_generated([short], enumerator=fake.enumerate)


def test_close_all_generated_closes_only_matches_when_armed():
    fake = _debris_desktop(on_key=lambda f: f.remove_frontmost_document())
    report = wc.close_all_generated(
        ["Probe", "Full_Feature_Check", "NoFilter_Probe"],
        dry_run=False,
        enumerator=fake.enumerate,
        clicker=fake.click,
        key_sender=fake.send_key,
        raiser=fake.raiser,
        sleeper=fake.sleep,
    )
    assert [c["stem"] for c in report["closed"]] == [
        "Full_Feature_Check",
        "Full_Feature_Check_v2",
        "ProbeA_FilterOnly",
        "NoFilter_Probe",
        "ProbeB_CalcColor",
    ]
    assert report["failed"] == []
    assert fake.keys == ["w"] * 5
    survivors = fake.titles()
    assert DOCK_TILE_EV["title"] in survivors
    assert wc.DOC_TITLE_PREFIX + "Quarterly_Sales_Review_QA_ready" in survivors
    assert RESTORED["title"] in survivors


def test_close_all_generated_closes_each_workbook_once_when_it_has_two_windows():
    fake = FakeDesktop(
        [doc("Probe_Alpha", wid=1, minimized=True), doc("Probe_Alpha", wid=2)],
        on_key=lambda f: f.remove_frontmost_document(),
    )
    report = wc.close_all_generated(
        ["Probe"],
        dry_run=False,
        enumerator=fake.enumerate,
        key_sender=fake.send_key,
        raiser=fake.raiser,
        sleeper=fake.sleep,
    )
    assert len(report["would_close"]) == 2
    assert len(report["closed"]) + len(report["failed"]) == 1
