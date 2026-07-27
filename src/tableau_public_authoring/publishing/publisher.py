"""Publish to Tableau Public through the visible desktop workflow.

Tableau Public exposes **no** supported publishing API (the REST API covers
Server/Cloud only), so the only sanctioned path is the documented menu command:

    Server > Tableau Public > Save to Tableau Public...

This module drives exactly that. It never reads, types, or stores a credential:
if Tableau presents a sign-in surface, the run pauses and hands off to the user.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from ..desktop.tableau_app import (
    PROCESS_NAME,
    VK_ANSI_S,
    DesktopError,
    as_escape,
    osascript,
    read_error_dialog,
    real_click,
    real_key,
    screenshot_window,
)

FILE_MENU = "File"
SERVER_MENU = "Server"
TABLEAU_PUBLIC_ITEM = "Tableau Public"
SAVE_ITEM_PREFIXES = ("Save to Tableau Public",)
SIGN_IN_HINTS = ("sign in", "sign-in", "tableau public sign in", "log in")


@dataclass
class PublishResult:
    published: bool
    requires_sign_in: bool
    workbook_name: str
    public_url: str | None = None
    url_verified: bool = False
    http_status: int | None = None
    error: str | None = None
    screenshots: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "published": self.published,
            "requires_sign_in": self.requires_sign_in,
            "workbook_name": self.workbook_name,
            "public_url": self.public_url,
            "url_verified": self.url_verified,
            "http_status": self.http_status,
            "error": self.error,
            "screenshots": self.screenshots,
            "steps": self.steps,
        }


def server_menu_items() -> list[str]:
    """Enumerate the Server menu, which only populates with a workbook open."""
    script = f"""
    tell application "System Events"
      tell process "{PROCESS_NAME}"
        set out to ""
        repeat with mi in menu items of menu 1 of menu bar item "{SERVER_MENU}" of menu bar 1
          set n to name of mi
          if n is missing value then set n to "(separator)"
          set out to out & n & "\n"
          try
            repeat with sub in menu items of menu 1 of mi
              set sn to name of sub
              if sn is missing value then set sn to "(separator)"
              set out to out & "  > " & sn & "\n"
            end repeat
          end try
        end repeat
        return out
      end tell
    end tell
    """
    try:
        return [ln for ln in osascript(script).split("\n") if ln.strip()]
    except DesktopError:
        return []


# A real sign-in window measured 500x648. Tableau leaves a shrunken ~59x112 husk
# of it in the window server after it closes, which is why size and on-screen
# presence are both required — matching on title alone reported "sign-in needed"
# forever after the first authentication.
MIN_SIGN_IN_AREA = 40_000

# How long a sign-in window may sit on screen before we treat it as genuinely
# waiting for the user. An already-authenticated session flashes one briefly.
SIGN_IN_PATIENCE = 25.0


def detect_sign_in_required() -> bool:
    """True only if a sign-in window is genuinely on screen at a usable size."""
    try:
        import Quartz
    except ImportError:  # pragma: no cover
        return False
    info = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID,
    )
    for w in info or []:
        if "Tableau" not in (w.get("kCGWindowOwnerName") or ""):
            continue
        title = (w.get("kCGWindowName") or "").lower()
        if not any(h in title for h in SIGN_IN_HINTS):
            continue
        b = w.get("kCGWindowBounds") or {}
        if int(b.get("Width", 0)) * int(b.get("Height", 0)) >= MIN_SIGN_IN_AREA:
            return True
    return False


DOC_TITLE_PREFIX = "Tableau Public - "


def document_windows() -> list[dict]:
    """Tableau *document* windows only, in front-to-back on-screen order.

    Notes learned the hard way on Tableau Public 2026.2.0:
      * Accessibility reports ``count of windows = 0``, so AX cannot be used.
      * The **Window menu lists worksheets, not documents**, so its checked item
        identifies the active *sheet*, never the active workbook.
    The window server's on-screen ordering is the only reliable source.
    """
    try:
        import Quartz
    except ImportError:  # pragma: no cover
        return []
    info = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID,
    )
    out: list[dict] = []
    for w in info or []:
        if "Tableau" not in (w.get("kCGWindowOwnerName") or ""):
            continue
        title = w.get("kCGWindowName") or ""
        if not title.startswith(DOC_TITLE_PREFIX):
            continue
        b = w.get("kCGWindowBounds") or {}
        out.append(
            {
                "id": int(w.get("kCGWindowNumber", 0)),
                "title": title,
                "x": float(b.get("X", 0)),
                "y": float(b.get("Y", 0)),
                "width": float(b.get("Width", 0)),
                "height": float(b.get("Height", 0)),
            }
        )
    return out


def frontmost_window_title() -> str | None:
    """Title of Tableau's frontmost *document* window."""
    docs = document_windows()
    return docs[0]["title"] if docs else None


