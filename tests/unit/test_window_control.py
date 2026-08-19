"""Window-management tests - every OS interaction is faked.

No test here touches Quartz, osascript, `open` or the Tableau GUI: the enumerator,
clicker, key sender, activator and opener are all injected. The window geometry in
the fixtures is not invented - it was captured read-only from a live Tableau
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
# Husks of CLOSED workbooks. These were originally labelled "minimized while
# hidden", which is wrong and cost two bugs: 218x161 at (-234, 367) is the exact
# signature of a window Tableau has destroyed and the window server has not yet
# reaped. A genuinely minimized document keeps an on-screen Dock tile (DOCK_TILE_*).
STALE_PROBE_A = {
    "id": 271811,
    "title": "Tableau Public - ProbeA_FilterOnly",
    "x": -234.0,
    "y": 367.0,
    "width": 218.0,
    "height": 161.0,
    "on_screen": False,
}
STALE_NOFILTER = {
    "id": 271750,
    "title": "Tableau Public - NoFilter_Probe",
    "x": -234.0,
    "y": 367.0,
    "width": 218.0,
    "height": 161.0,
    "on_screen": False,
}
# The same two workbooks while genuinely open and minimized.
DOCK_TILE_PROBE_A = {
    "id": 271812,
    "title": "Tableau Public - ProbeA_FilterOnly",
    "x": 16.0,
    "y": 518.0,
    "width": 140.0,
    "height": 165.0,
    "on_screen": True,
}
DOCK_TILE_NOFILTER = {
    "id": 271751,
    "title": "Tableau Public - NoFilter_Probe",
    "x": 16.0,
    "y": 860.0,
    "width": 140.0,
    "height": 172.0,
    "on_screen": True,
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


def doc(stem: str, *, wid: int, minimized: bool = False, stale: bool = False) -> dict:
    """A synthetic document window with realistic bounds."""
    if stale:  # husk of a closed document, not a minimized one
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
    sent *nothing* - which is the whole point of dry-run mode.
    """

    def __init__(self, windows, *, on_key=None, on_click=None, on_open=None, app_active=True):
        self.windows = [dict(w) for w in windows]
        # Whether Tableau owns keyboard focus. Command-W goes to the ACTIVE APP,
        # so a fake that always says "yes" would hide the very bug this models.
        self.app_active = app_active
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
        self.app_active = True

    def is_active(self) -> bool:
        return self.app_active

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


def test_an_offscreen_window_is_a_husk_not_a_minimized_document():
    """218x161 at (-234, 367), absent on-screen, is a DESTROYED window.

    It was read as "minimized while hidden" for a long time and that reading cost
    two bugs at once (STALE WINDOWS at the top of window_control): a husk
    outranks a live Dock tile on area, so closing aimed at the husk and called a
    live workbook unreachable; and a husk never disappears, so the post-close
    check saw the title survive and reported every successful close as a failure.

    The corrected model is decidable because both halves are pinned here. A live
    window is always composited - full size, or as a Dock tile - so off-screen
    means gone; and minimizing does NOT take a window off-screen, so nothing
    legitimate is lost by discarding what is. ``is_minimized`` still answers True
    for an off-screen window, which is backwards compatibility for that flag and
    not a claim about the world: ``is_stale`` carries the model, and it is what
    every caller filters on.
    """
    husk = FakeDesktop([STALE_PROBE_A])
    w = classify(husk)[0]
    assert w.is_document
    assert not w.on_screen
    assert w.is_stale, "an off-screen window is the husk of a closed document"

    # Invisible to every caller that decides what to click, raise or close.
    assert wc.document_windows(enumerator=husk.enumerate) == []
    assert wc.find_document("ProbeA_FilterOnly", enumerator=husk.enumerate) is None
    assert wc.frontmost_document(enumerator=husk.enumerate) is None
    # Reachable only by asking for husks by name, which exists for diagnostics.
    diagnosed = wc.document_windows(enumerator=husk.enumerate, include_stale=True)
    assert [d.id for d in diagnosed] == [STALE_PROBE_A["id"]]

    # The same workbook, genuinely open and minimized: an on-screen Dock tile,
    # not stale, and still findable.
    tile = FakeDesktop([DOCK_TILE_PROBE_A])
    m = classify(tile)[0]
    assert m.on_screen and not m.is_stale and m.is_minimized
    assert [d.id for d in wc.document_windows(enumerator=tile.enumerate)] == [
        DOCK_TILE_PROBE_A["id"]
    ]
    found = wc.find_document("ProbeA_FilterOnly", enumerator=tile.enumerate)
    assert found is not None and found.id == DOCK_TILE_PROBE_A["id"]


