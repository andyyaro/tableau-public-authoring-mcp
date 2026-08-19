"""Fixtures for the live tier: real workbooks, opened in the real Tableau Public.

READ THIS BEFORE ADDING A TEST HERE
-----------------------------------
Everything in this package drives a visible GUI on the developer's machine. That
makes it powerful (it is the only thing that catches "Tableau loaded the file and
drew nothing") and dangerous (it moves windows, presses keys and can close
documents). The safety rules encoded below are not stylistic:

* **Opt-in only, by two independent mechanisms.** ``pyproject.toml`` sets
  ``addopts = "-m 'not live'"``, so a bare ``pytest`` deselects everything
  carrying the ``live`` marker. The collection hook below is the second
  mechanism and covers what the first cannot: a test placed in this package
  *without* the marker. See "TWO MECHANISMS" in that hook. Select the tier with
  ``-m live`` or ``TABLEAU_LIVE_TESTS=1``.
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

#: The marker filter ``pyproject.toml`` puts in ``addopts``. Recognised by value
#: so the environment-variable route can tell the project's own
#: deselect-the-tier default apart from a filter the caller typed themselves.
#: Keep this in step with ``[tool.pytest.ini_options] addopts``; a unit test
#: pins the pyproject side (tests/unit/test_coverage_gaps.py).
DEFAULT_MARKEXPR = "not live"

#: Synthetic data. No real-world data ever goes near a publish flow.
_FIXTURE_DATA = Path(__file__).resolve().parents[1] / "fixtures" / "data"
FIXTURE_CSV = _FIXTURE_DATA / "ev_site_readiness.csv"

#: A second, structurally unrelated table. Used only by the two-data-source
#: case; it shares no column name with FIXTURE_CSV, so a workbook that renders
#: it is unambiguously reading the second source and not the first.
FIXTURE_CSV_2 = _FIXTURE_DATA / "ev_utilization.csv"

#: Tableau degrades badly with many documents open (see the module docstring).
#: Failing fast beats wedging the app halfway through a run. The observed wedge
#: point was roughly eighteen open documents; a full `-m live` run currently
#: opens twelve, so this must stay above that and comfortably below eighteen.
MAX_LIVE_WORKBOOKS = 14

#: Seconds to wait for a window after `open -a`. Cold-starting Tableau, opening
#: the .twbx and materialising the extract is slow on first run.
OPEN_TIMEOUT_S = 120.0

#: Seconds to keep re-screenshotting while the canvas is still blank. Marks
#: appear within a couple of seconds once the window is up; this is headroom.
RENDER_TIMEOUT_S = 30.0

_collection_notes: list[str] = []


# --------------------------------------------------------------- opt-in gate


def env_opt_in() -> bool:
    """True when ``TABLEAU_LIVE_TESTS`` names a truthy value."""
    return os.environ.get(OPT_IN_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def resolve_selection(markexpr: str, *, env_opt_in: bool) -> tuple[str, bool]:
    """Decide the marker filter to run under, and who deselects the tier.

    Returns ``(markexpr_to_use, deselect_here)``.

    This is the whole opt-in decision, extracted as a pure function so it can be
    tested without running pytest inside pytest. Its predecessor asked
    ``if "live" in markexpr`` and treated the project's own default filter,
    ``"not live"``, as "the caller asked for the live tier" - so the hook
    returned early on every run and the second mechanism never deselected
    anything at all.

    The four cases:

    * **Default run** (``-m "not live"`` from ``addopts``, no environment
      variable): left alone. pytest's own marker filter deselects the tier.
    * **Environment-variable opt-in with that same default filter**: the filter
      is dropped, because it would otherwise deselect exactly the tests the
      caller just asked for. This is what made
      ``TABLEAU_LIVE_TESTS=1 pytest tests/live`` select *nothing*.
    * **Any marker filter the caller typed themselves** (``-m live``,
      ``-m "live and not publish"``, ``-m publish``): always wins, environment
      variable or not. Guessing at someone's explicit ``-m`` is how a run that
      asked for four publish tests silently becomes a run of fourteen.
    * **No marker filter at all** (``addopts`` removed, or ``-m ""``): nothing
      else will exclude the tier, so this conftest must do it itself.
    """
    expr = markexpr.strip()
    if env_opt_in:
        return ("", False) if expr in ("", DEFAULT_MARKEXPR) else (markexpr, False)
    if expr == "":
        return markexpr, True
    return markexpr, False


def _in_live_tier(item: pytest.Item) -> bool:
    raw = getattr(item, "path", None) or getattr(item, "fspath", None)
    if raw is None:
        return False
    return Path(str(raw)).resolve().parent == Path(__file__).resolve().parent


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Keep the GUI tier out of any run that did not ask for it.

    TWO MECHANISMS, BOTH REAL
    -------------------------
    1. ``pyproject.toml`` sets ``addopts = "-m 'not live'"``. That deselects
       every test carrying the ``live`` marker, wherever it lives, and it is the
       one that does the work on a normal day.
    2. This hook. It covers the case the marker filter structurally cannot: a
       test added to ``tests/live/`` that nobody marked. Such a test would run
       in a bare ``pytest`` and launch Tableau. It is marked here, before
       pytest's own filter runs, so mechanism 1 then treats it like every other
       live test. If mechanism 1 is missing altogether - no marker filter in
       play at all - this hook deselects the tier outright instead.

    Hook order is what makes both of those work: conftest plugins are registered
    after pytest's builtins and their ``pytest_collection_modifyitems`` therefore
    runs *first*, so a marker added (or a ``markexpr`` adjusted) here is in place
    by the time ``_pytest.mark`` does its deselecting.
    """
    _collection_notes.clear()
    opt_in = env_opt_in()
    before = str(getattr(config.option, "markexpr", "") or "")
    markexpr, deselect_here = resolve_selection(before, env_opt_in=opt_in)
    config.option.markexpr = markexpr
    if markexpr != before:
        _collection_notes.append(
            f"live tier: {OPT_IN_ENV} is set, so the default -m {before!r} filter was dropped "
            f"for this run"
        )

    live_items = [item for item in items if _in_live_tier(item)]
    unmarked = [i for i in live_items if i.get_closest_marker("live") is None]
    for item in unmarked:
        # Not a licence to skip the marker - tests/unit/test_coverage_gaps.py
        # fails when a module in this package forgets it. This is the net that
        # stops the mistake reaching the GUI in the meantime.
        item.add_marker(pytest.mark.live)
    if unmarked:
        _collection_notes.append(
            f"live tier: {len(unmarked)} test(s) in tests/live/ carry no 'live' marker and were "
            f"marked during collection: {', '.join(i.nodeid for i in unmarked)}"
        )

    if deselect_here and live_items:
        config.hook.pytest_deselected(items=live_items)
        items[:] = [item for item in items if not _in_live_tier(item)]
        _collection_notes.append(
            f"live tier: {len(live_items)} test(s) deselected by tests/live/conftest.py because "
            f"no marker filter was in force (has addopts been removed from pyproject.toml?)"
        )
    elif not opt_in and markexpr.strip() == DEFAULT_MARKEXPR and live_items:
        _collection_notes.append(
            f"live tier: {len(live_items)} test(s) not selected "
            f"(run with -m live, or {OPT_IN_ENV}=1, to drive the real Tableau Public app)"
        )