def raise_document_window(title_contains: str) -> tuple[bool, str]:
    """Bring a specific document window to the front.

    Calibrated-coordinate fallback (documented brittle, MASTERPROMPT §4): the
    click point is computed from the window's *live* bounds reported by the
    window server, never from a hardcoded screen position. This is required
    because Tableau exposes no AX window objects to raise by name.
    """
    needle = title_contains.lower().replace("_", " ")
    target = next(
        (d for d in document_windows() if needle in d["title"].lower().replace("_", " ")),
        None,
    )
    if target is None:
        titles = [d["title"] for d in document_windows()]
        return False, f"no document window matching {title_contains!r}. Open: {titles}"

    # A small window is still a valid active document: menu commands apply to the
    # active document regardless of its size. Only a zero-size window is unusable.
    if target["width"] < 10 or target["height"] < 10:
        return False, f"window {target['title']!r} has unusable bounds"

    click_x = int(target["x"] + target["width"] / 2)
    click_y = int(target["y"] + 12)  # title bar
    try:
        osascript(
            f'tell application "{PROCESS_NAME}" to activate\n'
            f"delay 0.5\n"
            f'tell application "System Events" to click at {{{click_x}, {click_y}}}'
        )
    except DesktopError as exc:
        return False, f"could not raise window: {exc}"
    time.sleep(1.2)
    now = frontmost_window_title()
    if now and needle in now.lower().replace("_", " "):
        return True, f"raised {now!r}"
    return False, f"raise attempted but frontmost is still {now!r}"


def assert_target_frontmost(expected_substring: str) -> tuple[bool, str]:
    """Refuse to act unless the intended workbook is the active document.

    Without this guard a menu click is dispatched to whatever window happens to
    be frontmost — which could be one of the user's own workbooks. Publishing is
    irreversible, so this is a hard precondition, not a warning.
    """
    title = frontmost_window_title()
    if title is None:
        return False, "could not determine Tableau's frontmost window; refusing to publish"
    if expected_substring.lower().replace("_", " ") not in title.lower().replace("_", " "):
        return False, (
            f"SAFETY ABORT: frontmost Tableau window is {title!r}, which does not match the "
            f"intended target {expected_substring!r}. Refusing to invoke publish, because the "
            f"menu command would apply to the wrong workbook."
        )
    return True, f"frontmost window confirmed as {title!r}"


def _focus_workbook(window_title_contains: str, *, file_path: Path | None = None) -> bool:
    """Make the target workbook the active document.

    Earlier this clicked a Window-menu item matching the title. That was actively
    harmful: Tableau's **Window menu lists worksheets, not documents**, so the
    match never succeeded, and merely opening the menu changed which document was
    frontmost — causing the publish precondition to abort against the wrong
    workbook. It now delegates to the window-control module, which uses window
    server bounds and CGEvent, and is a no-op when the target is already active.
    """
    needle = window_title_contains.lower().replace("_", " ")
    current = frontmost_window_title() or ""
    if needle in current.lower().replace("_", " "):
        return True

    try:
        from ..desktop.window_control import unminimize_and_raise

        ok, _why = unminimize_and_raise(window_title_contains, file_path=file_path)
        if ok:
            return True
    except (ImportError, TypeError):
        pass

    # Last resort: activate the app and re-check. Never opens a menu.
    try:
        osascript(f'tell application "{PROCESS_NAME}" to activate')
    except DesktopError:
        return False
    time.sleep(1.0)
    now = frontmost_window_title() or ""
    return needle in now.lower().replace("_", " ")


def file_menu_items() -> list[str]:
    """Enumerate the File menu. Menus populate lazily, so it must be clicked open."""
    script = f"""
    tell application "System Events"
      tell process "{PROCESS_NAME}"
        click menu bar item "{FILE_MENU}" of menu bar 1
        delay 0.6
        set out to ""
        repeat with mi in menu items of menu 1 of menu bar item "{FILE_MENU}" of menu bar 1
          set n to name of mi
          if n is missing value then set n to "----"
          set out to out & n & "|" & (enabled of mi as text) & "\n"
        end repeat
        key code 53
        return out
      end tell
    end tell
    """
    try:
        return [ln for ln in osascript(script).split("\n") if ln.strip()]
    except DesktopError:
        return []


