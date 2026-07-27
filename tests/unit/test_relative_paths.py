"""Relative paths, and the containment that makes them safe to accept.

Accepting a relative path is only defensible because it is *contained*: it is
resolved against ``base_dir`` and then required to still be inside it, so it can
address nothing the spec author did not put there. An absolute path, by
contrast, may address anything on the machine.

That inverts the usual expectation, so it is worth stating plainly: **relative
paths here are the stricter of the two.** The tests below therefore spend most of
their effort on escape attempts, and on proving the check runs *after* symlinks
are resolved — a check on the literal string would pass every one of them.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Two exception types by design, and the distinction is user-visible:
# server.py reports SpecError as "specification error" and PathSecurityError as
# "path rejected". A malformed base_dir is a spec problem; a path that escapes
# is a path problem.
from tableau_public_authoring.models.spec import SpecError, parse_spec
from tableau_public_authoring.security.paths import (
    WORKSPACE_ENV,
    PathSecurityError,
    resolve_base_dir,
    resolve_input_file,
    resolve_output_dir,
)

CSV = "Site,Value\nA,1\nB,2\n"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    base = tmp_path / "workspace"
    (base / "data").mkdir(parents=True)
    (base / "data" / "sites.csv").write_text(CSV)
    (base / "out").mkdir()
    # A file the spec author never intended to expose, one level up.
    (tmp_path / "secret.csv").write_text("Secret,Value\nx,1\n")
    return base


def _spec(base: Path | None, csv: str, out: str) -> dict:
    spec: dict = {
        "spec_version": "0.1",
        "workbook": {"name": "RelCheck"},
        "data_sources": [{"id": "sites", "type": "csv", "path": csv}],
        "worksheets": [
            {
                "name": "S",
                "template": "bar",
                "data_source": "sites",
                "rows": ["Site"],
                "columns": [{"field": "Value", "aggregation": "Sum"}],
            }
        ],
        "output": {"directory": out},
    }
    if base is not None:
        spec["base_dir"] = str(base)
    return spec


# --- the ergonomic win -------------------------------------------------------


def test_a_spec_can_be_written_with_one_absolute_path(workspace):
    """The point of the feature: N absolute paths become one."""
    spec = parse_spec(_spec(workspace, "data/sites.csv", "out"))
    assert spec.data_sources[0].path == workspace / "data" / "sites.csv"
    assert spec.output_dir == workspace / "out"
    assert spec.base_dir == workspace


def test_absolute_paths_still_work_exactly_as_before(workspace):
    """No regression: an existing spec with absolute paths is unaffected."""
    spec = parse_spec(
        _spec(None, str(workspace / "data" / "sites.csv"), str(workspace / "out"))
    )
    assert spec.data_sources[0].path == workspace / "data" / "sites.csv"
    assert spec.base_dir is None


def test_absolute_paths_are_not_confined_to_base_dir(workspace, tmp_path):
    """An absolute path means what it says, even with a base_dir present.

    Confining it too would silently break specs that mix the two, and absolute
    paths were never contained before this feature existed.
    """
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "other.csv").write_text(CSV)
    spec = parse_spec(_spec(workspace, str(outside / "other.csv"), "out"))
    assert spec.data_sources[0].path == outside / "other.csv"


def test_the_workspace_env_var_supplies_a_default_base(workspace, monkeypatch):
    """Lets an operator make every spec relative-only, the strongest posture."""
    monkeypatch.setenv(WORKSPACE_ENV, str(workspace))
    spec = parse_spec(_spec(None, "data/sites.csv", "out"))
    assert spec.data_sources[0].path == workspace / "data" / "sites.csv"


# --- escape attempts ---------------------------------------------------------


def test_a_relative_path_cannot_climb_out_with_dotdot(workspace):
    with pytest.raises(PathSecurityError, match=r"\.\."):
        parse_spec(_spec(workspace, "../secret.csv", "out"))


def test_a_deeply_nested_climb_is_also_refused(workspace):
    with pytest.raises(PathSecurityError, match=r"\.\."):
        parse_spec(_spec(workspace, "data/../../secret.csv", "out"))


def test_a_symlink_inside_the_base_cannot_point_outside_it(workspace, tmp_path):
    """The check that a literal-string comparison would fail.

    The path contains no '..' and looks entirely well behaved; only resolving it
    reveals that it leaves the base.
    """
    (workspace / "data" / "sneaky.csv").symlink_to(tmp_path / "secret.csv")
    with pytest.raises(PathSecurityError, match="outside its base_dir"):
        parse_spec(_spec(workspace, "data/sneaky.csv", "out"))


def test_a_symlinked_directory_cannot_be_used_to_escape(workspace, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "other.csv").write_text(CSV)
    (workspace / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PathSecurityError, match="outside its base_dir"):
        parse_spec(_spec(workspace, "link/other.csv", "out"))


def test_a_relative_output_directory_cannot_escape(workspace, tmp_path):
    with pytest.raises(PathSecurityError, match=r"\.\."):
        parse_spec(_spec(workspace, "data/sites.csv", "../escaped"))


def test_an_escaping_output_directory_is_not_created_as_a_side_effect(workspace, tmp_path):
    """A refused location must not exist afterwards because it was refused."""
    (workspace / "link").symlink_to(tmp_path / "outside_target", target_is_directory=True)
    victim = tmp_path / "outside_target"
    with pytest.raises(PathSecurityError, match="outside its base_dir"):
        resolve_output_dir("link/made", base_dir=workspace)
    assert not victim.exists(), "the refused directory was created anyway"


# --- a relative path with no anchor -----------------------------------------


def test_a_relative_path_without_a_base_is_an_error_not_a_cwd_lookup(workspace, monkeypatch):
    """Never resolve against the process CWD.

    An MCP server inherits its working directory from whichever client launched
    it, so the same spec would address different files on different machines --
    and could read something the author never named.
    """
    monkeypatch.delenv(WORKSPACE_ENV, raising=False)
    monkeypatch.chdir(workspace)
    with pytest.raises(PathSecurityError, match="base_dir"):
        parse_spec(_spec(None, "data/sites.csv", str(workspace / "out")))


def test_that_error_names_all_three_ways_to_fix_it(workspace, monkeypatch):
    monkeypatch.delenv(WORKSPACE_ENV, raising=False)
    with pytest.raises(PathSecurityError) as exc:
        resolve_input_file("data/sites.csv", must_suffix=".csv")
    msg = str(exc.value)
    assert "absolute" in msg and "base_dir" in msg and WORKSPACE_ENV in msg


# --- base_dir itself ---------------------------------------------------------


def test_base_dir_must_be_absolute():
    with pytest.raises(PathSecurityError, match="must be absolute"):
        resolve_base_dir("relative/anchor")


def test_base_dir_must_exist(tmp_path):
    with pytest.raises(PathSecurityError, match="not an existing directory"):
        resolve_base_dir(str(tmp_path / "nope"))


def test_base_dir_must_be_a_directory_not_a_file(workspace):
    with pytest.raises(PathSecurityError, match="not an existing directory"):
        resolve_base_dir(str(workspace / "data" / "sites.csv"))


def test_a_bad_base_dir_is_reported_as_a_spec_error(workspace):
    """parse_spec's contract is SpecError; a raw PathSecurityError would leak."""
    with pytest.raises(SpecError, match="base_dir"):
        parse_spec(_spec(Path("not/absolute"), "data/sites.csv", "out"))