def test_absence_from_the_onscreen_list_alone_marks_a_husk():
    """Full-size bounds, missing on-screen: still destroyed, not merely hidden.

    Absence from the on-screen list is the entire signal. The window server reaps
    husks lazily and does not promise to shrink them first, so a husk carrying
    the last live bounds has to be discarded on the same evidence as the 218x161
    one. Note what ``is_minimized`` says here: True, for a 1291x949 window that is
    neither minimized nor open. That is exactly why the decision is made on
    ``is_stale`` and why no caller reads the older flag on its own.
    """
    hidden = dict(RESTORED, on_screen=False, id=424242)
    fake = FakeDesktop([hidden])
    w = classify(fake)[0]

    assert w.is_stale
    assert wc.document_windows(enumerator=fake.enumerate) == []
    assert wc.frontmost_document(enumerator=fake.enumerate) is None
    assert wc.find_document(RESTORED["title"], enumerator=fake.enumerate) is None


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
    fake = FakeDesktop([DOCK_TILE_FFC, STALE_PROBE_A, RESTORED])
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
    fake = FakeDesktop([PROGRESS_DIALOG, DOCK_TILE_NOFILTER])
    hit = wc.find_document("NoFilter_Probe", enumerator=fake.enumerate)
    assert hit is not None
    assert hit.id == DOCK_TILE_NOFILTER["id"]


# --- click geometry ---------------------------------------------------------


def test_click_point_uses_live_bounds_not_constants():
    tile = classify(FakeDesktop([DOCK_TILE_EV]))[0]
    assert wc.click_point(tile) == (86, 412)  # centre of the live Dock tile
    restored = classify(FakeDesktop([RESTORED]))[0]
    assert wc.click_point(restored) == (866, 45)  # title bar of the live window


def test_click_point_refuses_offscreen_windows():
    offscreen = classify(FakeDesktop([STALE_PROBE_A]))[0]
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


def test_the_dock_tile_click_is_preferred_even_when_a_file_path_is_known(tmp_path):
    """`open -a` raises more reliably but does NOT activate the document.

    Reproduced live: with one workbook minimized behind another, closing it via
    `open -a` failed twice over 21s while consuming two blank Book windows --
    Command-W was closing those, because the window server reported the target as
    frontmost while Tableau's own active-document state pointed elsewhere. The
    same close via the Dock-tile click succeeded first time. Clicking the tile
    activates the document; re-opening the file only rearranges windows.
    """
    path = tmp_path / "Probe_Alpha.twbx"
    path.write_bytes(b"not really a workbook")
    fake = FakeDesktop(
        [doc("Probe_Alpha", wid=7, minimized=True)],
        on_click=lambda f: f.restore_and_front("Probe_Alpha"),
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
    assert fake.clicks == [(86, 222)]  # centre of the live tile
    assert fake.opened == [], "open -a must not be used while a tile is clickable"
    assert fake.activations == 1
    assert "HID click" in message


def test_open_a_is_used_only_when_there_is_nothing_to_click(tmp_path):
    """The fallback still exists for a window with no usable on-screen bounds."""
    path = tmp_path / "Probe_Alpha.twbx"
    path.write_bytes(b"not really a workbook")
    tiny = dict(doc("Probe_Alpha", wid=7, minimized=True), width=4.0, height=4.0)
    fake = FakeDesktop([tiny], on_open=lambda f: f.restore_and_front("Probe_Alpha"))
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
    assert fake.clicks == []
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


def test_unminimize_and_raise_treats_a_husk_as_not_open():
    """A destroyed window must not look like a minimized one.

    Reading the husk as "minimized off-screen" is what made this function report a
    live workbook as unreachable, and it would make the caller re-open a workbook
    the user had already closed.
    """
    fake = FakeDesktop([STALE_PROBE_A])
    ok, message = wc.unminimize_and_raise(
        "ProbeA_FilterOnly",
        enumerator=fake.enumerate,
        clicker=fake.click,
        activator=fake.activate,
        opener=fake.open_file,
        sleeper=fake.sleep,
    )
    assert ok is False
    assert fake.clicks == []  # never click at a guessed coordinate
    assert fake.opened == []  # and never re-open a closed workbook
    assert "ProbeA_FilterOnly" in message


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
        app_checker=fake.is_active,
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
        app_checker=fake.is_active,
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
        app_checker=fake.is_active,
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
        app_checker=fake.is_active,
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
        app_checker=fake.is_active,
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
        app_checker=fake.is_active,
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
        app_checker=fake.is_active,
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
        app_checker=fake.is_active,
        raiser=fake.raiser,
        sleeper=fake.sleep,
    )
    assert ok is True
    assert "closed" in message
    assert fake.keys == ["w"]
    # The user's workbook is untouched.
    assert DOCK_TILE_EV["title"] in fake.titles()