def open_menu_and_locate(target: str) -> tuple[int, int] | None:
    """Open the File menu and return the target item's centre, in ONE osascript call.

    This ordering is essential and was arrived at empirically:

    * ``click menu bar item`` via Accessibility DOES open the menu — menu *bar
      items* respond to AX even though menu *items* do not.
    * The item's ``position``/``size`` are only reported correctly **while that
      same script holds the menu open**. Opening the menu with a CGEvent click and
      then querying geometry from a separate osascript returns ``(0, 0)`` with a
      bogus size, which previously sent the click to (0, 982).
    * The menu is deliberately left OPEN on return so the caller can CGEvent-click
      the coordinates, because Qt ignores an AX click on the item itself.
    """
    script = f"""
    tell application "System Events" to tell process "{PROCESS_NAME}"
      click menu bar item "{FILE_MENU}" of menu bar 1
      delay 0.9
      set mi to (first menu item of menu 1 of menu bar item "{FILE_MENU}" of menu bar 1 ¬
                 whose name starts with "{target}")
      set p to position of mi
      set sz to size of mi
      return ((item 1 of p) as text) & "," & ((item 2 of p) as text) & "," & ¬
             ((item 1 of sz) as text) & "," & ((item 2 of sz) as text)
    end tell
    """
    try:
        x, y, w, h = (int(v) for v in osascript(script).split(","))
    except (DesktopError, ValueError):
        return None
    if w <= 0 or h <= 0 or (x == 0 and y == 0):
        return None
    return x + w // 2, y + h // 2


def close_open_menu() -> None:
    try:
        osascript(
            f'tell application "System Events" to tell process "{PROCESS_NAME}" to key code 53'
        )
    except DesktopError:
        pass


def invoke_save_to_public(*, use_save_as: bool = True) -> tuple[bool, str]:
    """Invoke Tableau's publish command.

    IMPORTANT: in the **Tableau Public** edition the command lives on the **File**
    menu, not the Server menu. Tableau's own documentation describes
    ``Server > Tableau Public > Save to Tableau Public``, which applies to Tableau
    Desktop Professional. Verified on Tableau Public 2026.2.0, where the File menu
    contains both ``Save to Tableau Public...`` and ``Save to Tableau Public As...``
    while the Server menu contains only ``Run Optimizer...``.

    ``use_save_as`` picks the "As..." variant, which always prompts for a name and
    therefore cannot silently overwrite an existing published workbook.
    """
    target = "Save to Tableau Public As" if use_save_as else "Save to Tableau Public"

    # PRIMARY PATH: the keyboard shortcut. Command+Shift+S maps to
    # "Save to Tableau Public As..." in Tableau Public 2026.2.0.
    #
    # This replaced a CGEvent click on the menu item, which was unreliable in
    # practice: the item's AX geometry is only valid while the same osascript call
    # holds the menu open, the menu's width (and therefore the click point) varies
    # with the recent-files list, and even a correctly-computed dwell-then-click on
    # the highlighted item frequently did nothing. A shortcut needs no geometry, no
    # open menu and no mouse tracking.
    if use_save_as:
        try:
            real_key(VK_ANSI_S, command=True, shift=True)
            if find_named_window(SAVE_DIALOG_TITLE, timeout=12):
                return True, "invoked Save to Tableau Public As... via Command+Shift+S"
        except Exception as exc:  # noqa: BLE001 - fall through to the menu path
            _ = exc  # the menu fallback below reports any real failure

    # FALLBACK: drive the File menu.
    point = open_menu_and_locate(target)
    if point is None:
        close_open_menu()
        legacy = _invoke_via_server_menu()
        if legacy[0]:
            return legacy
        available = [i.split("|")[0] for i in file_menu_items()]
        return False, (
            f"could not locate an enabled {target!r} item on the File menu. "
            f"File menu contained: {' | '.join(available)}"
        )

    # Qt ignores an AX click on a menu item; only a real HID event activates it.
    real_click(*point)
    return True, f"invoked File > {target}... via CGEvent click at {point}"


