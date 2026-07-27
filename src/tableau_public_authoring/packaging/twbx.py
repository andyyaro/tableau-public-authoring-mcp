"""``.twbx`` packaging.

A ``.twbx`` is a ZIP containing the ``.twb`` at the archive root plus referenced
data under ``Data/``. Entries are written in a fixed order with a fixed timestamp,
so everything *this module* contributes is reproducible.

The archive as a whole is **not** byte-reproducible, and this docstring used to
claim it was. The embedded ``.hyper`` extract is written by Tableau's Hyper
engine, which records non-deterministic internal state, so two builds of an
identical spec produce different ``twbx_sha256`` values. The ``.twb`` inside is
byte-identical. A caller diffing the package digest across runs to detect a
changed spec will get a false positive every time; diff the ``.twb``.
"""

from __future__ import annotations

import hashlib
import json
import struct
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from ..models.spec import WorkbookSpec
from ..security.paths import PathSecurityError, assert_within, safe_archive_name

# Fixed timestamp (1980-01-01) so packaging is byte-reproducible.
_FIXED_DATE = (1980, 1, 1, 0, 0, 0)

DATA_ROOT = "Data"

# --- bounds for inspecting an UNTRUSTED archive -----------------------------
#
# inspect_twbx is the only function here that reads a file someone else wrote,
# and its result is serialised into a single MCP response. Every number below
# exists because the un-bounded version let the archive's author choose the size
# of that response.

#: Largest ``.twbx`` we will open at all. ZipFile() materialises the whole
#: central directory as ZipInfo objects during construction, so this is the only
#: bound available *before* any allocation happens.
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024

#: Largest number of entries we will accept. Checked against the end-of-central-
#: directory record before ZipFile() is constructed. A real ``.twbx`` has a
#: handful of entries; four thousand is already far past anything Tableau writes.
MAX_ARCHIVE_ENTRIES = 4096

#: Entries actually listed in the response. The hard cap above bounds memory;
#: this bounds the reply, which is a separate problem — 4096 names at the ZIP
#: format's 64 KB-per-name limit is a quarter-gigabyte of JSON.
MAX_REPORTED_ENTRIES = 512

#: Longest entry name reproduced in the response.
MAX_REPORTED_NAME_CHARS = 256

_EOCD_SIG = b"PK\x05\x06"
_EOCD_SIZE = 22
_ZIP64_LOCATOR_SIG = b"PK\x06\x07"
_ZIP64_EOCD_SIG = b"PK\x06\x06"


@dataclass
class PackageResult:
    twb_path: Path
    twbx_path: Path | None
    sha256: str
    entries: list[str] = field(default_factory=list)
    manifest_path: Path | None = None


def data_dir_for(ds_id: str) -> str:
    """Relative directory inside the package that holds a data source's CSV."""
    return f"{DATA_ROOT}/{ds_id}"


