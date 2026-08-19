"""Tableau Public desktop control via macOS Accessibility.

Tableau Public 2026.2.0 ships **no** AppleScript dictionary (verified: no .sdef,
no NSAppleScriptEnabled, no URL scheme), so all control goes through the
Accessibility API driven by System Events.

Design rules enforced here (MASTERPROMPT §4/§12):
  * the app is identified by bundle id, never by window position;
  * elements are addressed by role and accessible name, never by coordinates;
  * every wait has a timeout;
  * windows this module did not open are never closed or saved.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

BUNDLE_ID = "com.tableausoftware.tableaupublic"
APP_PATHS = (
    "/Applications/Tableau Public (Apple silicon).app",
    "/Applications/Tableau Public.app",
)
PROCESS_NAME = "Tableau Public"

# The error dialog Tableau shows for load/publish failures.
ERROR_DIALOG_TITLE = "Unable to complete action"
COPY_ERROR_BUTTON = "Copy Error Message"


class DesktopError(RuntimeError):
    """Raised when the desktop layer cannot complete an operation."""


@dataclass
class AppStatus:
    installed: bool
    app_path: str | None
    version: str | None
    bundle_id: str | None
    running: bool
    windows: list[str] = field(default_factory=list)
    accessibility_ok: bool = False
    notes: list[str] = field(default_factory=list)
    #: Husks of already-closed documents. Diagnostics only - never "open".
    stale_windows: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "installed": self.installed,
            "app_path": self.app_path,
            "version": self.version,
            "bundle_id": self.bundle_id,
            "running": self.running,
            "windows": self.windows,
            "accessibility_ok": self.accessibility_ok,
            "notes": self.notes,
            "stale_windows": self.stale_windows,
        }


def _run(args: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess:
    # Never shell=True (T4). Arguments are always passed as a list.
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)


def osascript(script: str, *, timeout: int = 30) -> str:
    """Run AppleScript passed on **stdin** (never interpolated into argv)."""
    proc = subprocess.run(
        ["osascript", "-"],
        input=script,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        raise DesktopError(f"osascript failed: {proc.stderr.strip()[:400]}")
    return proc.stdout.strip()


def as_escape(value: str) -> str:
    """Escape a Python string for embedding in an AppleScript string literal."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def find_app() -> str | None:
    for p in APP_PATHS:
        if Path(p).is_dir():
            return p
    return None


def app_version(app_path: str) -> str | None:
    proc = _run(
        [
            "/usr/libexec/PlistBuddy",
            "-c",
            "Print :CFBundleShortVersionString",
            f"{app_path}/Contents/Info.plist",
        ]
    )
    return proc.stdout.strip() or None


def app_bundle_id(app_path: str) -> str | None:
    proc = _run(
        [
            "/usr/libexec/PlistBuddy",
            "-c",
            "Print :CFBundleIdentifier",
            f"{app_path}/Contents/Info.plist",
        ]
    )
    return proc.stdout.strip() or None


def is_running() -> bool:
    return _run(["pgrep", "-x", PROCESS_NAME]).returncode == 0


def list_windows(*, include_stale: bool = False) -> list[dict]:
    """Enumerate Tableau's LIVE windows via the window server (CoreGraphics).

    Accessibility is NOT usable for this: Tableau Public 2026.2.0 intermittently
    reports ``count of windows = 0`` to System Events even with a document window
    visibly open (verified), so CGWindowListCopyWindowInfo is the only source that
    reports titles at all.

    WHICH CG LIST, AND WHY IT DECIDES WHAT THE USER IS TOLD
    ``kCGWindowListOptionOnScreenOnly`` is the list of windows that EXIST.
    ``kCGWindowListOptionAll`` additionally returns DESTROYED windows the window
    server has not yet reaped - every workbook Tableau has ever opened leaves such
    a husk behind, always at exactly 218x161 at (-234, 367). This function used to
    query only the all-windows list and its docstring called that an advantage
    ("including windows that are occluded or not marked on-screen"). It is not an
    advantage, it is the bug: with a single real document open, Quartz reported 26
    of them (screenshot-verified), and since :func:`window_names` feeds
    :func:`status`, the ``get_tableau_public_app_status`` tool reported 26 closed
    workbooks as open. Nothing legitimate is lost by ignoring husks, because a
    MINIMIZED document keeps a Dock tile and that tile IS on-screen. See the STALE
    WINDOWS section at the top of ``window_control.py``, which states the same rule
    and is the reference implementation.

    Husks are still enumerated and flagged ``is_stale``; they are simply not part
    of the default answer. Pass ``include_stale=True`` for diagnostics - never to
    decide whether a workbook is open, which window to screenshot, or what to
    close: a husk outranks a live Dock tile on area and never disappears.
    """
    try:
        import Quartz
    except ImportError:  # pragma: no cover - environment guard
        return []
    if not is_running():
        return []

    def _query(option: int) -> list:
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
        bounds = w.get("kCGWindowBounds") or {}
        width = int(bounds.get("Width", 0))
        height = int(bounds.get("Height", 0))
        return {
            "id": int(w.get("kCGWindowNumber", 0)),
            "title": w.get("kCGWindowName") or "",
            "width": width,
            "height": height,
            "area": width * height,
            "on_screen": on_screen,
            "is_stale": not on_screen,
        }

    out: list[dict] = []
    seen: set[int] = set()
    # On-screen first, in the window server's front-to-back order, so callers may
    # treat the first entry as the frontmost.
    for w in _query(Quartz.kCGWindowListOptionOnScreenOnly):
        row = _row(w, on_screen=True)
        if row and row["id"] not in seen:
            seen.add(row["id"])
            out.append(row)
    for w in _query(Quartz.kCGWindowListOptionAll):
        row = _row(w, on_screen=False)
        if row and row["id"] not in seen:
            seen.add(row["id"])
            if include_stale:
                out.append(row)
    return out


