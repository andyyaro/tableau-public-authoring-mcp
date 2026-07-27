"""Fixtures for the live tier: real workbooks, opened in the real Tableau Public.

READ THIS BEFORE ADDING A TEST HERE
-----------------------------------
Everything in this package drives a visible GUI on the developer's machine. That
makes it powerful (it is the only thing that catches "Tableau loaded the file and
drew nothing") and dangerous (it moves windows, presses keys and can close
documents). The safety rules encoded below are not stylistic:

* **Opt-in only.** A bare ``pytest`` run *deselects* this whole package, because
  ``pyproject.toml`` declares the ``live`` marker but sets no ``addopts`` filter.
  Without the collection hook here, ``pytest`` would launch Tableau on a laptop
  or, worse, in CI. Select the tier with ``-m live`` or ``TABLEAU_LIVE_TESTS=1``.
* **Environment skips, never failures.** Not macOS, no Tableau, no Accessibility,
  no Screen Recording -> the tier skips. A Linux CI box must never go red here.
* **Every workbook is named ``LiveTest_...``.** Teardown closes exactly those and
  nothing else. A workbook such as ``Quarterly_Sales_Review`` belongs
  to the user; ``window_control.close_all_generated`` refuses to touch anything
  that does not start with a prefix we pass, and we only ever pass ours.
* **Nothing here publishes.** See ``test_publish_flow.py``.

Cleanup matters more than it looks: a previous session left ~18 workbooks open
and Tableau stopped accepting new ones altogether, which looks exactly like a
compiler bug until you notice the window count.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from tableau_public_authoring.compiler.build import build_workbook
from tableau_public_authoring.desktop import tableau_app, window_control

from .canvas import WORKSHEET_CANVAS, CanvasStats, CropBox, ImageDecodeError, analyse_png

# Every workbook this tier creates starts with this. It is the ONLY thing
# teardown is allowed to close. Do not shorten it: window_control enforces a
# 3-character minimum precisely so that a stray "E" cannot sweep up real work.
LIVE_PREFIX = "LiveTest"

#: Opt-in environment variable, an alternative to ``-m live``.
OPT_IN_ENV = "TABLEAU_LIVE_TESTS"

#: Synthetic data. No real-world data ever goes near a publish flow.
FIXTURE_CSV = Path(__file__).resolve().parents[1] / "fixtures" / "data" / "ev_site_readiness.csv"

#: Tableau degrades badly with many documents open (see the module docstring).
#: Failing fast beats wedging the app halfway through a run.
MAX_LIVE_WORKBOOKS = 12

#: Seconds to wait for a window after `open -a`. Cold-starting Tableau, opening
#: the .twbx and materialising the extract is slow on first run.
OPEN_TIMEOUT_S = 120.0

#: Seconds to keep re-screenshotting while the canvas is still blank. Marks
#: appear within a couple of seconds once the window is up; this is headroom.
RENDER_TIMEOUT_S = 30.0

_deselected_live = 0


# --------------------------------------------------------------- opt-in gate


def _explicitly_requested(config: pytest.Config) -> bool:
    """True when the run named this tier, by marker or by environment variable.

    ``-m "not live"`` also matches, which is harmless: pytest's own marker filter
    then deselects exactly the same tests a moment later.
    """
    markexpr = str(getattr(config.option, "markexpr", "") or "")
    if "live" in markexpr or "publish" in markexpr:
        return True
    return os.environ.get(OPT_IN_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _in_live_tier(item: pytest.Item) -> bool:
    raw = getattr(item, "path", None) or getattr(item, "fspath", None)
    if raw is None:
        return False
    return Path(str(raw)).resolve().parent == Path(__file__).resolve().parent


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Deselect the live tier unless it was asked for by name.

    ``pyproject.toml`` has no ``addopts``, so ``-m live`` is the only marker
    filter in play and a plain ``pytest`` run would otherwise *execute* these
    tests. Deselecting (rather than skipping) keeps a default run's output honest
    and guarantees no GUI call is ever made.
    """
    global _deselected_live
    if _explicitly_requested(config):
        return
    keep: list[pytest.Item] = []
    dropped: list[pytest.Item] = []
    for item in items:
        (dropped if _in_live_tier(item) else keep).append(item)
    if dropped:
        _deselected_live = len(dropped)
        config.hook.pytest_deselected(items=dropped)
        items[:] = keep


def pytest_report_collectionfinish(config: pytest.Config, items: list[pytest.Item]) -> list[str]:
    if _explicitly_requested(config) or not _deselected_live:
        return []
    return [
        f"live tier: {_deselected_live} test(s) not selected "
        f"(run with -m live, or {OPT_IN_ENV}=1, to drive the real Tableau Public app)"
    ]


# ------------------------------------------------------------- environment


