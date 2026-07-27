"""Identify, raise and close individual Tableau Public document windows.

WHY THIS MODULE EXISTS
----------------------
Driving the publish flow leaves a trail of open workbooks. Every one of them is a
hazard: Tableau's menu commands apply to whatever document is active, so a stale
window that happens to be frontmost can receive a publish command intended for a
different workbook. Before this module there was no way to close *one specific*
workbook or to reliably raise one, so cleanup meant closing everything by hand.

WHY IT LOOKS LIKE THIS (each point cost real debugging time; do not "simplify")
------------------------------------------------------------------------------
1. Tableau Public 2026.2.0 is a **Qt** app. System Events ``click`` and
   ``perform action "AXPress"`` report success and do nothing. Only genuine HID
   events posted with ``Quartz.CGEventPost(kCGHIDEventTap, ...)`` have any effect,
   so every interaction here goes through :func:`~.tableau_app.real_click` or
   :func:`post_command_key`.
2. Accessibility reports ``count of windows = 0`` for Tableau even with document
   windows visibly open. AX can neither enumerate nor raise them, which rules out
   the ordinary ``AXRaise`` / ``AXMinimized = false`` approach entirely.
3. Window discovery therefore uses ``CGWindowListCopyWindowInfo``.
   ``kCGWindowListOptionOnScreenOnly`` is the list of windows that actually exist;
   ``kCGWindowListOptionAll`` additionally returns **destroyed** windows that the
   window server has not yet reaped. See STALE WINDOWS below — this was originally
   documented here as a minimized-window signal, which is wrong and caused two
   separate bugs.
4. A minimized Tableau document keeps a **Dock tile**, and that tile *is* on
   screen. So the on-screen list is sufficient to find minimized windows too, and
   nothing legitimate is lost by ignoring the all-windows list.

5. Tableau's **Window menu lists worksheets, not documents**, so it cannot be used
   to identify or select a workbook.
6. Document windows are titled exactly ``Tableau Public - <workbook stem>``.

STALE WINDOWS
-------------
Every workbook Tableau has *ever* opened leaves a husk behind: an entry that
survives in ``kCGWindowListOptionAll`` after the document is closed, always with
the exact bounds ``218x161 at (-234, 367)``. Directly observed: with one workbook
open, the same title appeared twice — once live at ``1291x949 at (221, 33)`` and
once as a husk — and a screenshot confirmed a single real window, with every other
"open" workbook sitting in Tableau's *recent files* list.

Twenty-six husks accumulated over two test runs, and they broke closing in two
ways at once. Target selection picks the largest matching window, and a husk
(218x161 = 35,098 px^2) outranks a live Dock tile (140x165 = 23,100 px^2), so the
code aimed at the husk and reported a live workbook as "minimized off-screen with
no tile to click". Worse, the post-close check asks whether any window with that
title remains; the husk always does, so **every successful close was reported as a
failure**. Teardown then left workbooks open that it had in fact already closed.

Windows are therefore classified as stale when they appear only in the all-windows
list, and :func:`document_windows` hides them by default. The cost is that a
*hidden* Tableau (Command-H) looks like it has no documents; that is a safe
failure, since every caller here refuses to act on a window it cannot find.

SAFETY POSTURE
--------------
Closing a window can destroy unsaved work, so this module is deliberately timid:
it refuses to act on a window it cannot positively identify by title, it never
answers a "save changes?" prompt, and bulk cleanup defaults to a dry run.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .tableau_app import PROCESS_NAME, DesktopError, find_app, osascript, real_click

DOC_TITLE_PREFIX = "Tableau Public - "

# --- minimized-window heuristics -------------------------------------------
# Measured on Tableau Public 2026.2.0 (macOS 15, Dock on the left edge):
#   * a restored document window is 1291x949 at x=221, y=33, on-screen;
#   * a window minimized into the Dock keeps its title and owner but shrinks to a
#     Dock *tile* of roughly 140x161..140x190 at the Dock's x (16 here), and is
#     still reported as on-screen;
#   * bounds of 218x161 at (-234, 367), absent from the on-screen list, are NOT a
#     minimized window. That is the husk of a CLOSED one — see STALE WINDOWS
#     above. This comment previously said the opposite and cost two bugs.
# No public API exposes "is minimized" for another process's windows, so this is a
# heuristic, and it is wrong in one known way:
#   * a genuinely tiny restored window would be misreported, which Tableau's own
#     minimum document size (far above 320x320) makes unreachable in practice.
# Coordinates are deliberately NOT part of the test: negative x/y is normal on a
# multi-monitor layout with a display left of or above the primary.
MINIMIZED_TILE_MAX_EDGE = 320
UNUSABLE_EDGE = 10

# A title bar click lands here relative to the window's top-left corner.
TITLE_BAR_OFFSET_Y = 12

# Bulk cleanup guard: a short prefix such as "E" would sweep up a user's real
# workbook, so prefixes must be specific enough to be deliberate.
MIN_PREFIX_LEN = 3

# Titles Tableau/macOS use for a "do you want to save?" surface. Matching is
# advisory only: the close path also refuses to claim success whenever the target
# window survives, so an unrecognised prompt still fails safe.
SAVE_PROMPT_TITLE_HINTS = (
    "save changes",
    "do you want to save",
    "unsaved change",
    "save workbook",
    "save the changes",
)

KEY_CODES = {"w": 13}

#: Returns raw window records: ``id, title, x, y, width, height, on_screen``,
#: on-screen windows first in front-to-back order. Injectable for testing.
Enumerator = Callable[[], list[dict]]
#: ``(x, y) -> None`` — posts a real HID click. Injectable for testing.
Clicker = Callable[[float, float], None]
#: ``(key) -> None`` — posts a real HID Command-<key>. Injectable for testing.
KeySender = Callable[[str], None]
Sleeper = Callable[[float], None]
Activator = Callable[[], None]
Opener = Callable[[Path], None]
Raiser = Callable[[str], "tuple[bool, str]"]


@dataclass(frozen=True)
class WindowInfo:
    """One window belonging to the Tableau Public process."""

    id: int
    title: str
    workbook_stem: str | None
    x: float
    y: float
    width: float
    height: float
    is_minimized: bool
    is_document: bool
    on_screen: bool = True

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def is_stale(self) -> bool:
        """True when this is a husk of a window Tableau has already destroyed.

        A live window is always composited — a full-size one directly, a minimized
        one as its Dock tile — so anything the window server reports as off-screen
        no longer exists. See the STALE WINDOWS note at the top of this module.
        """
        return not self.on_screen

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "workbook_stem": self.workbook_stem,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "is_minimized": self.is_minimized,
            "is_document": self.is_document,
            "on_screen": self.on_screen,
            "is_stale": self.is_stale,
        }


# --- naming ----------------------------------------------------------------


def normalise_stem(value: str) -> str:
    """Canonical form used for every workbook-name comparison.

    Tolerates the three shapes a caller realistically has to hand: a bare stem, a
    file name (``X.twbx``) and a full window title (``Tableau Public - X``).
    ``_`` becomes a space to match the existing publisher behaviour, because
    Tableau shows underscores in titles while humans type spaces.
    """
    text = value.strip()
    if text.startswith(DOC_TITLE_PREFIX):
        text = text[len(DOC_TITLE_PREFIX) :]
    for suffix in (".twbx", ".twb"):
        if text.lower().endswith(suffix):
            text = text[: -len(suffix)]
            break
    return " ".join(text.replace("_", " ").lower().split())


def _stem_from_title(title: str) -> str | None:
    if not title.startswith(DOC_TITLE_PREFIX):
        return None
    stem = title[len(DOC_TITLE_PREFIX) :].strip()
    return stem or None


def _looks_minimized(x: float, y: float, width: float, height: float, on_screen: bool) -> bool:
    """Size is the signal. See MINIMIZED_TILE_MAX_EDGE for the measurements.

    Position deliberately plays no part. An earlier version also treated any
    negative x or y as minimized, which is wrong on any multi-monitor layout: a
    display arranged to the left of (or above) the primary has negative global
    coordinates, so a perfectly normal 1291x949 Tableau window sitting there was
    classified as minimized. ``frontmost_document`` skips minimized windows, so
    every close on such a layout aborted with "frontmost document is None" and
    every raise advised reopening the file. It failed closed, but it failed
    always.

    An off-screen window is reported as minimized only for backwards
    compatibility of this flag; ``WindowInfo.is_stale`` is the signal that
    actually matters there, and callers filter on it.
    """
    if not on_screen:
        return True
    return width <= MINIMIZED_TILE_MAX_EDGE and height <= MINIMIZED_TILE_MAX_EDGE


# --- discovery -------------------------------------------------------------


def quartz_windows() -> list[dict]:
    """Default enumerator: Tableau's windows straight from the window server.

    Both CoreGraphics lists are queried, but they mean different things. The
    on-screen list is the set of windows that **exist**, ordered front-to-back;
    minimized documents appear in it as their Dock tiles. The all-windows list
    adds entries the window server has not yet reaped for windows that are
    already **destroyed**, which is why everything it contributes is flagged
    ``on_screen=False`` and treated as stale (see STALE WINDOWS above). It is
    queried only so that callers can report husks as diagnostics, never to decide
    what to click or close. On-screen windows are returned first, in front-to-back
    order, so callers can treat the first entry as the frontmost.

    Untitled windows are dropped. Tableau litters the window server with dozens of
    untitled 1512x33 and 500x500 helper surfaces; keeping them would add noise to
    every report without ever helping identify a document.
    """
    try:
        import Quartz
    except ImportError:  # pragma: no cover - environment guard
        return []

    def _query(option: int) -> list[dict]:
        return list(
            Quartz.CGWindowListCopyWindowInfo(
                option | Quartz.kCGWindowListExcludeDesktopElements,
                Quartz.kCGNullWindowID,
            )
            or []
        )

    def _row(w: dict, *, on_screen: bool) -> dict | None:
        if "Tableau" not in (w.get("kCGWindowOwnerName") or ""):
            return None
        if int(w.get("kCGWindowLayer", 0)) != 0:  # menus, popovers, tooltips
            return None
        title = w.get("kCGWindowName") or ""
        if not title.strip():
            return None
        b = w.get("kCGWindowBounds") or {}
        return {
            "id": int(w.get("kCGWindowNumber", 0)),
            "title": title,
            "x": float(b.get("X", 0.0)),
            "y": float(b.get("Y", 0.0)),
            "width": float(b.get("Width", 0.0)),
            "height": float(b.get("Height", 0.0)),
            "on_screen": on_screen,
        }

    rows: list[dict] = []
    seen: set[int] = set()
    for w in _query(Quartz.kCGWindowListOptionOnScreenOnly):
        row = _row(w, on_screen=True)
        if row and row["id"] not in seen:
            seen.add(row["id"])
            rows.append(row)
    for w in _query(Quartz.kCGWindowListOptionAll):
        row = _row(w, on_screen=False)
        if row and row["id"] not in seen:
            seen.add(row["id"])
            rows.append(row)
    return rows


def classify_windows(*, enumerator: Enumerator | None = None) -> list[WindowInfo]:
    """All Tableau windows, tagged as document/minimized, frontmost first."""
    raw = (enumerator or quartz_windows)()
    out: list[WindowInfo] = []
    for w in raw:
        title = str(w.get("title") or "")
        x = float(w.get("x", 0.0))
        y = float(w.get("y", 0.0))
        width = float(w.get("width", 0.0))
        height = float(w.get("height", 0.0))
        on_screen = bool(w.get("on_screen", True))
        stem = _stem_from_title(title)
        out.append(
            WindowInfo(
                id=int(w.get("id", 0)),
                title=title,
                workbook_stem=stem,
                x=x,
                y=y,
                width=width,
                height=height,
                is_minimized=_looks_minimized(x, y, width, height, on_screen),
                is_document=stem is not None,
                on_screen=on_screen,
            )
        )
    return out


def document_windows(
    *, enumerator: Enumerator | None = None, include_stale: bool = False
) -> list[WindowInfo]:
    """Open document windows, frontmost first.

    Husks of closed documents are excluded unless ``include_stale`` is set, which
    exists for diagnostics only. Including them is never right for deciding what to
    click or close: a husk outranks a live Dock tile on area, and it never
    disappears, so it defeats both target selection and close verification. See the
    STALE WINDOWS note at the top of this module.
    """
    return [
        w
        for w in classify_windows(enumerator=enumerator)
        if w.is_document and (include_stale or not w.is_stale)
    ]


def frontmost_document(*, enumerator: Enumerator | None = None) -> WindowInfo | None:
    """The document window a menu command would currently be dispatched to."""
    for w in document_windows(enumerator=enumerator):
        if w.on_screen and not w.is_minimized:
            return w
    return None


def find_document(stem: str, *, enumerator: Enumerator | None = None) -> WindowInfo | None:
    """Locate a document window by workbook stem.

    Matching is case-insensitive and treats ``_`` as a space. An exact match always
    beats a substring match — without that rule ``Full_Feature_Check`` would be
    ambiguous with ``Full_Feature_Check_v2``. Among equally good matches the
    largest window wins, because duplicates are usually one restored window plus
    one or more minimized Dock tiles, and the restored one is the useful target.
    """
    needle = normalise_stem(stem)
    if not needle:
        return None
    docs = document_windows(enumerator=enumerator)
    exact = [d for d in docs if normalise_stem(d.workbook_stem or "") == needle]
    partial = [d for d in docs if needle in normalise_stem(d.workbook_stem or "")]
    pool = exact or partial
    if not pool:
        return None
    return max(pool, key=lambda d: (d.area, -d.id))


def open_document_stems(*, enumerator: Enumerator | None = None) -> list[str]:
    return [d.workbook_stem or "" for d in document_windows(enumerator=enumerator)]


# --- real HID input --------------------------------------------------------


def post_command_key(key: str, *, settle: float = 0.12) -> None:
    """Post a real Command-<key> HID keystroke.

    System Events' ``keystroke`` goes through the Accessibility layer that Qt
    ignores (same failure mode as ``click``/``AXPress``), so the event is built and
    posted through Quartz exactly like :func:`~.tableau_app.real_click`.
    """
    code = KEY_CODES.get(key.lower())
    if code is None:
        raise DesktopError(f"unsupported key {key!r}; known keys: {sorted(KEY_CODES)}")
    import Quartz

    source = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
    for down in (True, False):
        event = Quartz.CGEventCreateKeyboardEvent(source, code, down)
        Quartz.CGEventSetFlags(event, Quartz.kCGEventFlagMaskCommand)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
        time.sleep(0.05)
    time.sleep(settle)


def activate_app() -> None:
    """Bring the Tableau process forward. Required before `open -a` will restore."""
    osascript(f'tell application "{PROCESS_NAME}" to activate')


def frontmost_app_name(*, runner: Callable[[str], str] | None = None) -> str | None:
    """Name of the application that currently owns keyboard focus, or None."""
    try:
        name = (runner or osascript)(
            'tell application "System Events" to get name of first application process '
            "whose frontmost is true"
        )
    except DesktopError:
        return None
    return name.strip() or None


def tableau_is_active(*, runner: Callable[[str], str] | None = None) -> bool:
    """True when Tableau owns keyboard focus, so a key event will reach it.

    Every keystroke this module sends goes through ``CGEventPost(kCGHIDEventTap,
    …)``, which is delivered to **whatever application is active**, not to a
    window we name. Nothing else here checks that.

    That gap is not theoretical. This server is normally driven from a terminal
    or editor while Tableau sits in the background, and
    :func:`frontmost_document` only ranks Tableau's *own* windows — it returns a
    confident answer even when Tableau is not the active app at all. Command-W
    aimed at a workbook would then close the front tab of whatever the user was
    actually looking at.
    """
    name = frontmost_app_name(runner=runner)
    return name is not None and PROCESS_NAME.lower() in name.lower()


def open_with_tableau(path: Path) -> None:
    """``open -a <Tableau> <file>`` — never shell=True, arguments always a list."""
    app = find_app()
    if not app:
        raise DesktopError("Tableau Public is not installed")
    proc = subprocess.run(
        ["open", "-a", app, str(path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        raise DesktopError(f"'open -a' failed for {path}: {proc.stderr.strip()[:300]}")


def click_point(window: WindowInfo) -> tuple[int, int] | None:
    """Where to click to raise ``window``, computed from its LIVE bounds.

    Never a hardcoded screen position (MASTERPROMPT §4). Returns ``None`` when the
    window offers nothing clickable — off-screen, or degenerate bounds.
    """
    if window.width < UNUSABLE_EDGE or window.height < UNUSABLE_EDGE:
        return None
    if not window.on_screen:
        return None
    if window.is_minimized:
        # An on-screen minimized window is its Dock tile; clicking the tile centre
        # is what restores it.
        return int(window.x + window.width / 2), int(window.y + window.height / 2)
    return int(window.x + window.width / 2), int(window.y + TITLE_BAR_OFFSET_Y)


# --- raising ---------------------------------------------------------------


def unminimize_and_raise(
    stem: str,
    *,
    file_path: Path | None = None,
    enumerator: Enumerator | None = None,
    clicker: Clicker | None = None,
    activator: Activator | None = None,
    opener: Opener | None = None,
    sleeper: Sleeper | None = None,
    timeout: float = 12.0,
    poll: float = 1.0,
) -> tuple[bool, str]:
    """Restore and raise one workbook window. Returns ``(ok, message)``.

    Two paths, in this order:

    1. **A real HID click** on the window, at a point computed from its live
       bounds (Dock-tile centre when minimized, title bar when restored).
    2. **Re-open the file** (only when there is nothing clickable and
       ``file_path`` is known). ``open -a "Tableau Public" <file>`` un-minimizes
       the existing window and brings it forward at full size, but only if the app
       was activated first; Tableau focuses the existing window rather than
       loading a second copy.

    THE ORDER MATTERS, AND IT IS THE OPPOSITE OF WHAT IT LOOKS LIKE. ``open -a``
    raises the window more reliably, so it was tried first — but the window it
    raises is not necessarily the document Tableau considers *active*. The window
    server reports the target as frontmost while Tableau's own active-document
    state still points elsewhere, so a Command-W that passes every guard here
    closes a different workbook. Reproduced deliberately: with ``CloseTestA``
    minimized behind ``CloseTestB``, closing A via ``open -a`` failed twice over
    21s while consuming two blank ``Book`` windows — Command-W was closing those.
    The same close via the Dock-tile click succeeded first time. Clicking the tile
    activates the document inside Tableau; re-opening the file only rearranges
    windows.

    AX ``AXRaise`` is not attempted: Tableau exposes no windows to Accessibility.
    """
    sleep = sleeper or time.sleep
    target = find_document(stem, enumerator=enumerator)
    if target is None:
        openv = open_document_stems(enumerator=enumerator)
        return False, (
            f"no Tableau document window matching {stem!r}. Currently open: {openv or 'none'}. "
            f"Open the workbook first, or pass the exact stem shown in the window title."
        )

    already = frontmost_document(enumerator=enumerator)
    if already is not None and already.id == target.id and not target.is_minimized:
        return True, f"{target.title!r} is already the frontmost document window"

    point = click_point(target)
    if point is not None:
        try:
            (activator or activate_app)()
            sleep(0.6)
            (clicker or real_click)(*point)
        except DesktopError as exc:
            return False, f"could not click {target.title!r} to raise it: {exc}"
        how = f"activate + HID click at {point} (from live bounds)"
    elif file_path is not None:
        path = Path(file_path)
        if not path.exists():
            return False, f"file_path does not exist: {path}"
        try:
            (activator or activate_app)()
            sleep(0.6)
            (opener or open_with_tableau)(path)
        except DesktopError as exc:
            return False, f"could not re-open {path.name} to raise its window: {exc}"
        how = f"activate + open -a {path.name}"
    else:
        return False, (
            f"{target.title!r} offers no on-screen tile to click (bounds "
            f"{target.width:.0f}x{target.height:.0f} at {target.x:.0f},{target.y:.0f}) and no "
            f"file_path was given. Pass file_path=<path to the .twbx> so it can be re-opened."
        )

    attempts = max(1, int(timeout / poll))
    for _ in range(attempts):
        sleep(poll)
        now = frontmost_document(enumerator=enumerator)
        if now is not None and normalise_stem(now.workbook_stem or "") == normalise_stem(
            target.workbook_stem or ""
        ):
            return True, f"raised {now.title!r} via {how}"
    now = frontmost_document(enumerator=enumerator)
    return False, (
        f"tried to raise {target.title!r} via {how}, but the frontmost document is still "
        f"{(now.title if now else None)!r} after {timeout:.0f}s"
    )


# --- save-prompt detection -------------------------------------------------


def looks_like_save_prompt(window: WindowInfo) -> bool:
    lowered = window.title.lower()
    return any(hint in lowered for hint in SAVE_PROMPT_TITLE_HINTS)


def detect_save_prompt(*, enumerator: Enumerator | None = None) -> WindowInfo | None:
    """A visible window that looks like a "save changes?" question, if any.

    Husks are skipped. Dialogs leave them behind exactly as documents do — the
    sign-in window leaves a ~59x112 one, which is what once made publishing
    believe sign-in was permanently required. A stale save prompt would be worse
    here: it would block EVERY close from then on with "Tableau is already
    showing a save prompt", and make every successful close report BAILED OUT.
    """
    for w in classify_windows(enumerator=enumerator):
        if not w.is_document and not w.is_stale and looks_like_save_prompt(w):
            return w
    return None


# --- closing ---------------------------------------------------------------


def close_document(
    stem: str,
    *,
    save: bool = False,
    file_path: Path | None = None,
    enumerator: Enumerator | None = None,
    clicker: Clicker | None = None,
    key_sender: KeySender | None = None,
    activator: Activator | None = None,
    opener: Opener | None = None,
    raiser: Raiser | None = None,
    sleeper: Sleeper | None = None,
    app_checker: Callable[[], bool] | None = None,
    app_namer: Callable[[], str | None] | None = None,
    settle: float = 1.5,
    close_timeout: float = 25.0,
    resend_on_timeout: bool = True,
) -> tuple[bool, str]:
    """Close exactly one workbook window. Returns ``(closed, message)``.

    ``settle`` is the interval between checks and ``close_timeout`` the total time
    the window is given to disappear before the close is called a failure.

    Guarantees, in the order they are enforced:

    * **Refuses when the target is not open.** No target, no action.
    * **Refuses without positive identification.** The window's title stem must
      match ``stem`` *exactly* (after case/underscore normalisation). A substring
      match is not enough: closing ``Full_Feature_Check_v2`` when asked for
      ``Full_Feature_Check`` would be indistinguishable from working correctly.
    * **Refuses while any save prompt is already showing**, because the close
      keystroke would be delivered to that dialog instead.
    * **Requires the target to be frontmost.** Command-W closes whatever document
      is active, so the window is raised and re-verified first; if it cannot be
      made frontmost, nothing is sent.
    * **Never answers a "save changes?" prompt.** If one appears, the function
      bails out and reports it, leaving the dialog on screen for a human. This is
      the deliberate design decision: "Don't Save" destroys work irreversibly and
      "Save" can overwrite a file the user did not intend to modify, and this code
      cannot tell which workbook's unsaved state is precious. Guessing wrong is
      unacceptable, so it does not guess. ``save=True`` is therefore rejected
      outright rather than silently ignored — saving on the user's behalf is out
      of scope for this module.
    * **Never claims success it cannot prove.** Success requires the target window
      to be absent from a fresh enumeration afterwards.
    """
    if save:
        return False, (
            "close_document(save=True) is not supported: this module never saves or discards "
            "a workbook on the user's behalf. Save it in Tableau first, then close with "
            "save=False."
        )

    sleep = sleeper or time.sleep
    needle = normalise_stem(stem)
    if not needle:
        return False, "refusing to close: an empty workbook name matches nothing"

    docs = document_windows(enumerator=enumerator)
    exact = [d for d in docs if normalise_stem(d.workbook_stem or "") == needle]
    if not exact:
        near = [d.workbook_stem for d in docs if needle in normalise_stem(d.workbook_stem or "")]
        if near:
            return False, (
                f"refusing to close: no window is titled exactly "
                f"{DOC_TITLE_PREFIX}{stem!r}. Closest open windows are {near}. Pass the exact "
                f"stem — a partial match could close the wrong workbook."
            )
        stale = [
            d
            for d in document_windows(enumerator=enumerator, include_stale=True)
            if d.is_stale and normalise_stem(d.workbook_stem or "") == needle
        ]
        if stale:
            return False, (
                f"{stem!r} is not open: the window server still lists a destroyed window "
                f"with that title, but the document itself is already closed. Nothing to do."
            )
        return False, (
            f"no Tableau document window matching {stem!r}. "
            f"Currently open: {[d.workbook_stem for d in docs] or 'none'}"
        )
    target = max(exact, key=lambda d: (d.area, -d.id))

    prompt = detect_save_prompt(enumerator=enumerator)
    if prompt is not None:
        return False, (
            f"refusing to act: Tableau is already showing {prompt.title!r}, and the close "
            f"command would be delivered to that dialog. Answer it in Tableau, then re-run."
        )

    raise_fn = raiser or (
        lambda s: unminimize_and_raise(
            s,
            file_path=file_path,
            enumerator=enumerator,
            clicker=clicker,
            activator=activator,
            opener=opener,
            sleeper=sleeper,
        )
    )
    raised, why = raise_fn(target.workbook_stem or stem)
    if not raised:
        return False, f"refusing to close {target.title!r}: could not make it frontmost ({why})"

    front = frontmost_document(enumerator=enumerator)
    if front is None or normalise_stem(front.workbook_stem or "") != needle:
        return False, (
            f"SAFETY ABORT: frontmost document is {(front.title if front else None)!r}, not "
            f"{target.title!r}. Command-W would close the wrong workbook."
        )

    # Command-W goes to the ACTIVE APPLICATION, not to a window we name. Every
    # check above only ranks Tableau's own windows, so all of them pass happily
    # while the user is in a browser — and the keystroke closes their tab.
    is_active = app_checker or tableau_is_active
    if not is_active():
        (activator or activate_app)()
        sleep(0.6)
        if not is_active():
            return False, (
                f"refusing to close {target.title!r}: Tableau could not be made the active "
                f"application (frontmost app is {(app_namer or frontmost_app_name)()!r}). "
                f"Command-W is "
                f"delivered to whatever app has keyboard focus, so it would close a window "
                f"there instead."
            )

    before = {w.id for w in classify_windows(enumerator=enumerator)}
    try:
        (key_sender or post_command_key)("w")
    except DesktopError as exc:
        return False, f"could not send Command-W to {target.title!r}: {exc}"
    # Poll rather than sample once. A single check after a fixed pause reported a
    # closed workbook as still open whenever Tableau was slow, which it reliably is
    # once a dozen documents are loaded.
    waited = 0.0
    while True:
        sleep(settle)
        waited += settle
        after = classify_windows(enumerator=enumerator)
        snapshot = [w.to_dict() for w in after]
        prompt = detect_save_prompt(enumerator=lambda rows=snapshot: rows)
        if prompt is not None:
            return False, (
                f"BAILED OUT: Tableau is asking {prompt.title!r} about {target.workbook_stem!r}. "
                f"This server will not answer a save prompt — 'Don't Save' would destroy unsaved "
                f"work. The prompt is still on screen; answer it in Tableau."
            )
        # Only live windows count. The husk this close just created carries the same
        # title and never goes away, so counting it would fail every successful close.
        still_open = [
            w
            for w in after
            if w.is_document
            and not w.is_stale
            and normalise_stem(w.workbook_stem or "") == needle
        ]
        if not still_open:
            return True, f"closed {target.title!r}"
        if waited >= close_timeout:
            break

    new_dialogs = [w.title for w in after if not w.is_document and w.id not in before]
    if new_dialogs:
        return False, (
            f"BAILED OUT: {target.title!r} is still open and Tableau raised {new_dialogs}. "
            f"That is very likely an unsaved-changes prompt; this server will not answer it. "
            f"Resolve the dialog in Tableau, then re-run."
        )
    # Tableau drops the occasional keystroke when it is busy -- with a dozen
    # documents loaded, one workbook per run reliably survived the first
    # Command-W while its window sat restored and frontmost, no save prompt and no
    # dialog. Resending once is safe: every guard above still holds, the save
    # prompt is re-checked each poll, and the window is re-identified by title.
    if resend_on_timeout:
        return close_document(
            stem,
            file_path=file_path,
            enumerator=enumerator,
            clicker=clicker,
            key_sender=key_sender,
            activator=activator,
            opener=opener,
            raiser=raiser,
            sleeper=sleeper,
            app_checker=app_checker,
            app_namer=app_namer,
            settle=settle,
            close_timeout=close_timeout,
            resend_on_timeout=False,
        )

    return False, (
        f"Command-W was sent twice but {target.title!r} was still open {waited:.0f}s after "
        f"the second attempt. Nothing was forced. Close it in Tableau, or check that "
        f"Tableau has Accessibility permission."
    )


def close_all_generated(
    prefixes: Sequence[str],
    *,
    dry_run: bool = True,
    known_paths: Mapping[str, Path] | None = None,
    enumerator: Enumerator | None = None,
    clicker: Clicker | None = None,
    key_sender: KeySender | None = None,
    activator: Activator | None = None,
    opener: Opener | None = None,
    raiser: Raiser | None = None,
    sleeper: Sleeper | None = None,
    app_checker: Callable[[], bool] | None = None,
    app_namer: Callable[[], str | None] | None = None,
) -> dict:
    """Close only the throwaway workbooks whose stem starts with a given prefix.

    Intended for test debris (``Probe``, ``Full_Feature_Check``, ``NoFilter_Probe``).
    A window is a candidate **only** if its normalised stem starts with a
    normalised prefix — never on a substring or fuzzy match — so a workbook the
    caller did not name can never be selected.

    ``dry_run`` defaults to True and reports what *would* be closed without
    sending a single event: nothing calls the clicker or the key sender on that
    path. Pass ``dry_run=False`` only after reading the ``would_close`` list.

    ``known_paths`` maps a workbook stem to the file it was opened from, and is
    forwarded to :func:`close_document` as ``file_path``. Supply it whenever the
    caller generated the workbooks itself. Without it, a workbook that Tableau has
    minimised off-screen cannot be closed at all: raising a window works by
    clicking its on-screen tile, and a minimised document offers none, so the only
    reliable way back is ``open -a`` on the original path. Every such workbook is
    otherwise reported in ``failed`` and left open, which degrades the app — Tableau
    stops accepting new documents after roughly eighteen of them.
    """
    cleaned = [p for p in prefixes if p and p.strip()]
    if not cleaned:
        raise ValueError("at least one non-empty prefix is required; refusing to match everything")
    normalised: list[str] = []
    for prefix in cleaned:
        norm = normalise_stem(prefix)
        if len(norm) < MIN_PREFIX_LEN:
            raise ValueError(
                f"prefix {prefix!r} is too short (minimum {MIN_PREFIX_LEN} characters after "
                f"normalisation); a short prefix risks matching a real workbook"
            )
        normalised.append(norm)

    docs = document_windows(enumerator=enumerator)
    matched: list[WindowInfo] = []
    skipped: list[dict] = []
    for doc in docs:
        stem_norm = normalise_stem(doc.workbook_stem or "")
        hit = next((p for p in normalised if stem_norm.startswith(p)), None)
        if hit is None:
            skipped.append({"stem": doc.workbook_stem, "reason": "no prefix matched"})
        else:
            matched.append(doc)

    # Husks of workbooks that were already closed. Reported so a caller cleaning up
    # after itself can see they were handled, rather than assuming they went missing.
    live_stems = {normalise_stem(w.workbook_stem or "") for w in docs}
    already_closed = sorted(
        {
            d.workbook_stem
            for d in document_windows(enumerator=enumerator, include_stale=True)
            if d.is_stale
            and d.workbook_stem
            and normalise_stem(d.workbook_stem) not in live_stems
            and any(normalise_stem(d.workbook_stem).startswith(p) for p in normalised)
        }
    )

    result: dict = {
        "dry_run": dry_run,
        "prefixes": list(cleaned),
        "would_close": [w.workbook_stem for w in matched],
        "matched": [w.to_dict() for w in matched],
        "skipped": skipped,
        "already_closed": already_closed,
        "closed": [],
        "failed": [],
        "notes": [],
    }
    if dry_run:
        result["notes"].append(
            f"dry run: {len(matched)} window(s) would be closed, "
            f"{len(skipped)} left untouched. No events were sent. "
            f"Re-run with dry_run=False to close them."
        )
        return result

    # Look the path up by normalised stem: the caller keys this map by the name it
    # built the file under, which need not match Tableau's window title byte for byte.
    paths = {normalise_stem(k): v for k, v in (known_paths or {}).items()}

    # De-duplicate by stem: one workbook can own several windows (a Dock tile and a
    # restored window), and each stem is closed once.
    seen: set[str] = set()
    for window in matched:
        stem = window.workbook_stem or ""
        key = normalise_stem(stem)
        if key in seen:
            continue
        seen.add(key)
        ok, message = close_document(
            stem,
            file_path=paths.get(key),
            enumerator=enumerator,
            clicker=clicker,
            key_sender=key_sender,
            activator=activator,
            opener=opener,
            raiser=raiser,
            sleeper=sleeper,
            app_checker=app_checker,
        )
        if ok:
            result["closed"].append({"stem": stem, "message": message})
            continue
        # Judge by OUTCOME, not by the return value. close_document refuses when a
        # stem resolves only to a husk ("already closed, nothing to do") -- which
        # is the goal state, not a failure, and reporting it under COULD NOT CLOSE
        # sends someone hunting for a window that does not exist. Anything with no
        # live window left is done, however it got there.
        if not any(
            normalise_stem(d.workbook_stem or "") == key
            for d in document_windows(enumerator=enumerator)
        ):
            result["already_closed"].append(stem)
            continue
        result["failed"].append({"stem": stem, "reason": message})
    result["notes"].append(
        f"closed {len(result['closed'])} of {len(seen)} matched workbook(s); "
        f"{len(result['failed'])} refused or bailed out."
    )
    unmapped = [e["stem"] for e in result["failed"] if normalise_stem(e["stem"]) not in paths]
    if unmapped:
        result["notes"].append(
            f"no file path was supplied for {unmapped}, so a minimised window could not be "
            f"restored with `open -a`. Pass known_paths={{stem: path}} if you know where "
            f"these came from."
        )
    return result
