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


def list_windows() -> list[dict]:
    """Enumerate Tableau windows via the window server (CoreGraphics).

    Accessibility is NOT usable for this: Tableau Public 2026.2.0 intermittently
    reports ``count of windows = 0`` to System Events even with a document window
    visibly open (verified). CGWindowListCopyWindowInfo with
    ``kCGWindowListOptionAll`` reports titles reliably, including windows that are
    occluded or not marked on-screen.
    """
    try:
        import Quartz
    except ImportError:  # pragma: no cover - environment guard
        return []
    if not is_running():
        return []
    info = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionAll | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID,
    )
    out: list[dict] = []
    for w in info or []:
        if "Tableau" not in (w.get("kCGWindowOwnerName") or ""):
            continue
        bounds = w.get("kCGWindowBounds") or {}
        out.append(
            {
                "id": int(w.get("kCGWindowNumber", 0)),
                "title": w.get("kCGWindowName") or "",
                "width": int(bounds.get("Width", 0)),
                "height": int(bounds.get("Height", 0)),
                "area": int(bounds.get("Width", 0)) * int(bounds.get("Height", 0)),
            }
        )
    return out


def window_names() -> list[str]:
    return [w["title"] for w in list_windows() if w["title"]]


def find_window(title_contains: str, *, min_area: int = 200_000) -> dict | None:
    """Largest Tableau window whose title contains ``title_contains``.

    ``min_area`` filters out transient progress dialogs such as
    "Opening workbook 'x.twbx'..." which share the workbook name.
    """
    needle = title_contains.lower()
    hits = [w for w in list_windows() if needle in w["title"].lower() and w["area"] >= min_area]
    return max(hits, key=lambda w: w["area"]) if hits else None


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
    return AppStatus(
        installed=True,
        app_path=app,
        version=app_version(app),
        bundle_id=app_bundle_id(app),
        running=is_running(),
        windows=window_names(),
        accessibility_ok=acc,
        notes=[]
        if acc
        else [
            "Accessibility permission is not granted to the controlling process. "
            "Grant it in System Settings > Privacy & Security > Accessibility."
        ],
    )


def read_error_dialog(*, dismiss: bool = True) -> str | None:
    """Return the text of Tableau's error dialog if one is showing.

    Uses the dialog's named 'Copy Error Message' button and reads the pasteboard,
    which is far more reliable than walking the AX text hierarchy.
    """
    if not is_running():
        return None
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
    if found.lower() != "true":
        return None
    time.sleep(0.4)
    text = _run(["pbpaste"]).stdout.strip()
    if dismiss:
        dismiss_dialogs()
    return text or None


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
    not respond to System Events' ``click``/``AXPress`` on menu items — those go
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


def close_window(title_contains: str) -> bool:
    """Close only a window whose title matches. Never touches other windows."""
    if not is_running():
        return False
    safe = as_escape(title_contains)
    script = f"""
    tell application "System Events"
      tell process "{PROCESS_NAME}"
        set closed to false
        repeat with w in windows
          if (name of w) contains "{safe}" then
            try
              click (first button of w whose subrole is "AXCloseButton")
              set closed to true
            end try
          end if
        end repeat
        return (closed as text)
      end tell
    end tell
    """
    try:
        return osascript(script).lower() == "true"
    except DesktopError:
        return False
