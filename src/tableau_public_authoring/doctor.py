"""Preflight check: is this machine actually able to run the server?

Everything this server does beyond generating XML depends on conditions no
Python import can establish - Tableau installed, two macOS permissions granted
to *the process that will run the server*, and a native extension that is easy
to install into the wrong environment.

Each of those fails **quietly** at runtime. Missing Screen Recording yields
blank screenshots, not an error. Missing Accessibility yields keystrokes that go
nowhere. A missing Quartz yields an empty window list, so Tableau looks like it
has no documents open and publishing reports "no document window matching ...".
Diagnosing any of that from inside an MCP conversation is miserable, because the
tool output describes a symptom three layers from the cause.

So this runs standalone, before the server is wired into anything:

    tableau-public-authoring doctor

Permissions are granted per-executable. Running this from a terminal checks the
*terminal's* permissions, which is why the report prints the interpreter it is
running under - that is the identity macOS will prompt about, and it must be the
same one registered with the MCP client.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

OK = "ok"
WARN = "warn"
FAIL = "fail"

_MARK = {OK: "PASS", WARN: "WARN", FAIL: "FAIL"}


@dataclass
class Check:
    name: str
    state: str
    detail: str
    fix: str | None = None


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if c.state == FAIL]

    @property
    def warned(self) -> list[Check]:
        return [c for c in self.checks if c.state == WARN]

    def render(self) -> str:
        width = max((len(c.name) for c in self.checks), default=0)
        lines = ["", "Tableau Public Authoring MCP - preflight", ""]
        for c in self.checks:
            lines.append(f"  [{_MARK[c.state]}] {c.name.ljust(width)}  {c.detail}")
        lines.append("")
        if self.failed:
            lines.append(f"{len(self.failed)} blocking problem(s):")
            for c in self.failed:
                lines.append(f"\n  {c.name}\n    {c.detail}")
                if c.fix:
                    for ln in c.fix.strip().split("\n"):
                        lines.append(f"    {ln}")
        elif self.warned:
            lines.append("Usable, with caveats:")
            for c in self.warned:
                lines.append(f"\n  {c.name}\n    {c.detail}")
                if c.fix:
                    for ln in c.fix.strip().split("\n"):
                        lines.append(f"    {ln}")
        else:
            lines.append("Everything needed is present. The server is ready to register.")
        lines.append("")
        return "\n".join(lines)


def _check_platform() -> Check:
    if sys.platform != "darwin":
        return Check(
            "platform",
            FAIL,
            f"{sys.platform} - this server drives the macOS Tableau Public app",
            "There is no headless or cross-platform path: Tableau Public has no\n"
            "publishing API, so publishing is done through the real desktop UI.",
        )
    return Check("platform", OK, "macOS")


def _check_python() -> Check:
    v = sys.version_info
    detail = f"{v.major}.{v.minor}.{v.micro} at {sys.executable}"
    if (v.major, v.minor) < (3, 10):
        return Check("python", FAIL, detail, "Python 3.10 or newer is required.")
    return Check("python", OK, detail)


def _check_tableau() -> Check:
    from .desktop import tableau_app

    app = tableau_app.find_app()
    if not app:
        return Check(
            "tableau public",
            FAIL,
            "not found",
            "Install Tableau Public (free) from https://www.tableau.com/products/public\n"
            f"Looked in: {', '.join(tableau_app.APP_PATHS)}",
        )
    version = tableau_app.app_version(app) or "unknown version"
    return Check("tableau public", OK, f"{version} at {app}")


def _check_quartz() -> Check:
    try:
        import Quartz  # noqa: F401
    except ImportError:
        return Check(
            "quartz (pyobjc)",
            FAIL,
            "not importable - window discovery would silently find nothing",
            "uv pip install 'pyobjc-framework-Quartz>=10.0'\n"
            "Install it into the SAME interpreter shown above, not a different venv.",
        )
    return Check("quartz (pyobjc)", OK, "importable")


def _check_hyper() -> Check:
    try:
        import tableauhyperapi  # noqa: F401
    except ImportError:
        return Check(
            "tableauhyperapi",
            FAIL,
            "not importable - no workbook can be built",
            "uv pip install 'tableauhyperapi>=0.0.25080'\n"
            "Tableau Public rejects any workbook that is not extract-backed\n"
            "(Error Code 3C242D89), so every CSV must become a .hyper.",
        )
    return Check("tableauhyperapi", OK, "importable")


def _check_accessibility() -> Check:
    from .desktop import tableau_app

    if tableau_app.check_accessibility():
        return Check("accessibility", OK, "granted to this process")
    return Check(
        "accessibility",
        FAIL,
        "not granted - keystrokes and clicks would go nowhere",
        "System Settings > Privacy & Security > Accessibility, then add:\n"
        f"    {sys.executable}\n"
        "Grant it to the interpreter above, not to Tableau. Permissions are\n"
        "per-executable, so the one you register with your MCP client is the\n"
        "one that needs it.",
    )


def _check_screen_recording() -> Check:
    """Screen Recording cannot be queried directly; capture and look at the result.

    A denied process still gets a successful screencapture call - the image is
    just blank or desktop-only. So the check takes a real capture and inspects
    the bytes rather than trusting the exit code.
    """
    if not shutil.which("screencapture"):
        return Check("screen recording", WARN, "screencapture not found; cannot verify")
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        shot = Path(td) / "probe.png"
        try:
            subprocess.run(
                ["screencapture", "-x", "-C", str(shot)],
                capture_output=True,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return Check("screen recording", WARN, f"probe failed: {exc}")
        if not shot.exists() or shot.stat().st_size < 1024:
            return Check(
                "screen recording",
                FAIL,
                "capture produced nothing - validation screenshots would be blank",
                "System Settings > Privacy & Security > Screen Recording, then add:\n"
                f"    {sys.executable}",
            )
    return Check("screen recording", OK, "capture succeeded")


def _check_mcp() -> Check:
    try:
        import mcp  # noqa: F401
    except ImportError:
        return Check("mcp sdk", FAIL, "not importable", "uv pip install 'mcp>=1.28.0'")
    return Check("mcp sdk", OK, "importable")


def run() -> Report:
    """Run every check. Order is cheapest-and-most-fundamental first."""
    report = Report()
    report.checks.append(_check_platform())
    report.checks.append(_check_python())
    report.checks.append(_check_mcp())
    report.checks.append(_check_hyper())
    if sys.platform == "darwin":
        report.checks.append(_check_quartz())
        report.checks.append(_check_tableau())
        report.checks.append(_check_accessibility())
        report.checks.append(_check_screen_recording())
    return report


def main(argv: list[str] | None = None) -> int:
    report = run()
    print(report.render())
    return 1 if report.failed else 0
