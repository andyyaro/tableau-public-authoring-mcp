"""Path safety helpers.

Mitigates T3 (path traversal) and T2 (ZIP slip) from docs/architecture/THREAT_MODEL.md.
Every filesystem path that originates from a tool argument passes through here.
"""

from __future__ import annotations

import os
from pathlib import Path

MAX_CSV_BYTES = 64 * 1024 * 1024  # 64 MB
MAX_CSV_ROWS = 200_000
MAX_CSV_COLUMNS = 256


class PathSecurityError(ValueError):
    """Raised when a path fails a safety check. Message is safe to surface."""


def resolve_input_file(raw: str, *, must_suffix: str | None = None) -> Path:
    """Resolve an input file path, rejecting traversal and non-regular files."""
    if not raw or not isinstance(raw, str):
        raise PathSecurityError("path must be a non-empty string")
    if "\x00" in raw:
        raise PathSecurityError("path contains a null byte")

    p = Path(raw).expanduser()
    if not p.is_absolute():
        raise PathSecurityError(f"path must be absolute, got: {raw!r}")

    # resolve() collapses '..' and follows symlinks; compare against the literal
    # form so we reject paths that only *look* contained.
    resolved = p.resolve(strict=False)
    if ".." in Path(raw).parts:
        raise PathSecurityError("path must not contain '..' segments")

    if not resolved.exists():
        raise PathSecurityError(f"file does not exist: {resolved}")
    if not resolved.is_file():
        raise PathSecurityError(f"not a regular file: {resolved}")

    if must_suffix and resolved.suffix.lower() != must_suffix.lower():
        raise PathSecurityError(
            f"expected a {must_suffix} file, got: {resolved.suffix or '(none)'}"
        )

    size = resolved.stat().st_size
    if size > MAX_CSV_BYTES:
        raise PathSecurityError(f"file exceeds {MAX_CSV_BYTES} bytes: {size}")
    if size == 0:
        raise PathSecurityError(f"file is empty: {resolved}")

    return resolved


def resolve_output_dir(raw: str) -> Path:
    """Resolve (and create) an output directory, rejecting traversal."""
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
    for forbidden in ("/System", "/usr", "/bin", "/sbin", "/Library/LaunchDaemons"):
        if str(resolved) == forbidden or str(resolved).startswith(forbidden + "/"):
            raise PathSecurityError(f"refusing to write into a system location: {resolved}")

    resolved.mkdir(parents=True, exist_ok=True)
    if not os.access(resolved, os.W_OK):
        raise PathSecurityError(f"output directory is not writable: {resolved}")
    return resolved


def safe_archive_name(name: str) -> str:
    """Validate an archive entry name (ZIP-slip guard, T2)."""
    if not name or name.startswith("/") or "\x00" in name:
        raise PathSecurityError(f"unsafe archive entry name: {name!r}")
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