def test_close_document_refuses_when_the_target_cannot_be_raised():
    fake = FakeDesktop([doc("Probe_Alpha", wid=7, minimized=True), RESTORED])
    ok, message = wc.close_document(
        "Probe_Alpha",
        enumerator=fake.enumerate,
        key_sender=fake.send_key,
        app_checker=fake.is_active,
        raiser=lambda stem: (False, "stub refuses to raise"),
        sleeper=fake.sleep,
    )
    assert ok is False
    assert fake.keys == []  # Command-W would have hit the wrong workbook
    assert "could not make it frontmost" in message


def test_close_document_aborts_if_the_raise_left_another_window_in_front():
    """A lying raiser must not be enough to make Command-W fire."""
    fake = FakeDesktop([RESTORED, doc("Probe_Alpha", wid=7, minimized=True)])
    ok, message = wc.close_document(
        "Probe_Alpha",
        enumerator=fake.enumerate,
        key_sender=fake.send_key,
        app_checker=fake.is_active,
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
            DOCK_TILE_PROBE_A,
            DOCK_TILE_NOFILTER,
            doc("ProbeB_CalcColor", wid=271840, minimized=True),
            doc("Quarterly_Sales_Review_QA_ready", wid=271424, minimized=True),
            PROGRESS_DIALOG,
            ERROR_DIALOG,
        ],
        **kwargs,
    )