def window_names() -> list[str]:
    """Titles of the windows that actually exist. Husks are excluded by design."""
    return [w["title"] for w in list_windows() if w["title"]]


def stale_window_names() -> list[str]:
    """Titles of husks: windows Tableau destroyed that the server has not reaped.

    Diagnostics only. Reported by :func:`status` so a user who sees a workbook
    "missing" from ``windows`` can tell the difference between "never opened" and
    "already closed", which is the one genuinely useful thing the all-windows list
    contributes.
    """
    return [w["title"] for w in list_windows(include_stale=True) if w["is_stale"] and w["title"]]


def find_window(stem: str, *, min_area: int = 200_000) -> dict | None:
    """The live Tableau window for exactly the workbook ``stem``, or None.

    MATCHING IS EXACT, NOT SUBSTRING, and that is the whole point. The previous
    version matched any title CONTAINING the needle, which manufactured green
    validations out of failures: with ``Probe_Alpha`` open, validating
    ``Probe.twbx`` that Tableau refused to load made ``find_window("Probe")``
    return ``Tableau Public - Probe_Alpha``; :func:`open_workbook` then reported
    ``opened=True`` and the screenshot "proving" Probe.twbx renders was in fact a
    picture of Probe_Alpha's window. There is deliberately no substring fallback,
    because any such fallback can reproduce exactly that false positive.

    Comparison goes through :func:`window_control.normalise_stem`, the single
    canonical form used everywhere for workbook names: it tolerates a bare stem, a
    file name (``X.twbx``) and a full window title (``Tableau Public - X``), and
    treats ``_`` as a space. A bare exact title is accepted as well as the
    prefixed document title - neither can name a different workbook.

    ``min_area`` is retained: it keeps the wait loop in :func:`open_workbook` from
    latching onto a transient progress dialog such as "Opening workbook
    'x.twbx'..." that carries the workbook name but is not a document surface.
    """
    # Imported inside the function on purpose: window_control imports real_click
    # (defined near the bottom of this module) at import time, so a module-level
    # import here would be a circular import that fails whenever tableau_app is
    # imported first.
    from .window_control import normalise_stem

    needle = normalise_stem(stem)
    if not needle:
        return None
    hits = [
        w for w in list_windows() if normalise_stem(w["title"]) == needle and w["area"] >= min_area
    ]
    # Duplicates are one restored window plus its Dock tiles; the biggest is the
    # one worth screenshotting. Ties break on the lowest id for determinism.
    return max(hits, key=lambda w: (w["area"], -w["id"])) if hits else None


def check_accessibility() -> bool:
    try:
        osascript('tell application "System Events" to return name of first process')
        return True
    except DesktopError:
        return False


