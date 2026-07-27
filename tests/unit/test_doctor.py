"""The preflight check must be right about a broken machine, not just a good one.

A doctor that passes everything on the developer's laptop and is never exercised
against a failure is decoration. Each check here is driven into its failing
branch, because the failures are the entire reason the command exists: every one
of these conditions fails *silently* at runtime.
"""

from __future__ import annotations

import builtins
import sys

import pytest

from tableau_public_authoring import doctor


def _hide_import(monkeypatch, name: str) -> None:
    """Make one module unimportable, leaving every other import alone."""
    real = builtins.__import__

    def fake(mod, *a, **k):
        if mod == name or mod.startswith(name + "."):
            raise ImportError(f"simulated: {name} unavailable")
        return real(mod, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    monkeypatch.delitem(sys.modules, name, raising=False)


# --- individual checks -------------------------------------------------------


def test_missing_quartz_is_a_blocking_failure(monkeypatch):
    """The one that fails most quietly: window discovery just returns nothing.

    quartz_windows() catches the ImportError and returns [], so Tableau looks
    like it has no documents open and publishing reports "no document window
    matching ..." -- a message that points nowhere near the real cause.
    """
    _hide_import(monkeypatch, "Quartz")
    c = doctor._check_quartz()
    assert c.state == doctor.FAIL
    assert "silently" in c.detail
    assert "pyobjc-framework-Quartz" in c.fix


def test_missing_hyperapi_is_a_blocking_failure(monkeypatch):
    _hide_import(monkeypatch, "tableauhyperapi")
    c = doctor._check_hyper()
    assert c.state == doctor.FAIL
    assert "3C242D89" in c.fix, "the fix should say WHY an extract is mandatory"


def test_missing_mcp_sdk_is_a_blocking_failure(monkeypatch):
    _hide_import(monkeypatch, "mcp")
    assert doctor._check_mcp().state == doctor.FAIL


def test_tableau_not_installed_is_a_blocking_failure(monkeypatch):
    from tableau_public_authoring.desktop import tableau_app

    monkeypatch.setattr(tableau_app, "find_app", lambda: None)
    c = doctor._check_tableau()
    assert c.state == doctor.FAIL
    assert "tableau.com" in c.fix, "tell the user where to get it"


def test_tableau_found_reports_its_version(monkeypatch):
    from tableau_public_authoring.desktop import tableau_app

    monkeypatch.setattr(tableau_app, "find_app", lambda: "/Applications/T.app")
    monkeypatch.setattr(tableau_app, "app_version", lambda _p: "2026.2.0")
    c = doctor._check_tableau()
    assert c.state == doctor.OK
    assert "2026.2.0" in c.detail


def test_accessibility_denied_names_the_interpreter_to_grant(monkeypatch):
    """Permissions are per-executable, so a generic instruction is useless."""
    from tableau_public_authoring.desktop import tableau_app

    monkeypatch.setattr(tableau_app, "check_accessibility", lambda: False)
    c = doctor._check_accessibility()
    assert c.state == doctor.FAIL
    assert sys.executable in c.fix
    assert "not to Tableau" in c.fix


def test_screen_recording_denied_when_the_capture_is_empty(monkeypatch, tmp_path):
    """A denied process still gets a successful screencapture call.

    The image is simply blank, which is why this probes the bytes rather than
    trusting the exit code -- and why a silent failure here produces blank
    validation screenshots rather than an error.
    """
    monkeypatch.setattr(doctor.shutil, "which", lambda _n: "/usr/sbin/screencapture")
    monkeypatch.setattr(doctor.subprocess, "run", lambda *a, **k: None)  # writes nothing
    c = doctor._check_screen_recording()
    assert c.state == doctor.FAIL
    assert sys.executable in c.fix


def test_screen_recording_ok_when_a_real_image_lands(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda _n: "/usr/sbin/screencapture")

    def fake_run(cmd, **_k):
        from pathlib import Path

        Path(cmd[-1]).write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 4096)

    monkeypatch.setattr(doctor.subprocess, "run", fake_run)
    assert doctor._check_screen_recording().state == doctor.OK


