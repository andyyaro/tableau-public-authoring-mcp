"""End-to-end build pipeline: spec -> validated -> .twb -> .twbx."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..models.spec import WorkbookSpec, parse_spec
from ..packaging.twbx import PackageResult, data_dir_for, package_twbx
from ..security.paths import contains_machine_identifiers
from ..validation.structure import validate_generated
from .extract import build_hyper
from .workbook import WorkbookCompiler

_SAFE_BASENAME = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass
class BuildResult:
    workbook_name: str
    twb_path: Path
    twbx_path: Path | None
    sha256: str
    worksheets: list[str]
    entries: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    manifest_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "workbook_name": self.workbook_name,
            "twb_path": str(self.twb_path),
            "twbx_path": str(self.twbx_path) if self.twbx_path else None,
            "twbx_sha256": self.sha256,
            "worksheets": self.worksheets,
            "package_entries": self.entries,
            "manifest_path": str(self.manifest_path) if self.manifest_path else None,
            "warnings": self.warnings,
        }


def safe_basename(name: str) -> str:
    base = _SAFE_BASENAME.sub("_", name).strip("._-")
    return base or "workbook"


def build_workbook(raw_spec: dict[str, Any]) -> BuildResult:
    """Validate a spec and compile it to ``.twb`` (+ ``.twbx``).

    Runs validation layers 1 and 2 (§14). Layers 3-5 require Tableau and live on
    the desktop/publishing modules.
    """
    spec: WorkbookSpec = parse_spec(raw_spec)  # layer 1

    # Tableau Public only accepts extract-backed data sources, so every CSV is
    # materialised into a .hyper before compilation (see compiler/extract.py).
    extract_dir = spec.output_dir / ".extracts"
    extract_dir.mkdir(parents=True, exist_ok=True)
    for ds in spec.data_sources:
        target = extract_dir / ds.hyper_name
        ds.row_count = build_hyper(ds.path, ds.fields, target)
        ds.hyper_path = target

    compiler = WorkbookCompiler(spec)

    # Inside a .twbx, data lives at Data/<ds_id>/. A workbook with a single data
    # source still uses the per-id directory so paths never collide.
    first_ds = spec.data_sources[0].id
    data_ref = data_dir_for(first_ds)
    twb_bytes = compiler.to_bytes(data_dir_ref=data_ref)

    warnings: list[str] = []
    leaks = contains_machine_identifiers(twb_bytes.decode("utf-8", errors="replace"))
    if leaks:
        raise RuntimeError(
            "generated workbook contains machine-identifying data, refusing to continue: "
            + ", ".join(leaks)
        )

    base = safe_basename(spec.name)
    result: PackageResult = package_twbx(spec, twb_bytes, spec.output_dir, base_name=base)

    issues = validate_generated(result.twb_path, result.twbx_path, spec)  # layer 2
    errors = [i for i in issues if i.severity == "error"]
    if errors:
        raise RuntimeError(
            "generated workbook failed structural validation: "
            + "; ".join(i.message for i in errors)
        )
    warnings.extend(i.message for i in issues if i.severity == "warning")

    return BuildResult(
        workbook_name=spec.name,
        twb_path=result.twb_path,
        twbx_path=result.twbx_path,
        sha256=result.sha256,
        worksheets=[w.name for w in spec.worksheets],
        entries=result.entries,
        warnings=warnings,
        manifest_path=result.manifest_path,
    )