def test_base_dir_null_means_absent(workspace):
    raw = _spec(None, str(workspace / "data" / "sites.csv"), str(workspace / "out"))
    raw["base_dir"] = None
    assert parse_spec(raw).base_dir is None


def test_base_dir_must_be_a_string(workspace):
    raw = _spec(None, str(workspace / "data" / "sites.csv"), str(workspace / "out"))
    raw["base_dir"] = 42
    with pytest.raises(SpecError, match="must be a string"):
        parse_spec(raw)


# --- interaction with the existing allowlist --------------------------------


def test_the_allowed_roots_allowlist_still_applies_to_a_relative_path(workspace, monkeypatch):
    """base_dir containment is additional to the allowlist, never instead of it."""
    monkeypatch.setenv("TABLEAU_MCP_ALLOWED_ROOTS", str(workspace / "nowhere"))
    with pytest.raises(PathSecurityError, match="TABLEAU_MCP_ALLOWED_ROOTS"):
        resolve_input_file("data/sites.csv", must_suffix=".csv", base_dir=workspace)


def test_the_system_blocklist_still_applies(workspace):
    with pytest.raises(PathSecurityError, match="system location"):
        resolve_output_dir("/usr/local/tableau-mcp-should-not-exist")
    assert not os.path.exists("/usr/local/tableau-mcp-should-not-exist")


# --- end to end --------------------------------------------------------------


def test_a_relative_spec_builds_a_real_workbook(workspace):
    """The feature is only useful if a build actually completes through it."""
    from tableau_public_authoring.compiler.build import build_workbook

    result = build_workbook(_spec(workspace, "data/sites.csv", "out"))
    assert Path(result.twb_path).exists()
    assert Path(result.twb_path).parent == workspace / "out"