def _invoke_via_server_menu() -> tuple[bool, str]:
    """Legacy path: Server > Tableau Public > Save to Tableau Public (Desktop Pro)."""
    script = f"""
    tell application "System Events"
      tell process "{PROCESS_NAME}"
        click menu bar item "{SERVER_MENU}" of menu bar 1
        delay 0.4
        set sm to menu 1 of menu bar item "{SERVER_MENU}" of menu bar 1
        click menu item "{TABLEAU_PUBLIC_ITEM}" of sm
        delay 0.4
        set tp to menu 1 of menu item "{TABLEAU_PUBLIC_ITEM}" of sm
        click (first menu item of tp whose name starts with "Save to Tableau Public")
        return "ok"
      end tell
    end tell
    """
    try:
        if osascript(script) == "ok":
            return True, "invoked via Server > Tableau Public (Desktop Professional path)"
    except DesktopError:
        pass
    return False, "Server menu publish path unavailable"


def verify_url(url: str, *, timeout: int = 25) -> tuple[bool, int | None]:
    """Load the published URL and confirm a successful response (layer 5)."""
    if not url.startswith("https://"):
        raise ValueError("only https URLs may be verified")
    req = urllib.request.Request(  # noqa: S310 - scheme is asserted https above
        url, headers={"User-Agent": "tableau-public-authoring/0.1"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return 200 <= resp.status < 400, resp.status
    except urllib.error.HTTPError as exc:
        return False, exc.code
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False, None


SAVE_DIALOG_TITLE = "Save Workbook to Tableau Public"
SIGN_IN_TITLE = "Tableau Public Sign In"

# Button centres as a FRACTION of the save dialog's live bounds.
#
# Calibrated from the real dialog (382x191 logical / 766x383 @2x). This is the one
# documented brittle fallback permitted by the project rules: Tableau exposes no AX
# buttons for this dialog, so there is nothing to address by name. The fractions are
# applied to the dialog's *live* bounds read from the window server, never to a
# hardcoded screen position, so the click follows the dialog wherever it opens.
# If Tableau changes this dialog's layout, re-measure these two constants.
SAVE_BUTTON_FRACTION = (0.855, 0.872)
CANCEL_BUTTON_FRACTION = (0.60, 0.872)


def onscreen_windows() -> list[dict]:
    """Tableau windows that are genuinely on screen right now.

    MUST NOT use ``kCGWindowListOptionAll``: the window server keeps entries for
    destroyed windows, and matching against those produced two separate bugs — a
    permanent false "sign-in required", and clicks aimed at a save dialog that had
    already been replaced.
    """
    try:
        import Quartz
    except ImportError:  # pragma: no cover
        return []
    info = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID,
    )
    out: list[dict] = []
    for w in info or []:
        if "Tableau" not in (w.get("kCGWindowOwnerName") or ""):
            continue
        b = w.get("kCGWindowBounds") or {}
        out.append(
            {
                "id": int(w.get("kCGWindowNumber", 0)),
                "title": w.get("kCGWindowName") or "",
                "x": float(b.get("X", 0)),
                "y": float(b.get("Y", 0)),
                "width": float(b.get("Width", 0)),
                "height": float(b.get("Height", 0)),
            }
        )
    return out


def find_named_window(title: str, *, timeout: float = 20.0, poll: float = 0.5) -> dict | None:
    """Wait for an on-screen Tableau window whose title matches ``title`` exactly.

    When several windows share the title (Tableau recreates the save dialog as it
    animates open) the LARGEST is returned, which is the settled one.
    """
    deadline = time.monotonic() + timeout
    while True:
        matches = [
            w for w in onscreen_windows() if w["title"] == title and w["width"] and w["height"]
        ]
        if matches:
            return max(matches, key=lambda w: w["width"] * w["height"])
        if time.monotonic() >= deadline:
            return None
        time.sleep(poll)


def _window_bounds(window_id: int) -> tuple[float, float, float, float] | None:
    try:
        import Quartz
    except ImportError:  # pragma: no cover
        return None
    info = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID
    )
    for w in info or []:
        if int(w.get("kCGWindowNumber", -1)) == window_id:
            b = w.get("kCGWindowBounds") or {}
            return float(b["X"]), float(b["Y"]), float(b["Width"]), float(b["Height"])
    return None


