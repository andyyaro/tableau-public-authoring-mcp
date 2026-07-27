"""Regression tests for the hardening pass on paths / packaging / validation / extract.

Every test here fails on the code as it stood before the corresponding fix. Where
a claim in a comment or docstring was the defect, the test pins the corrected
claim, because a false security claim is worse than none: it is what stops the
next reader from looking.

Nothing here touches the network. The extract tests spawn a real Hyper process,
which the suite already does.
"""

from __future__ import annotations

import tracemalloc
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

from tableau_public_authoring.compiler import extract as extract_mod
from tableau_public_authoring.compiler.build import build_workbook
from tableau_public_authoring.compiler.extract import _hyper_log_dir, build_hyper
from tableau_public_authoring.compiler.fields import infer_fields
from tableau_public_authoring.models.spec import parse_spec
from tableau_public_authoring.packaging import twbx as twbx_mod
from tableau_public_authoring.packaging.twbx import (
    MAX_ARCHIVE_ENTRIES,
    MAX_REPORTED_ENTRIES,
    inspect_twbx,
)
from tableau_public_authoring.security import paths as paths_mod
from tableau_public_authoring.security.paths import (
    ALLOWED_ROOTS_ENV,
    PathSecurityError,
    resolve_input_file,
    resolve_output_dir,
    safe_archive_name,
)
from tableau_public_authoring.validation.structure import validate_generated

from .conftest_helpers import make_spec, write_csv


@pytest.fixture(autouse=True)
def _no_ambient_allowlist(monkeypatch):
    """The allowlist is opt-in; never inherit one from the developer's shell."""
    monkeypatch.delenv(ALLOWED_ROOTS_ENV, raising=False)


# =========================================================================
# paths.py #1 — containment, and the claims made about it
# =========================================================================


def test_module_no_longer_claims_to_see_every_path():
    """The docstring promised a chokepoint that does not exist.

    ``server.py`` reaches the filesystem twice (``open_in_tableau_public``,
    ``validate_in_tableau_public``) with a bare ``Path(...).expanduser()`` and no
    call into this module, so "every filesystem path that originates from a tool
    argument passes through here" was false as written.
    """
    doc = paths_mod.__doc__ or ""
    assert "Every filesystem path that originates from a tool argument passes through here" not in doc
    assert ALLOWED_ROOTS_ENV in doc, "the docstring must point at the opt-in containment switch"


def test_no_containment_without_the_env_var(tmp_path):
    """Default behaviour is unchanged: any readable .csv is accepted."""
    csv = write_csv(tmp_path / "anywhere.csv")
    assert resolve_input_file(str(csv), must_suffix=".csv") == csv.resolve()