def status() -> AppStatus:
    app = find_app()
    if not app:
        return AppStatus(
            installed=False,
            app_path=None,
            version=None,
            bundle_id=None,
            running=False,
            notes=[f"Tableau Public not found at any of: {', '.join(APP_PATHS)}"],
        )
    acc = check_accessibility()
    # `windows` must list only windows that EXIST: this is what tells a user (and a
    # model) which workbooks are open, and it used to include every husk Tableau had
    # left behind, i.e. every workbook ever opened. See list_windows.
    stale = stale_window_names()
    notes: list[str] = []
    if not acc:
        notes.append(
            "Accessibility permission is not granted to the controlling process. "
            "Grant it in System Settings > Privacy & Security > Accessibility."
        )
    if stale:
        notes.append(
            f"{len(stale)} window(s) reported by the window server belong to documents "
            f"Tableau has already CLOSED (husks it has not yet reaped). They are listed "
            f"under 'stale_windows' and are not open workbooks."
        )
    return AppStatus(
        installed=True,
        app_path=app,
        version=app_version(app),
        bundle_id=app_bundle_id(app),
        running=is_running(),
        windows=window_names(),
        accessibility_ok=acc,
        notes=notes,
        stale_windows=stale,
    )


def _pbpaste() -> str:
    """Raw text contents of the pasteboard ('' when empty or when it holds non-text)."""
    return _run(["pbpaste"], timeout=10).stdout