def _write_manifest(
    spec: WorkbookSpec,
    out_dir: Path,
    base_name: str,
    twb_name: str,
    twbx_name: str | None,
    digest: str,
    entries: list[str],
) -> Path:
    """Write the provenance record beside the workbook.

    ``twbx_name`` is None for a bare build, where ``digest`` is the hash of the
    ``.twb`` itself rather than of an archive.
    """
    manifest_path = out_dir / f"{base_name}.manifest.json"
    payload = {
        "workbook_name": spec.name,
        "spec_version": spec.spec_version,
        "twb": twb_name,
        "twbx": twbx_name,
        "twbx_sha256" if twbx_name else "twb_sha256": digest,
        "entries": entries,
        "data_sources": [
            {"id": ds.id, "csv": ds.path.name, "fields": len(ds.fields)}
            for ds in spec.data_sources
        ],
        "worksheets": [{"name": w.name, "template": w.template} for w in spec.worksheets],
    }
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def package_twbx(
    spec: WorkbookSpec,
    twb_bytes: bytes,
    out_dir: Path,
    *,
    base_name: str,
    write_manifest: bool = True,
    package: bool = True,
) -> PackageResult:
    """Write ``<base_name>.twb``, and ``<base_name>.twbx`` unless ``package`` is False.

    Every name is validated **before the first byte is written**. The guard used
    to run after ``write_bytes`` and ``unlink``, which made it worse than no
    guard at all: ``base_name="../victim"`` overwrote ``victim.twb`` one level
    up, deleted ``victim.twbx``, replaced it with an empty archive, and *then*
    raised PathSecurityError. The caller saw a clean exception and had no way to
    know two of its files were already gone.
    """
    twb_name = f"{base_name}.twb"
    # Validate first. safe_archive_name raises on traversal, absolute paths and
    # anything that would escape the destination.
    safe_archive_name(twb_name)
    for ds in spec.data_sources:
        safe_archive_name(f"{data_dir_for(ds.id)}/{ds.id}.hyper")

    twb_path = out_dir / twb_name
    twbx_path = out_dir / f"{base_name}.twbx"
    if twb_path.resolve().parent != out_dir.resolve():
        raise PathSecurityError(
            f"refusing to write outside the output directory: {twb_path} is not in {out_dir}"
        )

    twb_path.write_bytes(twb_bytes)
    entries: list[str] = []

    if not package:
        # output.package_twbx=False. This flag was parsed and then ignored for a
        # while, so a caller who opted out still got the archive.
        #
        # The manifest is still written. It is the provenance record for what was
        # generated, and a bare build needs that at least as much as a packaged
        # one: there is no archive to inspect afterwards.
        digest = hashlib.sha256(twb_bytes).hexdigest()
        manifest_path = (
            _write_manifest(spec, out_dir, base_name, twb_name, None, digest, [twb_name])
            if write_manifest
            else None
        )
        return PackageResult(
            twb_path=twb_path,
            twbx_path=None,
            sha256=digest,
            entries=[twb_name],
            manifest_path=manifest_path,
        )

    if twbx_path.exists():
        twbx_path.unlink()

    with zipfile.ZipFile(twbx_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        info = zipfile.ZipInfo(safe_archive_name(twb_name), date_time=_FIXED_DATE)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        zf.writestr(info, twb_bytes)
        entries.append(twb_name)

        for ds in spec.data_sources:
            # The .hyper extract is what Tableau Public actually reads. The source
            # CSV is packaged alongside it for provenance and re-generation.
            payloads: list[tuple[str, bytes]] = []
            if ds.hyper_path is not None and ds.hyper_path.exists():
                payloads.append(
                    (f"{data_dir_for(ds.id)}/{ds.hyper_name}", ds.hyper_path.read_bytes())
                )
            payloads.append((f"{data_dir_for(ds.id)}/{ds.path.name}", ds.path.read_bytes()))

            for arc_raw, payload in payloads:
                arc = safe_archive_name(arc_raw)
                di = zipfile.ZipInfo(arc, date_time=_FIXED_DATE)
                di.compress_type = zipfile.ZIP_DEFLATED
                di.external_attr = 0o644 << 16
                zf.writestr(di, payload)
                entries.append(arc)

    digest = hashlib.sha256(twbx_path.read_bytes()).hexdigest()

    manifest_path = (
        _write_manifest(spec, out_dir, base_name, twb_name, twbx_path.name, digest, entries)
        if write_manifest
        else None
    )

    return PackageResult(
        twb_path=twb_path,
        twbx_path=twbx_path,
        sha256=digest,
        entries=entries,
        manifest_path=manifest_path,
    )


def _central_directory_entry_count(path: Path) -> int | None:
    """Entry count from the end-of-central-directory record, or None if unreadable.

    Read by hand, from the tail of the file, because the count has to be known
    *before* ``zipfile.ZipFile(path)`` is constructed — that constructor is what
    walks the central directory and builds one ZipInfo per entry, so by the time
    a ZipFile object exists the allocation the cap is meant to prevent has
    already happened.

    Returns None when the record cannot be located or parsed; callers treat that
    as "refuse", since ``is_zipfile`` has already confirmed an EOCD is there and
    a file that is a zip for zipfile but not for us is exactly the kind of
    disagreement not to resolve in the archive's favour.
    """
    size = path.stat().st_size
    if size < _EOCD_SIZE:
        return None
    # EOCD is at most 22 bytes plus a comment of at most 0xFFFF bytes.
    tail_len = min(size, _EOCD_SIZE + 0xFFFF)
    with path.open("rb") as fh:
        fh.seek(size - tail_len)
        tail = fh.read(tail_len)

        # Search backwards: the signature can legally occur inside a file comment,
        # so a candidate only counts if its declared comment length matches the
        # bytes that actually follow it.
        idx = tail.rfind(_EOCD_SIG)
        while idx >= 0:
            if len(tail) - idx >= _EOCD_SIZE:
                comment_len = struct.unpack("<H", tail[idx + 20 : idx + 22])[0]
                if idx + _EOCD_SIZE + comment_len == len(tail):
                    break
            idx = tail.rfind(_EOCD_SIG, 0, idx)
        if idx < 0:
            return None

        count = struct.unpack("<H", tail[idx + 10 : idx + 12])[0]
        if count != 0xFFFF:
            return count

        # 0xFFFF means "see the zip64 record", reached through its locator.
        loc = tail.rfind(_ZIP64_LOCATOR_SIG, 0, idx)
        if loc < 0 or len(tail) - loc < 20:
            return None
        z64_offset = struct.unpack("<Q", tail[loc + 8 : loc + 16])[0]
        if z64_offset + 56 > size:
            return None
        fh.seek(z64_offset)
        head = fh.read(56)
    if len(head) < 56 or not head.startswith(_ZIP64_EOCD_SIG):
        return None
    return struct.unpack("<Q", head[32:40])[0]


def _clip(name: str) -> str:
    """Shorten an entry name for the response. ZIP allows 64 KB per name."""
    if len(name) <= MAX_REPORTED_NAME_CHARS:
        return name
    return name[:MAX_REPORTED_NAME_CHARS] + f"... ({len(name)} chars)"


def inspect_twbx(path: Path) -> dict:
    """Safely inspect an existing ``.twbx`` (ZIP-slip guarded, T2).

    The archive is untrusted and everything returned goes into one MCP response,
    so the size of that response must be ours to decide, not the archive
    author's. Previously it was not: there was no size check before
    ``ZipFile()`` and no cap on entry count, so ``namelist()`` and the returned
    ``entries`` list were as long as the crafted central directory said, and a
    file of a few megabytes could name millions of entries.
    """
    if not zipfile.is_zipfile(path):
        raise PathSecurityError(f"not a zip archive: {path}")

    size = path.stat().st_size
    if size > MAX_ARCHIVE_BYTES:
        raise PathSecurityError(
            f"archive exceeds {MAX_ARCHIVE_BYTES} bytes and will not be inspected: {size}"
        )

    count = _central_directory_entry_count(path)
    if count is None:
        raise PathSecurityError(f"could not read the archive's central directory: {path}")
    if count > MAX_ARCHIVE_ENTRIES:
        raise PathSecurityError(
            f"archive declares {count} entries, above the {MAX_ARCHIVE_ENTRIES} inspection "
            f"limit; a .twbx has a handful"
        )

    out: dict = {
        "path": str(path),
        "entries": [],
        "entry_count": count,
        "entries_truncated": False,
        "twb": None,
        "root_twb_entries": [],
        "unsafe_entries": [],
        "warnings": [],
    }
    root = Path("/__pkg__")
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()

    for name in names:
        try:
            safe_archive_name(name)
            assert_within(root, root / name)
        except PathSecurityError:
            if len(out["unsafe_entries"]) < MAX_REPORTED_ENTRIES:
                out["unsafe_entries"].append(_clip(name))
            continue
        if len(out["entries"]) < MAX_REPORTED_ENTRIES:
            out["entries"].append(_clip(name))
        else:
            out["entries_truncated"] = True
        if name.lower().endswith(".twb") and "/" not in name:
            out["root_twb_entries"].append(_clip(name))

    if out["entries_truncated"]:
        out["warnings"].append(
            f"listing truncated to the first {MAX_REPORTED_ENTRIES} safe entries of {count}"
        )

    # A .twbx has exactly one root-level .twb, and which one Tableau opens when
    # there are several is not something this function gets to decide. The loop
    # used to just overwrite `twb` each time, so the LAST match won silently —
    # a caller that then read that .twb was inspecting an attacker's choice of
    # document while a different one might be what Tableau loads.
    roots = out["root_twb_entries"]
    if len(roots) == 1:
        out["twb"] = roots[0]
    elif len(roots) > 1:
        out["warnings"].append(
            f"archive contains {len(roots)} root-level .twb entries {roots}; which one "
            f"Tableau treats as the workbook is ambiguous, so none is reported"
        )
    else:
        out["warnings"].append("archive contains no root-level .twb entry")

    return out