def test_allowed_roots_reject_an_input_outside_them(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = write_csv(tmp_path / "elsewhere.csv")
    monkeypatch.setenv(ALLOWED_ROOTS_ENV, str(allowed))

    with pytest.raises(PathSecurityError, match="outside every directory"):
        resolve_input_file(str(outside), must_suffix=".csv")


def test_allowed_roots_reject_a_symlink_that_escapes(tmp_path, monkeypatch):
    """The case the audit named: a .csv symlink onto somebody else's file.

    The link lives inside the allowed root, so a check against the *literal*
    path would pass it. The contents of whatever it points at get embedded in a
    .twbx that the publish flow can make world-readable, so the comparison has
    to be against the resolved target.
    """
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (tmp_path / "victims").mkdir()
    victim = write_csv(tmp_path / "victims" / "payroll.csv")
    link = allowed / "innocent.csv"
    link.symlink_to(victim)
    monkeypatch.setenv(ALLOWED_ROOTS_ENV, str(allowed))

    with pytest.raises(PathSecurityError, match="outside every directory"):
        resolve_input_file(str(link), must_suffix=".csv")


def test_allowed_roots_accept_a_contained_input(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    csv = write_csv(allowed / "mine.csv")
    monkeypatch.setenv(ALLOWED_ROOTS_ENV, str(allowed))
    assert resolve_input_file(str(csv), must_suffix=".csv") == csv.resolve()


def test_allowed_roots_reject_an_output_dir_outside_them(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setenv(ALLOWED_ROOTS_ENV, str(allowed))
    target = tmp_path / "elsewhere"

    with pytest.raises(PathSecurityError, match="outside every directory"):
        resolve_output_dir(str(target))
    assert not target.exists(), "a refused directory must not be created by being refused"


def test_resolve_input_file_accepts_a_suffixes_tuple(tmp_path):
    """``server.py`` already calls this as ``suffixes=(".twbx",)``.

    The parameter did not exist, so ``inspect_local_workbook`` raised
    ``TypeError: unexpected keyword argument 'suffixes'`` on every invocation —
    the tool could not run at all.
    """
    pkg = tmp_path / "book.twbx"
    with zipfile.ZipFile(pkg, "w") as zf:
        zf.writestr("book.twb", "<workbook/>")
    assert resolve_input_file(str(pkg), suffixes=(".twbx",)) == pkg.resolve()

    with pytest.raises(PathSecurityError, match="expected a .twbx file"):
        resolve_input_file(str(write_csv(tmp_path / "d.csv")), suffixes=(".twbx",))


# =========================================================================
# paths.py #2 — the write blocklist
# =========================================================================


def test_write_blocklist_is_case_insensitive():
    """``/system/library/X`` and ``/System/Library/X`` are the same directory.

    macOS's default APFS volume is case-insensitive
    (``os.stat("/System").st_ino == os.stat("/SYSTEM").st_ino``), so the
    case-sensitive blocklist rejected one spelling and passed the other straight
    into ``mkdir()``.
    """
    for spelling in ("/System/Library/Nope", "/system/library/Nope", "/SYSTEM/Library/Nope"):
        with pytest.raises(PathSecurityError, match="system location"):
            resolve_output_dir(spelling)


def test_write_blocklist_covers_user_writable_persistence_dirs(tmp_path, monkeypatch):
    """~/Library/LaunchAgents needs no privilege at all, and was not listed.

    HOME is redirected so the assertion is about the rule, not about this
    machine, and so a failing run cannot create the real directory.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    for rel in ("Library/LaunchAgents", "Library/StartupItems", ".ssh"):
        target = tmp_path / rel
        with pytest.raises(PathSecurityError, match="system location"):
            resolve_output_dir(str(target))
        assert not target.exists()

    # An ordinary directory under the same home is still fine.
    ok = tmp_path / "Documents" / "vizzes"
    assert resolve_output_dir(str(ok)) == ok.resolve()


# =========================================================================
# paths.py #3 — Windows traversal in archive entry names
# =========================================================================


@pytest.mark.parametrize(
    "name",
    [
        "..\\..\\evil",
        "..\\..\\..\\Users\\victim\\.ssh\\authorized_keys",
        "C:\\Windows\\system32\\x.csv",
        "C:/Windows/system32/x.csv",
        "C:relative.csv",
        "\\\\server\\share\\x.csv",
        "Data\\..\\..\\escape.csv",
    ],
)
def test_safe_archive_name_rejects_windows_traversal(name):
    """On POSIX these are single path components, so ``".." in parts`` said "safe".

    Extracted by any Windows unzipper they land outside the destination.
    """
    with pytest.raises(PathSecurityError):
        safe_archive_name(name)


def test_inspect_twbx_classifies_windows_traversal_as_unsafe(tmp_path):
    """The consequence of the above: inspect_twbx sorts UNTRUSTED entries."""
    pkg = tmp_path / "hostile.twbx"
    with zipfile.ZipFile(pkg, "w") as zf:
        zf.writestr("book.twb", "<workbook/>")
        zf.writestr("..\\..\\evil.twb", "x")
        zf.writestr("C:\\Windows\\system32\\evil.csv", "x")

    result = inspect_twbx(pkg)
    assert "..\\..\\evil.twb" in result["unsafe_entries"]
    assert "C:\\Windows\\system32\\evil.csv" in result["unsafe_entries"]
    assert result["entries"] == ["book.twb"]


# =========================================================================
# twbx.py #4 — bounds on inspecting an untrusted archive
# =========================================================================


def _zip_with_entries(path: Path, count: int, prefix: str = "Data/e") -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as zf:
        for i in range(count):
            zf.writestr(f"{prefix}{i}.csv", b"")
    return path


def test_inspect_twbx_refuses_an_absurd_entry_count(tmp_path):
    """The entry count is the archive author's choice; the response size is not.

    There was no cap, so ``namelist()`` and the returned list were as long as the
    crafted central directory, and the whole thing went into one MCP response.
    """
    pkg = _zip_with_entries(tmp_path / "many.twbx", MAX_ARCHIVE_ENTRIES + 1)
    with pytest.raises(PathSecurityError, match="above the .* inspection limit"):
        inspect_twbx(pkg)


def test_inspect_twbx_reads_the_entry_count_before_opening_the_zip(tmp_path, monkeypatch):
    """The cap has to bite before ``ZipFile()``, which is what allocates.

    ZipFile's constructor builds one ZipInfo per central-directory entry, so a
    check performed on an open ZipFile would already have paid the cost it is
    meant to avoid.
    """
    pkg = _zip_with_entries(tmp_path / "many.twbx", MAX_ARCHIVE_ENTRIES + 1)

    def _explode(*args, **kwargs):
        raise AssertionError("ZipFile must not be constructed for an over-sized archive")

    monkeypatch.setattr(twbx_mod.zipfile, "ZipFile", _explode)
    with pytest.raises(PathSecurityError, match="above the .* inspection limit"):
        inspect_twbx(pkg)


def test_inspect_twbx_truncates_a_long_but_legal_listing(tmp_path):
    n = MAX_REPORTED_ENTRIES + 50
    pkg = _zip_with_entries(tmp_path / "long.twbx", n)
    result = inspect_twbx(pkg)

    assert result["entry_count"] == n
    assert len(result["entries"]) == MAX_REPORTED_ENTRIES
    assert result["entries_truncated"] is True
    assert any("truncated" in w for w in result["warnings"])


def test_inspect_twbx_clips_an_enormous_entry_name(tmp_path):
    """ZIP allows 64 KB per name; the response should not."""
    pkg = tmp_path / "longname.twbx"
    long_name = "a" * 5000 + ".csv"
    with zipfile.ZipFile(pkg, "w") as zf:
        zf.writestr("book.twb", "<workbook/>")
        zf.writestr(long_name, b"")

    result = inspect_twbx(pkg)
    assert max(len(e) for e in result["entries"]) < 400


def test_inspect_twbx_reports_ambiguous_root_twb(tmp_path):
    """Two root-level .twb entries: the last one used to win, silently.

    A caller then inspected whichever document the archive listed last, which is
    the author's choice and need not be the one Tableau opens.
    """
    pkg = tmp_path / "two.twbx"
    with zipfile.ZipFile(pkg, "w") as zf:
        zf.writestr("real.twb", "<workbook/>")
        zf.writestr("decoy.twb", "<workbook/>")

    result = inspect_twbx(pkg)
    assert result["twb"] is None
    assert sorted(result["root_twb_entries"]) == ["decoy.twb", "real.twb"]
    assert any("ambiguous" in w for w in result["warnings"])


def test_inspect_twbx_still_reports_the_single_twb(tmp_path):
    pkg = tmp_path / "one.twbx"
    with zipfile.ZipFile(pkg, "w") as zf:
        zf.writestr("book.twb", "<workbook/>")
        zf.writestr("Data/d/d.csv", "A,B\n1,2\n")

    result = inspect_twbx(pkg)
    assert result["twb"] == "book.twb"
    assert result["unsafe_entries"] == []
    assert result["entries_truncated"] is False


def test_inspect_twbx_handles_a_zip_comment(tmp_path):
    """The hand-rolled end-of-central-directory scan must survive a trailing comment.

    The record is located by searching backwards for its signature, and a comment
    is what sits between it and the end of file. A candidate only counts if its
    declared comment length matches the bytes that actually follow, otherwise a
    comment containing the signature would win the search.
    """
    pkg = tmp_path / "commented.twbx"
    with zipfile.ZipFile(pkg, "w") as zf:
        zf.writestr("book.twb", "<workbook/>")
        zf.comment = b"x" * 4000

    assert inspect_twbx(pkg)["twb"] == "book.twb"
    assert inspect_twbx(pkg)["entry_count"] == 1


# =========================================================================
# structure.py #5 — the empty_worksheet check could never fire
# =========================================================================


def _blank_every_shelf(twb_path: Path, out_path: Path) -> Path:
    """Keep <rows>/<cols>/<encodings> but strip everything out of them."""
    tree = ET.parse(twb_path)
    for ws in tree.getroot().find("worksheets"):
        for tag in ("rows", "cols"):
            for el in ws.iter(tag):
                el.text = ""
        for enc in ws.iter("encodings"):
            for child in list(enc):
                enc.remove(child)
    tree.write(out_path, encoding="utf-8", xml_declaration=True)
    return out_path


def test_empty_worksheet_check_can_actually_fire(tmp_path):
    """The old test was for *presence* of the elements, which is unconditional.

    The compiler always emits <rows>, <cols> and <encodings>, so ``has_shelf``
    and ``has_enc`` were both always true and the safety net was dead code. The
    file below keeps all three elements and empties them — exactly the shape a
    compiler regression would produce.
    """
    csv = write_csv(tmp_path / "d.csv")
    out = tmp_path / "out"
    out.mkdir()
    raw = make_spec(csv, out)
    built = build_workbook(raw)
    spec = parse_spec(raw)

    stripped = _blank_every_shelf(built.twb_path, tmp_path / "stripped.twb")
    codes = [i.code for i in validate_generated(stripped, None, spec)]
    assert "empty_worksheet" in codes


def test_empty_worksheet_check_does_not_fire_on_a_real_build(tmp_path):
    """A rows-only text table ships <encodings /> and <cols />; it is not empty."""
    csv = write_csv(tmp_path / "d.csv")
    out = tmp_path / "out"
    out.mkdir()
    raw = make_spec(csv, out)
    raw["worksheets"] = [
        {
            "name": "Sheet One",
            "template": "text_table",
            "data_source": "d",
            "rows": ["Site"],
        }
    ]
    built = build_workbook(raw)
    codes = [i.code for i in validate_generated(built.twb_path, built.twbx_path, parse_spec(raw))]
    assert "empty_worksheet" not in codes


# =========================================================================
# structure.py #6 — the billion-laughs claim was false
# =========================================================================

_BOMB = """<?xml version="1.0"?>
<!DOCTYPE workbook [
<!ENTITY a "aaaaaaaaaa">
<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">
<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">
<!ENTITY d "&c;&c;&c;&c;&c;&c;&c;&c;&c;&c;">
<!ENTITY e "&d;&d;&d;&d;&d;&d;&d;&d;&d;&d;">
<!ENTITY f "&e;&e;&e;&e;&e;&e;&e;&e;&e;&e;">
]>
<workbook source-build='0' source-platform='mac' version='18.1'><x>&f;</x></workbook>
"""

_XXE = """<?xml version="1.0"?>
<!DOCTYPE workbook [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<workbook source-build='0' source-platform='mac' version='18.1'><x>&xxe;</x></workbook>
"""


@pytest.fixture
def any_spec(tmp_path):
    """A parsed spec, so validate_generated can be pointed at an arbitrary file."""
    csv = write_csv(tmp_path / "spec.csv")
    out = tmp_path / "spec-out"
    out.mkdir()
    return parse_spec(make_spec(csv, out))


def test_elementtree_really_does_expand_the_bomb(tmp_path):
    """Evidence for the claim correction, not a test of our code.

    The comment said ElementTree "does not expand external entities or resolve
    DTDs, so it is not vulnerable to XXE/billion-laughs". Internal entities are
    expanded: 343 bytes of file become a megabyte of string.
    """
    bomb = tmp_path / "bomb.xml"
    bomb.write_text(_BOMB, encoding="utf-8")
    assert bomb.stat().st_size < 500
    assert len(ET.parse(bomb).getroot().find("x").text) == 1_000_000  # noqa: S314


def test_validate_generated_refuses_a_billion_laughs_twb(tmp_path, any_spec):
    bomb = tmp_path / "bomb.twb"
    bomb.write_text(_BOMB, encoding="utf-8")

    issues = validate_generated(bomb, None, any_spec)
    assert [i.code for i in issues] == ["xml_unsafe"]
    assert "entity" in issues[0].message


def test_validate_generated_still_refuses_an_external_entity(tmp_path, any_spec):
    """The XXE half of the old claim was correct; keep it correct.

    ElementTree alone raises "undefined entity" rather than reading the file;
    now the declaration is refused one step earlier.
    """
    xxe = tmp_path / "xxe.twb"
    xxe.write_text(_XXE, encoding="utf-8")

    issues = validate_generated(xxe, None, any_spec)
    assert [i.code for i in issues] == ["xml_unsafe"]

    with pytest.raises(ET.ParseError, match="undefined entity"):
        ET.parse(xxe)  # noqa: S314


def test_validate_generated_still_parses_an_ordinary_workbook(tmp_path):
    """The entity pre-pass must not change the verdict on a real file."""
    csv = write_csv(tmp_path / "d.csv")
    out = tmp_path / "out"
    out.mkdir()
    raw = make_spec(csv, out)
    built = build_workbook(raw)
    issues = validate_generated(built.twb_path, built.twbx_path, parse_spec(raw))
    assert [i for i in issues if i.severity == "error"] == []


def test_validate_generated_reports_malformed_xml_as_before(tmp_path, any_spec):
    broken = tmp_path / "broken.twb"
    broken.write_text("<workbook><unclosed>", encoding="utf-8")
    assert [i.code for i in validate_generated(broken, None, any_spec)] == ["xml_malformed"]


# =========================================================================
# extract.py #7 — the row cap, and streaming instead of buffering
# =========================================================================


def test_build_hyper_enforces_the_row_cap(tmp_path, monkeypatch):
    """MAX_CSV_ROWS was declared in security/paths.py and enforced only in
    compiler/fields.py, which reads the CSV during *inference*. build_hyper
    re-opens the same path later, and had no limit of its own.
    """
    csv = tmp_path / "d.csv"
    csv.write_text("Site,Score\n" + "".join(f"s{i},{i}\n" for i in range(20)), encoding="utf-8")
    fields = infer_fields(csv)
    monkeypatch.setattr(extract_mod, "MAX_CSV_ROWS", 5)

    with pytest.raises(PathSecurityError, match="exceeds 5 rows"):
        build_hyper(csv, fields, tmp_path / "capped.hyper")


def test_build_hyper_does_not_buffer_the_whole_csv(tmp_path):
    """The old code built a ``list[list]`` of every row before inserting one.

    Measured on this CSV: buffering peaks around 10 MB of traced Python objects,
    streaming stays under 2 MB. At the 64 MB MAX_CSV_BYTES ceiling the buffered
    form is roughly a gigabyte of live objects.
    """
    rows = 40_000
    csv = tmp_path / "big.csv"
    with csv.open("w", encoding="utf-8") as fh:
        fh.write("Site,Score,Ratio\n")
        for i in range(rows):
            fh.write(f"site-{i},{i},{i * 1.5}\n")
    fields = infer_fields(csv)

    tracemalloc.start()
    try:
        count = build_hyper(csv, fields, tmp_path / "big.hyper")
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert count == rows
    assert peak < 5_000_000, f"peak traced memory {peak} suggests the rows are being buffered"


# =========================================================================
# extract.py #8 — hyperd's log
# =========================================================================


def test_hyperd_log_does_not_land_in_the_working_directory(tmp_path, monkeypatch):
    """hyperd defaults its log to the CWD of whoever started it.

    For an MCP server that is wherever the client launched it; this repository
    collected a 48 MB ``hyperd.log`` in its root, recording absolute paths.
    """
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)

    csv = write_csv(tmp_path / "d.csv")
    build_hyper(csv, infer_fields(csv), tmp_path / "d.hyper")

    assert list(work.iterdir()) == [], f"hyperd polluted the CWD: {list(work.iterdir())}"
    assert list(_hyper_log_dir().glob("hyperd*.log")), "the log should still exist, just elsewhere"