def _pbcopy(text: str) -> None:
    """Put ``text`` back on the pasteboard. Best effort: never raises.

    Reading an error message costs the user their clipboard, because the only
    reliable way to get the text out of Tableau is to make Tableau copy it. Taking
    a snapshot first and restoring it here keeps that cost at zero.
    """
    try:
        subprocess.run(["pbcopy"], input=text, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - defensive
        pass


# How long to give Tableau to actually populate the pasteboard after the click.
# Counted in attempts rather than wall-clock so the loop terminates promptly when
# the click was a no-op (the common case this function now has to survive).
COPY_POLL_ATTEMPTS = 8
COPY_POLL_INTERVAL = 0.15

#: Returned when a dialog is provably showing but its text could not be obtained.
#: NEVER None: None means "no error", and saying that about a dialog we just
#: dismissed loses the error permanently.
DIALOG_TEXT_UNREADABLE = (
    "Tableau is showing an error dialog, but its message could not be read: the "
    "'Copy Error Message' button put nothing new on the pasteboard (System Events "
    "clicks are silently ignored by Qt) and the dialog exposed no readable text. "
    "Treat this as a failure and read the dialog in Tableau Public."
)


def _dialog_text() -> str | None:
    """Best-effort AX read of the error dialog's own static text.

    Fallback for when the pasteboard did not change. Reading is much likelier to
    work than clicking: it is AX *actions* that Qt drops (see :func:`real_click`),
    while AX *queries* are what :func:`element_center` already depends on. Scoped
    to the window or sheet that actually owns a 'Copy Error Message' button, so it
    cannot return the document window's text as if it were an error.
    """
    script = f"""
    set collected to {{}}
    tell application "System Events"
      tell process "{PROCESS_NAME}"
        repeat with w in windows
          try
            if (count of (buttons of w whose name is "{COPY_ERROR_BUTTON}")) > 0 then
              repeat with t in (static texts of w)
                try
                  set end of collected to ((value of t) as text)
                end try
              end repeat
            end if
          end try
          try
            repeat with sh in sheets of w
              if (count of (buttons of sh whose name is "{COPY_ERROR_BUTTON}")) > 0 then
                repeat with t in (static texts of sh)
                  try
                    set end of collected to ((value of t) as text)
                  end try
                end repeat
              end if
            end repeat
          end try
        end repeat
      end tell
    end tell
    set AppleScript's text item delimiters to linefeed
    return collected as text
    """
    try:
        raw = osascript(script)
    except DesktopError:
        return None
    seen: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if line and line not in seen:
            seen.append(line)
    return "\n".join(seen) or None


def read_error_dialog(*, dismiss: bool = True) -> str | None:
    """Return the text of Tableau's error dialog, or None if none is showing.

    ``None`` means "Tableau is showing no error dialog" and every caller treats it
    as success, so both halves of this function exist to make sure that answer is
    never wrong in either direction.

    PROVENANCE - why the pasteboard is snapshotted first
    The text is obtained by clicking the dialog's named 'Copy Error Message'
    button and reading the pasteboard, which beats walking the AX text hierarchy.
    But that click is a System Events click, the exact call this codebase has
    measured as a silent no-op on Qt (see :func:`real_click`). The previous
    version set ``found`` purely from the EXISTENCE of the button and then
    returned whatever happened to be on the pasteboard, with nothing tying the two
    together: when the click no-opped, the USER'S unrelated clipboard came back as
    a "Tableau error", which aborted publishes that had already succeeded and
    leaked clipboard contents into an MCP tool response. Now the pasteboard is
    snapshotted before the click and only content that ACTUALLY CHANGED is
    attributed to Tableau; the snapshot is then put back so reading an error does
    not cost the user their clipboard.

    NEVER SWALLOWS A DIALOG - the mirror-image failure
    The previous version returned ``None`` when the pasteboard was empty, *after*
    ``dismiss`` had already pressed Escape: a real error was thrown away and its
    dialog closed, so it could not even be re-read. Once a dialog is confirmed,
    this function always returns a non-empty string - the copied text, else the
    dialog's own AX text, else :data:`DIALOG_TEXT_UNREADABLE`.
    """
    if not is_running():
        return None
    # Snapshot BEFORE the script runs: the script itself does the clicking.
    before = _pbpaste()
    script = f"""
    tell application "System Events"
      tell process "{PROCESS_NAME}"
        set found to false
        repeat with w in windows
          try
            repeat with b in (buttons of w whose name is "{COPY_ERROR_BUTTON}")
              click b
              set found to true
            end repeat
          end try
          try
            repeat with sh in sheets of w
              repeat with b in (buttons of sh whose name is "{COPY_ERROR_BUTTON}")
                click b
                set found to true
              end repeat
            end repeat
          end try
        end repeat
        return (found as text)
      end tell
    end tell
    """
    try:
        found = osascript(script)
    except DesktopError:
        return None
    if found.strip().lower() != "true":
        return None

    # A dialog IS showing from here on, so every exit below returns a string.
    after = before
    for _ in range(COPY_POLL_ATTEMPTS):
        time.sleep(COPY_POLL_INTERVAL)
        after = _pbpaste()
        if after != before:
            break

    text = ""
    if after != before:
        text = after.strip()
        # Only restore something we can represent. pbpaste returns '' for image or
        # other non-text clipboards, and writing that back would replace whatever
        # is there now with an empty string rather than recovering anything.
        if before.strip():
            _pbcopy(before)
    # Unchanged pasteboard means the click did nothing (or, harmlessly, that the
    # error text was already on the clipboard from a previous run) - either way it
    # is not evidence, so it is not reported as Tableau's message.
    if not text:
        text = _dialog_text() or DIALOG_TEXT_UNREADABLE
    if dismiss:
        dismiss_dialogs()
    return text


def dismiss_dialogs() -> None:
    """Press Escape to close a modal, scoped strictly to the Tableau process."""
    if not is_running():
        return
    try:
        osascript(
            f'tell application "System Events" to tell process "{PROCESS_NAME}" to key code 53'
        )
    except DesktopError:
        pass


def open_workbook(path: Path, *, timeout: float = 90.0, poll: float = 1.0) -> dict:
    """Open a workbook and wait for its window, or return the load error.

    Returns a dict with ``opened``, ``window``, ``error`` and ``elapsed_s``.
    """
    app = find_app()
    if not app:
        raise DesktopError("Tableau Public is not installed")
    if not path.exists():
        raise DesktopError(f"workbook does not exist: {path}")

    stem = path.stem

    proc = _run(["open", "-a", app, str(path)])
    if proc.returncode != 0:
        raise DesktopError(f"'open' failed: {proc.stderr.strip()[:300]}")

    start = time.monotonic()
    while time.monotonic() - start < timeout:
        time.sleep(poll)
        win = find_window(stem)
        if win:
            return {
                "opened": True,
                "window": win["title"],
                "window_id": win["id"],
                "error": None,
                "elapsed_s": round(time.monotonic() - start, 1),
            }
        err = read_error_dialog(dismiss=False)
        if err:
            dismiss_dialogs()
            return {
                "opened": False,
                "window": None,
                "window_id": None,
                "error": err,
                "elapsed_s": round(time.monotonic() - start, 1),
            }

    return {
        "opened": False,
        "window": None,
        "window_id": None,
        "error": f"timed out after {timeout}s waiting for a window matching {stem!r}",
        "elapsed_s": round(time.monotonic() - start, 1),
    }


def real_click(x: float, y: float, *, settle: float = 0.15) -> None:
    """Post a genuine HID-level mouse click via CGEvent.

    THIS IS REQUIRED FOR TABLEAU. Tableau Public is a Qt application, and Qt does
    not respond to System Events' ``click``/``AXPress`` on menu items - those go
    through the Accessibility layer and are silently ignored, reporting success
    while doing nothing. Only real CGEvent HID events activate its menus.

    Verified: ``click``, ``AXPress`` and AX keyboard navigation all no-op'd on
    ``File > Save to Tableau Public As...``; a CGEvent click opened it first try.
    """
    import Quartz

    pt = Quartz.CGPointMake(float(x), float(y))
    Quartz.CGEventPost(
        Quartz.kCGHIDEventTap,
        Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, pt, 0),
    )
    time.sleep(settle)
    Quartz.CGEventPost(
        Quartz.kCGHIDEventTap,
        Quartz.CGEventCreateMouseEvent(
            None, Quartz.kCGEventLeftMouseDown, pt, Quartz.kCGMouseButtonLeft
        ),
    )
    time.sleep(0.09)
    Quartz.CGEventPost(
        Quartz.kCGHIDEventTap,
        Quartz.CGEventCreateMouseEvent(
            None, Quartz.kCGEventLeftMouseUp, pt, Quartz.kCGMouseButtonLeft
        ),
    )


