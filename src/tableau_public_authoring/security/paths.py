"""Path safety helpers.

Mitigates T3 (path traversal) and T2 (ZIP slip) from docs/architecture/THREAT_MODEL.md.

**What this module is not.** An earlier version of this docstring said "every
filesystem path that originates from a tool argument passes through here". It
does not, and a reader would reasonably have taken that sentence as a guarantee
that nothing reaches the filesystem unchecked. ``open_in_tableau_public`` and
``validate_in_tableau_public`` in ``server.py`` build their target with a bare
``Path(args["path"]).expanduser()`` and never call in here. Treat this module as
the check that the *build* pipeline performs, not as a chokepoint for the server.

**Containment.** THREAT_MODEL.md lists "generation must not write outside allowed
roots" as an asset, but by default there is no allowlist: any readable ``.csv``
and any writable directory on the machine is accepted, and ``resolve_output_dir``
enforces a *blocklist* of places we refuse to write, which is a strictly weaker
thing. That default is deliberate — the tool's entire job is to read the user's
own data from wherever the user keeps it, and a hardcoded allowlist would make it
useless — but the consequence is concrete: a ``.csv`` that is a symlink onto
someone else's file is read without complaint and its contents are embedded in a
``.twbx`` that the publish flow may then make world-readable.

Callers who want the guarantee the threat model describes can set
``TABLEAU_MCP_ALLOWED_ROOTS`` to an ``os.pathsep``-separated list of directories.
When it is set, every input file and every output directory must resolve inside
one of them, and the comparison is against the **resolved** path, so a symlink
sitting inside an allowed root but pointing outside it is rejected.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

MAX_CSV_BYTES = 64 * 1024 * 1024  # 64 MB
MAX_CSV_ROWS = 200_000
MAX_CSV_COLUMNS = 256

#: ``os.pathsep``-separated directories that input files and output directories
#: must live inside. Unset (the default) means "no containment", which is what
#: this project shipped with; see the module docstring.
ALLOWED_ROOTS_ENV = "TABLEAU_MCP_ALLOWED_ROOTS"

# Absolute locations no generated artifact may be written into. These are
# prefixes, matched component-wise so "/usrX" is not treated as being under
# "/usr".
#
# "/etc" and "/private/etc" are both listed because resolve() rewrites the first
# into the second on macOS, and the check runs on the resolved path.
_FORBIDDEN_ABSOLUTE = (
    "/System",
    "/usr",
    "/bin",
    "/sbin",
    "/etc",
    "/private/etc",
    "/Library/LaunchDaemons",
    "/Library/LaunchAgents",
    "/Library/StartupItems",
)

# Persistence directories under the invoking user's home. These are the ones that
# matter most in practice: unlike /System they need no privilege at all, so an
# output directory of ~/Library/LaunchAgents was previously created and written
# to without a murmur. Dropping a file there is how unprivileged code on macOS
# arranges to be run again at login.
_FORBIDDEN_UNDER_HOME = (
    "Library/LaunchAgents",
    "Library/LaunchDaemons",
    "Library/StartupItems",
    "Library/Services",
    ".ssh",
    ".config/autostart",
)

# A Windows drive prefix in an archive entry: "C:\Windows\x" and also the
# drive-relative "C:x" form.
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


class PathSecurityError(ValueError):
    """Raised when a path fails a safety check. Message is safe to surface."""


def _allowed_roots() -> list[Path]:
    """Resolved contents of ``TABLEAU_MCP_ALLOWED_ROOTS``; empty means unrestricted.

    Read on every call rather than at import so the setting can be changed (and
    tested) without reloading the module.
    """
    raw = os.environ.get(ALLOWED_ROOTS_ENV, "")
    roots: list[Path] = []
    for chunk in raw.split(os.pathsep):
        chunk = chunk.strip()
        if chunk:
            roots.append(Path(chunk).expanduser().resolve(strict=False))
    return roots


def _assert_within_allowed_roots(resolved: Path, what: str) -> None:
    """Enforce the optional allowlist against an already-resolved path.

    The argument must be post-``resolve()``: comparing the literal path would
    accept a symlink that lives inside an allowed root and points anywhere at
    all, which is the exact case the allowlist exists to stop.
    """
    roots = _allowed_roots()
    if not roots:
        return
    for root in roots:
        if resolved == root or root in resolved.parents:
            return
    raise PathSecurityError(
        f"{what} resolves to {resolved}, which is outside every directory listed in "
        f"{ALLOWED_ROOTS_ENV} ({', '.join(str(r) for r in roots)})"
    )


def _is_under(prefix: str, target: str) -> bool:
    """Component-wise prefix test, case-insensitively.

    Case matters here, and getting it wrong made the blocklist decorative. The
    default macOS APFS volume is case-INsensitive — ``os.stat("/System").st_ino``
    and ``os.stat("/SYSTEM").st_ino`` are the same inode — so the old
    case-sensitive ``startswith`` rejected ``/System/Library/X`` while happily
    passing ``/system/library/X``, which names the identical directory.

    Case-folding over-blocks on a case-sensitive volume (a user's own ``/system``
    would be refused). That is the right way to be wrong for a blocklist.
    """
    p = prefix.casefold().rstrip("/")
    t = target.casefold()
    return t == p or t.startswith(p + "/")


def _forbidden_write_locations() -> list[str]:
    """Absolute paths ``resolve_output_dir`` refuses, including home-relative ones."""
    locations = list(_FORBIDDEN_ABSOLUTE)
    try:
        home = Path.home()
    except RuntimeError:  # pragma: no cover - no home directory configured
        return locations
    locations.extend(str(home / rel) for rel in _FORBIDDEN_UNDER_HOME)
    return locations


def resolve_input_file(
    raw: str,
    *,
    must_suffix: str | None = None,
    suffixes: tuple[str, ...] | None = None,
    max_bytes: int | None = None,
) -> Path:
    """Resolve an input file path, rejecting traversal and non-regular files.

    ``must_suffix`` accepts one extension, ``suffixes`` accepts several; either
    may be given. ``suffixes`` exists because ``server.py`` already calls this
    with ``suffixes=(".twbx",)``, which raised ``TypeError: unexpected keyword
    argument`` — ``inspect_local_workbook`` could not run at all.

    Symlinks are followed and the checks below apply to the target, but note that
    there is no root allowlist unless ``TABLEAU_MCP_ALLOWED_ROOTS`` is set: see
    the module docstring for what that does and does not buy you.
    """
    if not raw or not isinstance(raw, str):
        raise PathSecurityError("path must be a non-empty string")
    if "\x00" in raw:
        raise PathSecurityError("path contains a null byte")

    p = Path(raw).expanduser()
    if not p.is_absolute():
        raise PathSecurityError(f"path must be absolute, got: {raw!r}")

    if ".." in Path(raw).parts:
        raise PathSecurityError("path must not contain '..' segments")

    # resolve() collapses '..' and follows symlinks, so everything below —
    # including the allowlist — is asserted about the file that will actually be
    # opened, not about the name the caller typed.
    resolved = p.resolve(strict=False)

    if not resolved.exists():
        raise PathSecurityError(f"file does not exist: {resolved}")
    if not resolved.is_file():
        raise PathSecurityError(f"not a regular file: {resolved}")

    _assert_within_allowed_roots(resolved, "input file")

    accepted = tuple(s.lower() for s in (suffixes or ())) + (
        (must_suffix.lower(),) if must_suffix else ()
    )
    if accepted and resolved.suffix.lower() not in accepted:
        raise PathSecurityError(
            f"expected a {' or '.join(accepted)} file, got: {resolved.suffix or '(none)'}"
        )

    # MAX_CSV_BYTES is a CSV limit and makes no sense for a workbook: a .twbx
    # embeds every extract, so a legitimate one easily exceeds it and could not be
    # inspected or opened at all. Callers that handle a different kind of file
    # pass their own ceiling.
    limit = max_bytes if max_bytes is not None else MAX_CSV_BYTES
    size = resolved.stat().st_size
    if size > limit:
        raise PathSecurityError(f"file exceeds {limit} bytes: {size}")
    if size == 0:
        raise PathSecurityError(f"file is empty: {resolved}")

    return resolved


def resolve_output_dir(raw: str) -> Path:
    """Resolve (and create) an output directory, rejecting traversal.

    The blocklist runs **before** ``mkdir``, so a refused location is never
    created as a side effect of being refused.
    """
    if not raw or not isinstance(raw, str):
        raise PathSecurityError("output directory must be a non-empty string")
    if "\x00" in raw:
        raise PathSecurityError("path contains a null byte")

    p = Path(raw).expanduser()
    if not p.is_absolute():
        raise PathSecurityError(f"output directory must be absolute, got: {raw!r}")
    if ".." in Path(raw).parts:
        raise PathSecurityError("path must not contain '..' segments")

    resolved = p.resolve(strict=False)
    target = str(resolved)
    for forbidden in _forbidden_write_locations():
        if _is_under(forbidden, target):
            raise PathSecurityError(f"refusing to write into a system location: {resolved}")

    _assert_within_allowed_roots(resolved, "output directory")

    resolved.mkdir(parents=True, exist_ok=True)
    if not os.access(resolved, os.W_OK):
        raise PathSecurityError(f"output directory is not writable: {resolved}")
    return resolved


def safe_archive_name(name: str) -> str:
    """Validate an archive entry name (ZIP-slip guard, T2).

    Rejects POSIX **and** Windows traversal. On POSIX ``Path("..\\..\\evil").parts``
    is a single component — the backslashes are ordinary characters — so the
    ``".." in parts`` test called it safe, and so did the test for ``C:\\Windows\\x``.
    That mattered beyond packaging: this function is the general ZIP-slip guard,
    and ``inspect_twbx`` uses it to sort the entries of an **untrusted** archive
    into safe and unsafe. Reporting an entry as safe when any Windows unzipper
    would drop it two directories above the destination is a wrong answer about
    someone else's file, not just about ours.

    A backslash is therefore rejected outright rather than normalised. ZIP names
    use ``/``; nothing this project writes contains a backslash, so there is no
    legitimate entry to preserve, and rewriting a hostile name into a "clean" one
    is how these guards usually get bypassed.
    """
    if not name or name.startswith("/") or "\x00" in name:
        raise PathSecurityError(f"unsafe archive entry name: {name!r}")
    if "\\" in name:
        raise PathSecurityError(
            f"unsafe archive entry name (backslash is a path separator on Windows): {name!r}"
        )
    if _WINDOWS_DRIVE.match(name):
        raise PathSecurityError(f"unsafe archive entry name (Windows drive letter): {name!r}")
    parts = Path(name).parts
    if ".." in parts or any(p.startswith("/") for p in parts):
        raise PathSecurityError(f"unsafe archive entry name: {name!r}")
    if Path(name).is_absolute():
        raise PathSecurityError(f"archive entry must be relative: {name!r}")
    return name


def assert_within(root: Path, candidate: Path) -> Path:
    """Assert candidate resolves inside root (ZIP-slip guard for extraction)."""
    root_r = root.resolve()
    cand_r = candidate.resolve()
    if root_r != cand_r and root_r not in cand_r.parents:
        raise PathSecurityError(f"path escapes destination root: {candidate}")
    return cand_r


def contains_machine_identifiers(text: str) -> list[str]:
    """Return machine-identifying strings found in generated content (T6).

    Used pre-publish to guarantee no absolute paths or usernames leak into a
    world-readable artifact.
    """
    findings: list[str] = []
    user = os.environ.get("USER") or ""
    home = str(Path.home())
    if home and home in text:
        findings.append(f"home directory path ({home})")
    if user and len(user) > 2 and f"/{user}/" in text:
        findings.append(f"username in a path (/{user}/)")
    for marker in ("/Users/", "/private/tmp/", "/var/folders/"):
        if marker in text:
            findings.append(f"absolute path marker ({marker})")
    return sorted(set(findings))