def pytest_report_collectionfinish(config: pytest.Config, items: list[pytest.Item]) -> list[str]:
    return list(_collection_notes)


# ------------------------------------------------------------- environment


def _screen_recording_granted() -> bool:
    """True when this process may capture window contents.

    ``CGPreflightScreenCaptureAccess`` is the non-prompting query;
    ``CGRequestScreenCaptureAccess`` is the one that pops a system dialog and is
    deliberately NOT used - a test run must never ambush the user with a
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
    # stem -> the file it was opened from. Teardown needs the path, not just the
    # name: a workbook Tableau has minimised off-screen has no tile to click and
    # can only be raised by re-opening its file.
    opened: dict[str, Path] = field(default_factory=dict)

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
    say(f"[live] cleaning up {len(env.opened)} generated workbook(s) with prefix {LIVE_PREFIX!r}")
    try:
        result = window_control.close_all_generated(
            [LIVE_PREFIX], dry_run=False, known_paths=dict(env.opened)
        )
    except Exception as exc:  # noqa: BLE001 - teardown must never mask a test result
        say(f"[live] CLEANUP FAILED ({type(exc).__name__}: {exc}). Close them by hand.")
        return
    for entry in result.get("closed", []):
        say(f"[live]   closed {entry['stem']}")
    # Scoped to this run: close_all_generated reports husks for every run that ever
    # used this prefix, and a count larger than the number opened reads as a bug.
    already = [s for s in result.get("already_closed", []) if s in env.opened]
    if already:
        say(f"[live]   already closed before teardown: {len(already)} ({', '.join(already)})")
    for entry in result.get("failed", []):
        say(f"[live]   COULD NOT CLOSE {entry['stem']}: {entry['reason']}")

    # Report against what is actually still open, not against what was attempted.
    # An earlier version counted destroyed windows as open and declared every
    # successful close a failure, so the check that matters is this one.
    leftover = sorted(
        d.workbook_stem
        for d in window_control.document_windows()
        if (d.workbook_stem or "").startswith(LIVE_PREFIX)
    )
    if leftover:
        say(
            f"[live] {len(leftover)} workbook(s) still open: {leftover}. They will slow the "
            f"next run down; close them in Tableau before re-running."
        )
    else:
        say(f"[live] all {len(env.opened)} generated workbook(s) are closed")


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
    data_sources: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a spec dict wired to the fixture CSV and this run's temp output.

    ``data_sources`` overrides the single ``sites`` source, for the one case that
    needs two of them (``test_encodings_and_sources.py``). Everything else takes
    the default: one source keeps a render failure attributable to the thing the
    test is actually about.
    """
    spec: dict[str, Any] = {
        "spec_version": "0.1",
        "workbook": {
            "name": env.workbook_name(slug),
            "description": "Automated live-tier render check. Synthetic data. Never published.",
        },
        "data_sources": list(data_sources)
        if data_sources
        else [{"id": "sites", "type": "csv", "path": str(env.csv)}],
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
                f"result would be meaningless. Already opened: {sorted(live_env.opened)}"
            )

        started = time.monotonic()
        build = build_workbook(spec)
        target = build.twbx_path or build.twb_path
        stem = target.stem
        live_env.opened[stem] = target

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