def _screen_recording_granted() -> bool:
    """True when this process may capture window contents.

    ``CGPreflightScreenCaptureAccess`` is the non-prompting query;
    ``CGRequestScreenCaptureAccess`` is the one that pops a system dialog and is
    deliberately NOT used — a test run must never ambush the user with a
    permission prompt.
    """
    try:
        import Quartz
    except ImportError:  # pragma: no cover - environment guard
        return False
    preflight = getattr(Quartz, "CGPreflightScreenCaptureAccess", None)
    if preflight is None:  # pragma: no cover - pre-Catalina, no such concept
        return True
    return bool(preflight())


@dataclass
class LiveEnvironment:
    """Everything a live test needs, plus the bookkeeping teardown relies on."""

    app_path: str
    version: str | None
    run_id: str
    output_dir: Path
    screenshot_dir: Path
    csv: Path
    opened: list[str] = field(default_factory=list)

    def workbook_name(self, slug: str) -> str:
        """A workbook name unique to this run.

        Uniqueness is not cosmetic: ``open -a`` on a path whose window is already
        open just raises the existing window, so a reused name would silently
        screenshot the *previous* test's workbook.
        """
        return f"{LIVE_PREFIX} {self.run_id} {slug}"


@pytest.fixture(scope="session", autouse=True)
def live_env(tmp_path_factory: pytest.TempPathFactory, request: pytest.FixtureRequest):
    """Session guard, temp workspace, and teardown that closes what we opened.

    Autouse so that a test which forgets to request it still cannot run against a
    machine that has no Tableau, no permissions, or no fixture data.
    """
    if sys.platform != "darwin":
        pytest.skip("the live tier drives the macOS Tableau Public app")
    try:
        import Quartz  # noqa: F401  (import is the check)
    except ImportError:
        pytest.skip("pyobjc/Quartz is unavailable; Tableau's windows cannot be enumerated")

    app = tableau_app.find_app()
    if app is None:
        pytest.skip(f"Tableau Public is not installed at any of {list(tableau_app.APP_PATHS)}")
    if not tableau_app.check_accessibility():
        pytest.skip(
            "macOS Accessibility permission is not granted to the process running pytest. "
            "System Settings > Privacy & Security > Accessibility."
        )
    if not _screen_recording_granted():
        pytest.skip(
            "macOS Screen Recording permission is not granted, so window screenshots would "
            "be blank. System Settings > Privacy & Security > Screen Recording."
        )
    if not FIXTURE_CSV.exists():
        pytest.skip(f"fixture data is missing: {FIXTURE_CSV}")

    root = tmp_path_factory.mktemp("tableau-live")
    shots = root / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    env = LiveEnvironment(
        app_path=app,
        version=tableau_app.app_version(app),
        run_id=time.strftime("%H%M%S"),
        output_dir=root,
        screenshot_dir=shots,
        csv=FIXTURE_CSV,
    )

    reporter = request.config.pluginmanager.get_plugin("terminalreporter")

    def say(message: str) -> None:
        if reporter is not None:
            reporter.write_line(message)

    say(f"[live] Tableau Public {env.version or '?'} at {env.app_path}")
    say(f"[live] workbooks -> {env.output_dir} (prefix {LIVE_PREFIX}_{env.run_id})")

    yield env

    # ---- teardown: close ONLY our own workbooks -----------------------------
    if not env.opened:
        return
    say(f"[live] closing {len(env.opened)} generated workbook(s) with prefix {LIVE_PREFIX!r}")
    try:
        result = window_control.close_all_generated([LIVE_PREFIX], dry_run=False)
    except Exception as exc:  # noqa: BLE001 - teardown must never mask a test result
        say(f"[live] CLEANUP FAILED ({type(exc).__name__}: {exc}). Close them by hand.")
        return
    for entry in result.get("closed", []):
        say(f"[live]   closed {entry['stem']}")
    for entry in result.get("failed", []):
        say(f"[live]   COULD NOT CLOSE {entry['stem']}: {entry['reason']}")
    if result.get("failed"):
        say(
            "[live] leftover LiveTest_* windows will slow the next run down; close them in "
            "Tableau before re-running."
        )


@pytest.fixture(scope="session")
def sample_csv(live_env: LiveEnvironment) -> Path:
    """The synthetic EV-charging dataset every live workbook is built from."""
    return live_env.csv


# ------------------------------------------------------------- spec building