def wait_for_stable_dialog(
    title: str, *, timeout: float = 25.0, min_area: int = 20_000
) -> dict | None:
    """Wait until a dialog exists AND has stopped resizing.

    Tableau's save dialog is first reported at ~126x100 while it animates open and
    is assigned a DIFFERENT window id once settled (~382x191). Acting on the first
    sighting clicked a window that had already been destroyed. So: poll until the
    bounds repeat across two consecutive reads at a plausible size, and always
    return the freshest window id.
    """
    deadline = time.monotonic() + timeout
    previous: tuple[int, int] | None = None
    while time.monotonic() < deadline:
        win = find_named_window(title, timeout=0.1)
        if win:
            current = (int(win["width"]), int(win["height"]))
            if current[0] * current[1] >= min_area and current == previous:
                return win
            previous = current
        time.sleep(0.4)
    return None


def click_dialog_button(title: str, fraction: tuple[float, float]) -> tuple[bool, str]:
    """Click a dialog button using its live bounds and a calibrated fraction.

    Looks the window up by title at click time rather than trusting a previously
    captured id, because Tableau recreates the dialog window while it animates.
    """
    win = find_named_window(title, timeout=2.0)
    if win is None:
        return False, f"dialog {title!r} is no longer on screen"
    bounds = _window_bounds(int(win["id"]))
    if bounds is None:
        return False, f"dialog window {win['id']} vanished before the click"
    x, y, w, h = bounds
    px, py = x + w * fraction[0], y + h * fraction[1]
    real_click(px, py)
    return True, f"clicked at ({px:.0f},{py:.0f}) within dialog bounds {int(w)}x{int(h)}"


def cancel_save_dialog(*, timeout: float = 8.0) -> bool:
    """Dismiss the save dialog with Escape.

    Escape is used rather than clicking Cancel: the Cancel button click was observed
    to leave the dialog on screen (it repaints blank mid-transition and lingers),
    whereas Escape closes it deterministically. The Save button click, by contrast,
    is verified working — see SAVE_BUTTON_FRACTION.
    """
    try:
        osascript(
            f'tell application "System Events" to tell process "{PROCESS_NAME}" to key code 53'
        )
    except DesktopError:
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not find_named_window(SAVE_DIALOG_TITLE, timeout=0.1):
            return True
        time.sleep(0.4)
    return False


def set_dialog_title(text: str) -> tuple[bool, str]:
    """Replace the pre-filled Workbook Title with ``text``.

    Tableau pre-fills the field from the file name and focuses it, so select-all
    then type replaces it. Keystrokes DO reach Qt (unlike Accessibility clicks on
    menu items), because System Events synthesises them as session-level events.
    """
    safe = as_escape(text)
    try:
        osascript(
            f'tell application "System Events" to tell process "{PROCESS_NAME}"\n'
            f'  keystroke "a" using command down\n'
            f"  delay 0.25\n"
            f'  keystroke "{safe}"\n'
            f"end tell"
        )
    except DesktopError as exc:
        return False, f"could not set the workbook title: {exc}"
    return True, f"typed workbook title {text!r}"