"""Virtual key codes used for menu shortcuts (Carbon kVK_* values)."""
VK_ANSI_S = 1


def real_key(keycode: int, *, command: bool = False, shift: bool = False) -> None:
    """Post a genuine HID key event with modifiers.

    Same reasoning as :func:`real_click`: Tableau is Qt and ignores Accessibility
    input. A keyboard shortcut is markedly more robust than clicking a menu item,
    because it needs no geometry, no menu to stay open, and no mouse tracking.
    """
    import Quartz

    flags = 0
    if command:
        flags |= Quartz.kCGEventFlagMaskCommand
    if shift:
        flags |= Quartz.kCGEventFlagMaskShift

    source = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
    down = Quartz.CGEventCreateKeyboardEvent(source, keycode, True)
    up = Quartz.CGEventCreateKeyboardEvent(source, keycode, False)
    Quartz.CGEventSetFlags(down, flags)
    Quartz.CGEventSetFlags(up, flags)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
    time.sleep(0.08)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)


def element_center(applescript_selector: str) -> tuple[int, int] | None:
    """Centre point of an AX element. AX exposes menu *geometry* reliably even
    though it hides Tableau's windows, so geometry + CGEvent is the working combo.
    """
    script = f"""
    tell application "System Events" to tell process "{PROCESS_NAME}"
      set el to {applescript_selector}
      set p to position of el
      set s to size of el
      return ((item 1 of p) as text) & "," & ((item 2 of p) as text) & "," & ¬
             ((item 1 of s) as text) & "," & ((item 2 of s) as text)
    end tell
    """
    try:
        x, y, w, h = (int(v) for v in osascript(script).split(","))
    except (DesktopError, ValueError):
        return None
    return x + w // 2, y + h // 2


def screenshot_window(window_id: int, out_path: Path) -> Path:
    """Capture a single window by its CoreGraphics id (needs Screen Recording)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    proc = _run(["screencapture", "-x", "-o", "-l", str(window_id), str(out_path)], timeout=30)
    if proc.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
        raise DesktopError(
            f"window screenshot failed (id={window_id}): {proc.stderr.strip()[:200]}"
        )
    return out_path


def screenshot(out_path: Path, *, window_title_contains: str | None = None) -> Path:
    """Capture a screenshot. Captures the whole screen; window-scoped capture
    requires Screen Recording permission and a window id."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if window_title_contains:
        try:
            osascript(
                f'tell application "System Events" to tell process "{PROCESS_NAME}" '
                f"to set frontmost to true"
            )
            time.sleep(0.8)
        except DesktopError:
            pass
    proc = _run(["screencapture", "-x", "-o", str(out_path)], timeout=30)
    if proc.returncode != 0 or not out_path.exists():
        raise DesktopError(f"screencapture failed: {proc.stderr.strip()[:200]}")
    return out_path


# close_window() was DELETED here, not repaired. It clicked a window's
# AXCloseButton through System Events and returned True whenever an AXCloseButton
# was found and the click did not throw - the "reports success and does nothing"
# pattern, since Qt silently ignores System Events clicks (see real_click), so the
# usual outcome was True with the window still open. It also selected its target by
# substring, so `close_window("Probe")` could close Probe_Alpha and destroy unsaved
# work. It had no callers.
#
# Making it prove the window is gone would mean rebuilding what
# ``window_control.close_document`` already does and has been validated doing:
# exact-stem identification, refusing to act while a save prompt is showing,
# raising the target and re-checking it is frontmost, confirming Tableau owns
# keyboard focus, sending a REAL HID Command-W, and reporting success only when
# the window is absent from a fresh enumeration (ignoring the husk the close
# itself creates). A second, weaker close path next to it is a trap, not a
# feature. Use window_control.close_document().