def test_non_macos_is_reported_as_unsupported(monkeypatch):
    monkeypatch.setattr(doctor.sys, "platform", "linux")
    c = doctor._check_platform()
    assert c.state == doctor.FAIL
    assert "no headless" in c.fix


# --- the report and the exit code -------------------------------------------


def test_exit_code_is_nonzero_when_something_blocks(monkeypatch, capsys):
    monkeypatch.setattr(
        doctor, "run", lambda: doctor.Report([doctor.Check("x", doctor.FAIL, "broken", "fix it")])
    )
    assert doctor.main([]) == 1
    out = capsys.readouterr().out
    assert "FAIL" in out and "fix it" in out


def test_exit_code_is_zero_when_everything_passes(monkeypatch, capsys):
    monkeypatch.setattr(
        doctor, "run", lambda: doctor.Report([doctor.Check("x", doctor.OK, "fine")])
    )
    assert doctor.main([]) == 0
    assert "ready to register" in capsys.readouterr().out


def test_a_warning_alone_does_not_block(monkeypatch, capsys):
    monkeypatch.setattr(
        doctor, "run", lambda: doctor.Report([doctor.Check("x", doctor.WARN, "odd")])
    )
    assert doctor.main([]) == 0
    assert "with caveats" in capsys.readouterr().out


def test_every_failure_carries_a_remediation():
    """A check that says "broken" without saying what to do wastes the user's time."""
    for check in doctor.run().checks:
        if check.state == doctor.FAIL:
            assert check.fix, f"{check.name} fails with no remediation"


def test_run_covers_the_conditions_that_fail_silently():
    names = {c.name for c in doctor.run().checks}
    for essential in ("tableauhyperapi", "mcp sdk", "python", "platform"):
        assert essential in names
    if sys.platform == "darwin":
        for essential in ("quartz (pyobjc)", "accessibility", "screen recording", "tableau public"):
            assert essential in names


# --- the CLI contract --------------------------------------------------------


def test_bare_invocation_still_starts_the_server(monkeypatch):
    """MCP clients invoke the entry point with NO arguments. That must not change."""
    from tableau_public_authoring import server

    started = {"yes": False}

    def fake_run(_coro):
        started["yes"] = True
        _coro.close()

    monkeypatch.setattr(sys, "argv", ["tableau-public-authoring"])
    monkeypatch.setattr("asyncio.run", fake_run)
    server.main()
    assert started["yes"], "a bare invocation must run the stdio server"


@pytest.mark.parametrize("flag", ["doctor", "--doctor", "check"])
def test_doctor_subcommand_is_reachable(monkeypatch, flag):
    from tableau_public_authoring import server

    monkeypatch.setattr(sys, "argv", ["tableau-public-authoring", flag])
    monkeypatch.setattr(doctor, "main", lambda _a: 0)
    with pytest.raises(SystemExit) as exc:
        server.main()
    assert exc.value.code == 0


def test_version_flag_does_not_start_a_server(monkeypatch, capsys):
    from tableau_public_authoring import server

    monkeypatch.setattr(sys, "argv", ["tableau-public-authoring", "--version"])
    with pytest.raises(SystemExit) as exc:
        server.main()
    assert exc.value.code == 0
    assert server.SERVER_VERSION in capsys.readouterr().out


def test_the_status_tool_carries_the_preflight(monkeypatch):
    """A model that hits a silent failure must be able to reach the cause in-band.

    Without this the only signal is a symptom ("no document window matching X")
    three layers from the actual problem, and nothing in the conversation can
    surface "Quartz is not installed".
    """
    import asyncio
    import json

    from tableau_public_authoring.server import _dispatch

    payload = json.loads(asyncio.run(_dispatch("get_tableau_public_app_status", {}))[0].text)
    assert payload["ok"] is True
    pf = payload["preflight"]
    assert set(pf) == {"ready", "checks", "blocking"}
    names = {c["name"] for c in pf["checks"]}
    assert "tableauhyperapi" in names and "python" in names
    assert isinstance(pf["ready"], bool)