def test_close_all_generated_never_matches_outside_its_prefixes():
    """SAFETY CRITICAL: the user's own workbook Quarterly_Sales_Review is open.

    It must not be selected by any of the test-debris prefixes, nor must the
    ``_QA_ready`` variant, nor the unrelated validation workbook.
    """
    fake = _debris_desktop()
    report = wc.close_all_generated(
        ["Probe", "Full_Feature_Check", "NoFilter_Probe"],
        enumerator=fake.enumerate,
        clicker=fake.click,
        key_sender=fake.send_key,
        app_checker=fake.is_active,
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
        app_checker=fake.is_active,
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
        app_checker=fake.is_active,
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
    """One workbook, two windows: closed ONCE, and actually closed.

    The assertion here used to be ``len(closed) + len(failed) == 1``, which the
    test's name promised more than: a run in which the close was refused or
    bailed out satisfied it identically, so only de-duplication was ever tested.
    Both halves are checked now - the stem appears exactly once and in
    ``closed``, nothing lands in ``failed``, exactly one Command-W is sent, and
    no window with that title survives.

    The fake also has to model Command-W properly for that to be answerable.
    Closing a document destroys *every* window it owns, so the shared
    ``remove_frontmost_document`` (which drops exactly one) leaves the second
    window standing, ``close_document`` correctly refuses to claim a success it
    cannot prove, and the old assertion counted that refusal as a pass.
    """

    def close_the_whole_document(f: FakeDesktop) -> None:
        front = next(
            (w for w in f.windows if w["title"].startswith(wc.DOC_TITLE_PREFIX) and w["on_screen"]),
            None,
        )
        if front is not None:
            f.windows = [w for w in f.windows if w["title"] != front["title"]]

    fake = FakeDesktop(
        [doc("Probe_Alpha", wid=1, minimized=True), doc("Probe_Alpha", wid=2)],
        on_key=close_the_whole_document,
    )
    report = wc.close_all_generated(
        ["Probe"],
        dry_run=False,
        enumerator=fake.enumerate,
        key_sender=fake.send_key,
        app_checker=fake.is_active,
        raiser=fake.raiser,
        sleeper=fake.sleep,
    )
    # Both windows are candidates...
    assert len(report["would_close"]) == 2
    # ...and the workbook behind them is closed exactly once, successfully.
    assert [c["stem"] for c in report["closed"]] == ["Probe_Alpha"]
    assert report["failed"] == [], report["failed"]
    assert fake.keys == ["w"], "one workbook must cost exactly one Command-W"
    assert fake.titles() == [], f"a window with that title survived: {fake.titles()}"


# --- close_all_generated: known_paths and husks -----------------------------
#
# These pin the two defects that made the live test tier close nine workbooks and
# report eight of them as failures:
#
#   COULD NOT CLOSE LiveTest_022054_bar: ... is minimized off-screen (bounds
#   218x161 at -234,367) and offers no on-screen tile to click.
#   COULD NOT CLOSE LiveTest_022850_bar: Command-W was sent but ... is still open.
#
# Both messages were false. A screenshot of the live session showed a single real
# Tableau window while Quartz reported twenty-six documents; every workbook named
# in those errors sat in Tableau's *recent files* list, i.e. closed. The husks
# beat live Dock tiles on area during target selection, and they never disappear,
# so the post-close check could never succeed.


def test_close_all_generated_ignores_husks_of_workbooks_it_already_closed():
    """The false-failure bug. A husk is not something left to close."""
    fake = FakeDesktop([doc("LiveTest_022054_bar", wid=1, stale=True)])
    report = wc.close_all_generated(
        ["LiveTest"],
        dry_run=False,
        enumerator=fake.enumerate,
        clicker=fake.click,
        key_sender=fake.send_key,
        app_checker=fake.is_active,
        opener=fake.open_file,
        sleeper=fake.sleep,
    )
    assert report["would_close"] == []
    assert report["failed"] == []
    assert report["already_closed"] == ["LiveTest_022054_bar"]
    assert fake.keys == []
    assert fake.opened == []  # a closed workbook is never re-opened to be closed


def test_a_husk_never_outranks_the_live_window_of_the_same_workbook():
    """Target selection took the largest match, and the husk is larger.

    Husk 218x161 = 35,098 px^2 beats a live Dock tile 140x161 = 22,540 px^2, so the
    code aimed every close at a window that no longer existed.
    """
    fake = FakeDesktop(
        [
            doc("LiveTest_022850_bar", wid=1, stale=True),
            doc("LiveTest_022850_bar", wid=2, minimized=True),
        ],
        on_key=lambda f: f.remove_frontmost_document(),
    )
    report = wc.close_all_generated(
        ["LiveTest"],
        dry_run=False,
        known_paths={"LiveTest_022850_bar": Path("/nonexistent/x.twbx")},
        enumerator=fake.enumerate,
        clicker=fake.click,
        key_sender=fake.send_key,
        app_checker=fake.is_active,
        activator=fake.activate,
        opener=fake.open_file,
        sleeper=fake.sleep,
    )
    assert report["would_close"] == ["LiveTest_022850_bar"]  # once, not twice
    assert [w["id"] for w in report["matched"]] == [2]  # the live tile, not the husk


def test_close_all_generated_closes_a_minimized_workbook(tmp_path):
    """known_paths is supplied, but a minimized workbook has a tile, so the tile wins."""
    path = tmp_path / "LiveTest_022850_bar.twbx"
    path.write_bytes(b"not really a workbook")
    fake = FakeDesktop(
        [doc("LiveTest_022850_bar", wid=1, minimized=True)],
        on_click=lambda f: f.restore_and_front("LiveTest_022850_bar"),
        on_key=lambda f: f.remove_frontmost_document(),
    )
    report = wc.close_all_generated(
        ["LiveTest"],
        dry_run=False,
        known_paths={"LiveTest_022850_bar": path},
        enumerator=fake.enumerate,
        clicker=fake.click,
        key_sender=fake.send_key,
        app_checker=fake.is_active,
        activator=fake.activate,
        opener=fake.open_file,
        sleeper=fake.sleep,
    )
    assert [e["stem"] for e in report["closed"]] == ["LiveTest_022850_bar"]
    assert report["failed"] == []
    assert fake.clicks == [(86, 222)]  # the tile activates the document
    assert fake.opened == []
    assert fake.keys == ["w"]
    assert fake.titles() == []


def test_without_a_known_path_a_minimized_workbook_is_closed_via_its_dock_tile():
    """known_paths is an optimisation, not a requirement: the tile still works."""
    fake = FakeDesktop(
        [doc("LiveTest_022850_bar", wid=1, minimized=True)],
        on_click=lambda f: f.restore_and_front("LiveTest_022850_bar"),
        on_key=lambda f: f.remove_frontmost_document(),
    )
    report = wc.close_all_generated(
        ["LiveTest"],
        dry_run=False,
        enumerator=fake.enumerate,
        clicker=fake.click,
        key_sender=fake.send_key,
        app_checker=fake.is_active,
        activator=fake.activate,
        opener=fake.open_file,
        sleeper=fake.sleep,
    )
    assert [e["stem"] for e in report["closed"]] == ["LiveTest_022850_bar"]
    assert fake.clicks == [(86, 222)]  # centre of the live tile
    assert fake.opened == []


def test_known_paths_never_widen_what_close_all_generated_is_allowed_to_touch():
    """SAFETY CRITICAL: a path is a means of raising a window, not a licence to close one.

    Supplying a path for the user's own workbook must not make it a candidate; the
    prefix check is still the only thing that selects.
    """
    fake = FakeDesktop([DOCK_TILE_EV, doc("LiveTest_022850_bar", wid=1, minimized=True)])
    report = wc.close_all_generated(
        ["LiveTest"],
        known_paths={
            "Quarterly_Sales_Review": Path("/tmp/EV.twbx"),
            "LiveTest_022850_bar": Path("/tmp/bar.twbx"),
        },
        enumerator=fake.enumerate,
    )
    assert report["would_close"] == ["LiveTest_022850_bar"]
    assert "Quarterly_Sales_Review" in [s["stem"] for s in report["skipped"]]


def test_known_paths_are_matched_on_the_normalised_stem():
    """Tableau's window title need not match the file name byte for byte."""
    # No clickable tile, so the open -a fallback runs and the path lookup matters.
    unclickable = dict(doc("LiveTest 022850 bar", wid=1, minimized=True), width=4.0, height=4.0)
    fake = FakeDesktop(
        [unclickable],
        on_open=lambda f: f.restore_and_front("LiveTest 022850 bar"),
        on_key=lambda f: f.remove_frontmost_document(),
    )
    report = wc.close_all_generated(
        ["LiveTest"],
        dry_run=False,
        known_paths={"LiveTest_022850_bar": Path("/nonexistent/LiveTest_022850_bar.twbx")},
        enumerator=fake.enumerate,
        clicker=fake.click,
        key_sender=fake.send_key,
        app_checker=fake.is_active,
        activator=fake.activate,
        opener=fake.open_file,
        sleeper=fake.sleep,
    )
    # The path was found for this stem, so the open -a branch was taken - which is
    # proved by the failure being about the missing FILE, not a missing tile.
    assert report["closed"] == []
    assert "file_path does not exist" in report["failed"][0]["reason"]


def test_close_document_says_a_husk_only_workbook_is_already_closed():
    fake = FakeDesktop([doc("LiveTest_022054_bar", wid=1, stale=True)])
    ok, message = wc.close_document(
        "LiveTest_022054_bar",
        enumerator=fake.enumerate,
        key_sender=fake.send_key,
        app_checker=fake.is_active,
        clicker=fake.click,
        opener=fake.open_file,
        sleeper=fake.sleep,
    )
    assert ok is False
    assert "already closed" in message
    assert fake.keys == [] and fake.opened == []


def test_dry_run_with_known_paths_still_sends_nothing():
    fake = FakeDesktop([doc("LiveTest_022850_bar", wid=1, minimized=True)])
    report = wc.close_all_generated(
        ["LiveTest"],
        known_paths={"LiveTest_022850_bar": Path("/tmp/bar.twbx")},
        enumerator=fake.enumerate,
        clicker=fake.click,
        key_sender=fake.send_key,
        app_checker=fake.is_active,
        opener=fake.open_file,
    )
    assert report["dry_run"] is True
    assert report["would_close"] == ["LiveTest_022850_bar"]
    assert fake.keys == [] and fake.clicks == [] and fake.opened == []


# --- keyboard focus belongs to an APP, not a window -------------------------
#
# Every guard above this point ranks only Tableau's OWN windows, so all of them
# pass happily while the user is typing in a browser. Command-W is posted with
# CGEventPost(kCGHIDEventTap, ...), which delivers to whatever application owns
# keyboard focus. The result was a close that shut the user's front Chrome tab
# and then reported "Command-W was sent but the workbook is still open".


def test_close_refuses_when_tableau_is_not_the_active_application():
    fake = FakeDesktop(
        [doc("Probe_Alpha", wid=7)],
        app_active=False,
        on_key=lambda f: f.remove_frontmost_document(),
    )
    ok, message = wc.close_document(
        "Probe_Alpha",
        enumerator=fake.enumerate,
        key_sender=fake.send_key,
        raiser=fake.raiser,
        sleeper=fake.sleep,
        app_checker=lambda: False,  # activation never takes effect
        activator=lambda: None,
        app_namer=lambda: "Google Chrome",
    )
    assert ok is False
    assert "active application" in message
    assert "Google Chrome" in message, "the message must name where focus actually is"
    assert fake.keys == [], "a keystroke escaped to whatever app the user was in"


def test_close_activates_tableau_first_rather_than_giving_up():
    """Refusing outright would break every run driven from a terminal."""
    fake = FakeDesktop(
        [doc("Probe_Alpha", wid=7)],
        app_active=False,
        on_key=lambda f: f.remove_frontmost_document(),
    )
    ok, _ = wc.close_document(
        "Probe_Alpha",
        enumerator=fake.enumerate,
        key_sender=fake.send_key,
        activator=fake.activate,
        raiser=fake.raiser,
        sleeper=fake.sleep,
        app_checker=fake.is_active,
    )
    assert ok is True
    assert fake.activations == 1
    assert fake.keys == ["w"]


def test_tableau_is_active_recognises_the_process_name():
    assert wc.tableau_is_active(runner=lambda _s: "Tableau Public") is True
    assert wc.tableau_is_active(runner=lambda _s: "Google Chrome") is False


def test_frontmost_app_name_returns_none_when_it_cannot_be_determined():
    def boom(_script):
        raise wc.DesktopError("System Events is not responding")

    assert wc.frontmost_app_name(runner=boom) is None
    assert wc.tableau_is_active(runner=boom) is False


# --- a stale save prompt must not block every future close ------------------


def test_a_husk_of_a_save_prompt_is_not_treated_as_an_open_dialog():
    """Dialogs leave husks exactly as documents do.

    The sign-in window's ~59x112 husk once made publishing believe sign-in was
    permanently required. A stale save prompt is worse: it would abort EVERY
    close from then on with "Tableau is already showing a save prompt".
    """
    stale_prompt = dict(SAVE_PROMPT, on_screen=False)
    assert wc.detect_save_prompt(enumerator=lambda: [stale_prompt]) is None
    # ...while a live one is still caught.
    assert wc.detect_save_prompt(enumerator=lambda: [dict(SAVE_PROMPT)]) is not None


def test_a_husk_of_a_save_prompt_does_not_block_a_close():
    fake = FakeDesktop(
        [doc("Probe_Alpha", wid=7), dict(SAVE_PROMPT, on_screen=False)],
        on_key=lambda f: f.remove_frontmost_document(),
    )
    ok, message = wc.close_document(
        "Probe_Alpha",
        enumerator=fake.enumerate,
        key_sender=fake.send_key,
        raiser=fake.raiser,
        sleeper=fake.sleep,
        app_checker=fake.is_active,
    )
    assert ok is True, message


def test_a_husk_only_stem_is_reported_as_already_closed_not_as_a_failure():
    """Teardown must judge by outcome, not by close_document's return value.

    close_document REFUSES a stem that resolves only to a husk ("already closed,
    nothing to do") -- which is the goal state. Reporting that under COULD NOT
    CLOSE sends someone hunting for a window that does not exist, which is
    exactly the false alarm the husk work was meant to end.
    """
    fake = FakeDesktop([doc("LiveTest_1_gone", wid=1, stale=True)])
    report = wc.close_all_generated(
        ["LiveTest"],
        dry_run=False,
        enumerator=fake.enumerate,
        key_sender=fake.send_key,
        app_checker=fake.is_active,
        sleeper=fake.sleep,
    )
    assert report["failed"] == []
    assert "LiveTest_1_gone" in report["already_closed"]


def test_a_genuinely_stuck_window_is_still_reported_as_failed():
    """The outcome rule must not swallow a real failure."""
    fake = FakeDesktop([doc("LiveTest_1_stuck", wid=1)])  # on-screen, never closes
    report = wc.close_all_generated(
        ["LiveTest"],
        dry_run=False,
        enumerator=fake.enumerate,
        key_sender=fake.send_key,
        app_checker=fake.is_active,
        raiser=fake.raiser,
        sleeper=fake.sleep,
    )
    assert [e["stem"] for e in report["failed"]] == ["LiveTest_1_stuck"]
    assert report["closed"] == []


def test_a_dropped_keystroke_is_resent_once():
    """Tableau drops the occasional Command-W when it is busy.

    With a dozen documents loaded, one workbook per live run survived the first
    keystroke while its window sat restored and frontmost, with no save prompt
    and no dialog. One resend is bounded and safe: every guard is re-evaluated.
    """
    state = {"keys": 0}

    def flaky(_key):
        state["keys"] += 1
        if state["keys"] >= 2:  # the second one lands
            fake.remove_frontmost_document()

    fake = FakeDesktop([doc("Probe_Alpha", wid=7)], on_key=flaky)
    ok, message = wc.close_document(
        "Probe_Alpha",
        enumerator=fake.enumerate,
        key_sender=fake.send_key,
        raiser=fake.raiser,
        sleeper=fake.sleep,
        app_checker=fake.is_active,
    )
    assert ok is True, message
    assert state["keys"] == 2


def test_the_resend_is_bounded_to_one_extra_attempt():
    """A window that never closes must not loop forever."""
    fake = FakeDesktop([doc("Probe_Alpha", wid=7)])  # on_key does nothing
    ok, message = wc.close_document(
        "Probe_Alpha",
        enumerator=fake.enumerate,
        key_sender=fake.send_key,
        raiser=fake.raiser,
        sleeper=fake.sleep,
        app_checker=fake.is_active,
    )
    assert ok is False
    assert fake.keys == ["w", "w"], "expected exactly two attempts"
    assert "twice" in message


def test_a_save_prompt_still_stops_the_resend():
    """The retry must not bulldoze past the one thing this module never answers."""
    fake = FakeDesktop(
        [doc("Probe_Alpha", wid=7)],
        on_key=lambda f: f.add(dict(SAVE_PROMPT)),
    )
    ok, message = wc.close_document(
        "Probe_Alpha",
        enumerator=fake.enumerate,
        key_sender=fake.send_key,
        raiser=fake.raiser,
        sleeper=fake.sleep,
        app_checker=fake.is_active,
    )
    assert ok is False
    assert "BAILED OUT" in message
    assert fake.keys == ["w"], "a save prompt must stop it dead, not trigger a resend"