def make_live_spec(
    env: LiveEnvironment,
    slug: str,
    worksheets: Sequence[dict[str, Any]],
    *,
    dashboards: Sequence[dict[str, Any]] | None = None,
    calculated_fields: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a spec dict wired to the fixture CSV and this run's temp output."""
    spec: dict[str, Any] = {
        "spec_version": "0.1",
        "workbook": {
            "name": env.workbook_name(slug),
            "description": "Automated live-tier render check. Synthetic data. Never published.",
        },
        "data_sources": [{"id": "sites", "type": "csv", "path": str(env.csv)}],
        "worksheets": list(worksheets),
        "output": {"directory": str(env.output_dir), "package_twbx": True},
    }
    if calculated_fields:
        spec["calculated_fields"] = list(calculated_fields)
    if dashboards:
        spec["dashboards"] = list(dashboards)
    return spec


# ------------------------------------------------------------------ opening


@dataclass(frozen=True)
class LiveRender:
    """The outcome of building a spec, opening it, and photographing the result."""

    name: str
    stem: str
    workbook: Path
    opened: bool
    window: dict | None
    error: str | None
    screenshot: Path | None
    stats: CanvasStats | None
    elapsed_s: float
    #: Why the screenshot or its analysis failed. Kept apart from ``error``,
    #: which means "Tableau complained": a capture failure is our problem, not
    #: evidence about the workbook, and conflating them sends the reader to the
    #: wrong place.
    capture_error: str | None = None

    def explain(self, note: str = "") -> str:
        """A failure message a human can act on without re-deriving anything."""
        lines = [
            note or "live render failed",
            f"  workbook: {self.name}",
            f"  file:     {self.workbook}",
            f"  opened:   {self.opened} after {self.elapsed_s:.1f}s",
            f"  window:   {(self.window or {}).get('title')!r}",
            f"  error:    {self.error!r}",
        ]
        if self.capture_error:
            lines.append(f"  capture:  {self.capture_error}")
        if self.stats is not None:
            lines.append(f"  pixels:   {self.stats.describe()}")
        elif self.screenshot is not None:
            lines.append(f"  screenshot: {self.screenshot}")
        return "\n".join(lines)


def _wait_for_render(
    stem: str,
    out_path: Path,
    crop: CropBox,
    *,
    timeout: float,
    poll: float = 1.5,
) -> tuple[CanvasStats | None, dict | None]:
    """Screenshot the window repeatedly until its canvas has ink, or time out.

    Polling the pixels beats a fixed sleep in both directions: a fast render is
    not paid for, and a slow one (cold extract, big window) is not failed for.
    The final screenshot is the one left on disk, so a failure report always
    shows the state the assertion actually judged.
    """
    deadline = time.monotonic() + timeout
    stats: CanvasStats | None = None
    window: dict | None = None
    while True:
        window = tableau_app.find_window(stem) or window
        if window is None:
            return None, None
        tableau_app.screenshot_window(int(window["id"]), out_path)
        stats = analyse_png(out_path, crop)
        if not stats.looks_blank or time.monotonic() >= deadline:
            return stats, window
        time.sleep(poll)


@pytest.fixture(scope="session")
def open_and_capture(live_env: LiveEnvironment) -> Callable[..., LiveRender]:
    """``spec -> built -> opened in Tableau -> screenshot -> pixel stats``.

    Returns a :class:`LiveRender`; it does NOT assert. Each test decides what
    counts as a pass, and prints the measurement when it does not.
    """

    def run(
        spec: dict[str, Any],
        *,
        crop: CropBox = WORKSHEET_CANVAS,
        open_timeout: float = OPEN_TIMEOUT_S,
        render_timeout: float = RENDER_TIMEOUT_S,
    ) -> LiveRender:
        if len(live_env.opened) >= MAX_LIVE_WORKBOOKS:
            pytest.fail(
                f"refusing to open more than {MAX_LIVE_WORKBOOKS} workbooks in one session: "
                f"Tableau stops accepting new documents long before this and every later "
                f"result would be meaningless. Already opened: {live_env.opened}"
            )

        started = time.monotonic()
        build = build_workbook(spec)
        target = build.twbx_path or build.twb_path
        stem = target.stem
        live_env.opened.append(stem)

        result = tableau_app.open_workbook(target, timeout=open_timeout)
        if not result["opened"]:
            return LiveRender(
                name=build.workbook_name,
                stem=stem,
                workbook=target,
                opened=False,
                window=None,
                error=result["error"],
                screenshot=None,
                stats=None,
                elapsed_s=time.monotonic() - started,
            )

        # A load error can surface after the window exists, so it is checked here
        # as well as inside open_workbook's wait loop.
        error = tableau_app.read_error_dialog(dismiss=True)

        shot = live_env.screenshot_dir / f"{stem}.png"
        capture_error: str | None = None
        stats: CanvasStats | None = None
        window: dict | None = None
        try:
            stats, window = _wait_for_render(stem, shot, crop, timeout=render_timeout)
            if stats is None:
                capture_error = (
                    f"the window for {stem!r} disappeared before it could be captured; "
                    f"Tableau windows currently open: {tableau_app.window_names()}"
                )
        except (tableau_app.DesktopError, ImageDecodeError) as exc:
            # Most likely Screen Recording permission, which the session guard
            # checks up front - so reaching here means it was revoked mid-run, or
            # screencapture failed for a reason worth reading verbatim.
            capture_error = f"{type(exc).__name__}: {exc}"

        late_error = tableau_app.read_error_dialog(dismiss=True)

        return LiveRender(
            name=build.workbook_name,
            stem=stem,
            workbook=target,
            opened=True,
            window=window or {"title": result["window"], "id": result["window_id"]},
            error=error or late_error,
            screenshot=shot if shot.exists() else None,
            stats=stats,
            elapsed_s=time.monotonic() - started,
            capture_error=capture_error,
        )

    return run