def publish(
    *,
    workbook_window: str,
    public_name: str,
    screenshot_dir: Path,
    workbook_path: Path | None = None,
    profile: str | None = None,
    set_title: bool = True,
    wait_timeout: float = 300.0,
) -> PublishResult:
    """Drive the visible publish flow to completion. Never handles credentials.

    Steps: focus -> frontmost precondition -> File > Save to Tableau Public As... ->
    (hand off if sign-in appears) -> set title -> click Save -> wait for submission ->
    resolve and verify the public URL.
    """
    res = PublishResult(published=False, requires_sign_in=False, workbook_name=public_name)

    if not _focus_workbook(workbook_window, file_path=workbook_path):
        res.error = f"could not focus a Tableau window matching {workbook_window!r}"
        return res
    res.steps.append(f"focused window matching {workbook_window!r}")

    # HARD PRECONDITION: never dispatch a publish command unless the intended
    # workbook is genuinely the active document, or it would publish the wrong one.
    safe, why = assert_target_frontmost(workbook_window)
    res.steps.append(f"precondition: {why}")
    if not safe:
        res.error = why
        return res

    ok, detail = invoke_save_to_public(use_save_as=True)
    res.steps.append(f"menu: {detail}")
    if not ok:
        res.error = detail
        return res

    # Either a sign-in window or the save dialog will appear.
    #
    # A sign-in window showing is NOT by itself a failure. When the desktop session
    # is already authenticated Tableau still flashes an auth web view that resolves
    # itself within a few seconds and then the save dialog appears. Bailing on first
    # sight of it reported "sign in required" to an already-signed-in user. So we
    # only hand off if the sign-in window PERSISTS, meaning it is genuinely waiting
    # for input.
    deadline = time.monotonic() + 90.0
    sign_in_since: float | None = None
    dialog = None
    while time.monotonic() < deadline:
        dialog = find_named_window(SAVE_DIALOG_TITLE, timeout=0.1)
        if dialog:
            break

        if detect_sign_in_required():
            now = time.monotonic()
            if sign_in_since is None:
                sign_in_since = now
                res.steps.append("sign-in window appeared; waiting to see if it resolves")
            elif now - sign_in_since > SIGN_IN_PATIENCE:
                res.requires_sign_in = True
                res.error = (
                    f"Tableau's sign-in window has been waiting for input for "
                    f"{SIGN_IN_PATIENCE:.0f}s. Complete sign-in manually in the Tableau "
                    f"Public app, then re-run publish. This server never reads, types "
                    f"or stores credentials."
                )
                res.steps.append("halted at sign-in checkpoint")
                return res
        else:
            sign_in_since = None

        err = read_error_dialog(dismiss=True)
        if err:
            res.error = f"Tableau reported: {err[:600]}"
            return res
        time.sleep(0.5)

    if dialog:
        settled = wait_for_stable_dialog(SAVE_DIALOG_TITLE)
        if settled:
            dialog = settled

    if not dialog:
        res.error = (
            f"the {SAVE_DIALOG_TITLE!r} dialog did not appear within 30s. The menu "
            f"command was dispatched, so Tableau may be busy or the workbook may have "
            f"no fields on any shelf (Tableau disables publishing for a field-less viz)."
        )
        return res
    res.steps.append(f"save dialog appeared ({dialog['width']}x{dialog['height']})")

    if set_title:
        ok_t, why_t = set_dialog_title(public_name)
        res.steps.append(f"title: {why_t}")
        if not ok_t:
            res.steps.append("continuing with Tableau's pre-filled title")

    try:
        shot = screenshot_dir / "publish-01-save-dialog.png"
        screenshot_window(int(dialog["id"]), shot)
        res.screenshots.append(str(shot))
    except DesktopError:
        pass

    ok_c, why_c = click_dialog_button(SAVE_DIALOG_TITLE, SAVE_BUTTON_FRACTION)
    res.steps.append(f"save button: {why_c}")
    if not ok_c:
        res.error = why_c
        return res

    # The dialog closing is the signal that the upload was submitted.
    closed_by = time.monotonic() + 60.0
    while time.monotonic() < closed_by:
        if not find_named_window(SAVE_DIALOG_TITLE, timeout=0.1):
            break
        time.sleep(0.5)
    else:
        res.error = "the save dialog never closed; publication was not submitted"
        return res
    res.steps.append("save dialog closed - upload submitted")

    err = read_error_dialog(dismiss=True)
    if err:
        res.error = f"Tableau reported after Save: {err[:600]}"
        return res

    if not profile:
        res.steps.append("no profile supplied - cannot resolve the public URL")
        res.error = (
            "Publication was submitted, but no 'profile' was supplied so the public URL "
            "could not be resolved or verified. Pass profile=<your Tableau Public "
            "profile name> to confirm the result."
        )
        return res

    url = _await_published_url(profile, public_name, timeout=wait_timeout)
    if not url:
        res.error = (
            f"Publication was submitted but {public_name!r} did not appear on profile "
            f"{profile!r} within {wait_timeout:.0f}s. It may still be processing; "
            f"re-check with verify_published_workbook."
        )
        return res
    res.public_url = url
    res.steps.append(f"resolved public URL: {url}")

    verified, status = verify_url(url)
    res.url_verified = verified
    res.http_status = status
    res.published = verified
    if not verified:
        res.error = f"published URL returned HTTP {status}"
    return res


def _await_published_url(profile: str, title: str, *, timeout: float) -> str | None:
    """Poll the user's public profile until the newly published workbook appears."""
    try:
        from .existing import list_published_workbooks
    except ImportError:  # pragma: no cover - module lands with overwrite protection
        return None

    wanted = {title.strip().lower(), title.strip().lower().replace(" ", "_")}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            for wb in list_published_workbooks(profile):
                if wb.title.strip().lower() in wanted:
                    return wb.direct_url
        except Exception as exc:  # noqa: BLE001 - polling must not abort the publish
            # A transient profile-query failure is expected while Tableau is still
            # processing the upload; keep polling rather than reporting a failure.
            last_error = exc
            _ = last_error
        time.sleep(5)
    return None
