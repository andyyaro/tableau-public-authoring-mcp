"""``.twbx`` packaging.

A ``.twbx`` is a ZIP containing the ``.twb`` at the archive root plus referenced
data under ``Data/``. Packaging is deterministic: entries are written in a fixed
order with a fixed timestamp so identical specs produce identical bytes (§13
"reproducible packaging").
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from ..models.spec import WorkbookSpec
from ..security.paths import PathSecurityError, assert_within, safe_archive_name

# Fixed timestamp (1980-01-01) so packaging is byte-reproducible.
_FIXED_DATE = (1980, 1, 1, 0, 0, 0)

DATA_ROOT = "Data"


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


def package_twbx(
    spec: WorkbookSpec,
    twb_bytes: bytes,
    out_dir: Path,
    *,
    base_name: str,
    write_manifest: bool = True,
) -> PackageResult:
    """Write ``<base_name>.twb`` and ``<base_name>.twbx`` into ``out_dir``."""
    twb_name = f"{base_name}.twb"
    twb_path = out_dir / twb_name
    twb_path.write_bytes(twb_bytes)

    twbx_path = out_dir / f"{base_name}.twbx"
    entries: list[str] = []

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

    manifest_path = None
    if write_manifest:
        manifest_path = out_dir / f"{base_name}.manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "workbook_name": spec.name,
                    "spec_version": spec.spec_version,
                    "twb": twb_name,
                    "twbx": twbx_path.name,
                    "twbx_sha256": digest,
                    "entries": entries,
                    "data_sources": [
                        {"id": ds.id, "csv": ds.path.name, "fields": len(ds.fields)}
                        for ds in spec.data_sources
                    ],
                    "worksheets": [
                        {"name": w.name, "template": w.template} for w in spec.worksheets
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    return PackageResult(
        twb_path=twb_path,
        twbx_path=twbx_path,
        sha256=digest,
        entries=entries,
        manifest_path=manifest_path,
    )


def inspect_twbx(path: Path) -> dict:
    """Safely inspect an existing ``.twbx`` (ZIP-slip guarded, T2)."""
    if not zipfile.is_zipfile(path):
        raise PathSecurityError(f"not a zip archive: {path}")
    out: dict = {"path": str(path), "entries": [], "twb": None, "unsafe_entries": []}
    root = Path("/__pkg__")
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            try:
                safe_archive_name(name)
                assert_within(root, root / name)
            except PathSecurityError:
                out["unsafe_entries"].append(name)
                continue
            out["entries"].append(name)
            if name.lower().endswith(".twb") and "/" not in name:
                out["twb"] = name
    return out
