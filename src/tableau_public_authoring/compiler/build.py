"""End-to-end build pipeline: spec -> validated -> .twb -> .twbx."""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..models.spec import WorkbookSpec, parse_spec
from ..packaging.twbx import DATA_ROOT, PackageResult, package_twbx
from ..security.paths import contains_machine_identifiers
from ..validation.structure import validate_generated
from .extract import build_hyper
from .ids import datasource_name
from .workbook import WorkbookCompiler

_SAFE_BASENAME = re.compile(r"[^A-Za-z0-9._-]+")

# Where a bare .twb's data goes, relative to the .twb itself. A packaged build
# must use DATA_ROOT because that is the layout packaging.twbx writes into the
# archive and the SAME bytes are both zipped and left on disk. A bare build has
# no archive to match, so the sidecar is named after the workbook: two bare
# workbooks built into one output directory then cannot overwrite each other's
# extract, which a shared Data/<id>/ would let them do silently.
_BARE_DATA_SUFFIX = ".data"

# How much of a pre-existing file the overwrite guard will read back to decide
# whether we wrote it. Our own artifacts are bounded; slurping an arbitrarily
# large foreign file to answer a yes/no question is not worth it, and "too big to
# check" resolves to "not ours", which is the safe answer.
_PROBE_BYTES = 32 * 1024 * 1024


class OutputCollisionError(RuntimeError):
    """Raised when a build would overwrite a file it did not write itself."""


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
    # The directory the .twb's own connection strings point at. Reported because
    # the .twb is only openable while it sits next to it: moving the file alone
    # is the same broken artifact this field exists to document.
    data_dir: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "workbook_name": self.workbook_name,
            "twb_path": str(self.twb_path),
            "twbx_path": str(self.twbx_path) if self.twbx_path else None,
            "twbx_sha256": self.sha256,
            "data_dir": str(self.data_dir) if self.data_dir else None,
            "worksheets": self.worksheets,
            "package_entries": self.entries,
            "manifest_path": str(self.manifest_path) if self.manifest_path else None,
            "warnings": self.warnings,
        }


def safe_basename(name: str) -> str:
    """Workbook name -> output file base. **Not injective**: ``"My/Report"`` and
    ``"My Report"`` both become ``"My_Report"``, so two different workbooks can
    target the same files. That is what ``_is_prior_build`` exists to notice."""
    base = _SAFE_BASENAME.sub("_", name).strip("._-")
    return base or "workbook"


def _is_our_twb(data: bytes, ds_names: set[str]) -> bool:
    """True when ``data`` is workbook XML this server compiled for THIS spec.

    ``datasource_name()`` hashes the workbook name together with the data source
    id, so the ``federated.<hash>`` strings in a .twb identify which workbook
    produced it. That makes the test both a provenance check (no hand-authored
    workbook contains our hashes) and an identity check: the two names that
    collide on one file base compile to different hashes, so a build of
    ``"My Report"`` will not claim ownership of a build of ``"My/Report"``.
    """
    text = data.decode("utf-8", errors="replace")
    return "<workbook" in text and all(name in text for name in ds_names)


def _is_prior_build(path: Path, spec: WorkbookSpec, ds_names: set[str]) -> bool:
    """True when ``path`` is an artifact of an earlier build of this workbook.

    The size cap applies to what is READ, never to the container: a .twbx
    carrying a 60 MB extract is entirely ordinary, and capping the archive itself
    would disown our own package and make every rebuild of a real workbook demand
    ``overwrite``.
    """
    try:
        suffix = path.suffix.lower()
        if suffix in (".twb", ".json") and path.stat().st_size > _PROBE_BYTES:
            return False
        if suffix == ".twb":
            return _is_our_twb(path.read_bytes(), ds_names)
        if suffix == ".twbx":
            if not zipfile.is_zipfile(path):
                return False
            with zipfile.ZipFile(path) as zf:
                inner = [
                    i
                    for i in zf.infolist()
                    if i.filename.lower().endswith(".twb") and "/" not in i.filename
                ]
                if len(inner) != 1 or inner[0].file_size > _PROBE_BYTES:
                    return False
                return _is_our_twb(zf.read(inner[0]), ds_names)
        if suffix == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            return isinstance(payload, dict) and payload.get("workbook_name") == spec.name
    except (OSError, ValueError, zipfile.BadZipFile):
        # Unreadable, not a zip, not JSON: we cannot prove it is ours, so it is not.
        return False
    return False


def _check_output_collision(spec: WorkbookSpec, base: str, *, overwrite: bool) -> None:
    """Refuse to destroy files this pipeline did not write.

    ``build_workbook`` writes ``<base>.twb``, ``<base>.twbx`` (which packaging
    explicitly unlinks first) and ``<base>.manifest.json`` into any writable
    absolute directory the spec names, with no confirmation - while
    ``publish_to_tableau_public`` gates on ``confirm_publish``. The threat model
    protects the user's existing workbooks; ``output.directory`` pointed at a
    Tableau repository plus a colliding name is all it takes to lose one.

    The guard is provenance-based rather than a blanket prompt because this tool
    exists to write files and a rebuild is the normal loop. What the user can
    actually lose is a file we did not create; replacing our own previous output
    for the same workbook costs nothing (it is regenerable from the spec), so
    that case stays frictionless and everything else is refused.
    """
    if overwrite:
        return
    ds_names = {datasource_name(spec.name, ds.id) for ds in spec.data_sources}
    targets = [
        spec.output_dir / f"{base}.twb",
        spec.output_dir / f"{base}.twbx",
        spec.output_dir / f"{base}.manifest.json",
    ]
    foreign = [p for p in targets if p.exists() and not _is_prior_build(p, spec, ds_names)]
    if not foreign:
        return

    detail = ", ".join(p.name for p in sorted(foreign))
    message = (
        f"refusing to overwrite {detail} in {spec.output_dir}: not written by this server "
        f"for workbook {spec.name!r}, and building would destroy the contents."
    )
    # Name the collision when the directory can tell us about it: two workbook
    # names that sanitise alike is the confusing case, and "not written by this
    # server" is a misleading way to describe your own earlier build.
    manifest = spec.output_dir / f"{base}.manifest.json"
    if manifest.exists():
        prior = None
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = None
        if isinstance(payload, dict):
            prior = payload.get("workbook_name")
        if isinstance(prior, str) and prior != spec.name:
            message += (
                f" {manifest.name} records workbook {prior!r}: output names are sanitised, "
                f"so {prior!r} and {spec.name!r} both write {base!r}."
            )
    raise OutputCollisionError(
        message + " Choose a different output.directory or workbook.name, delete the file, "
        "or rebuild with overwrite=True."
    )


def build_workbook(raw_spec: dict[str, Any], *, overwrite: bool = False) -> BuildResult:
    """Validate a spec and compile it to ``.twb`` (+ ``.twbx``).

    Runs validation layers 1 and 2 (§14). Layers 3-5 require Tableau and live on
    the desktop/publishing modules.

    ``overwrite`` is the escape hatch for :func:`_check_output_collision`: it is
    only needed to replace a file this server did not write, never to rebuild the
    same workbook.
    """
    spec: WorkbookSpec = parse_spec(raw_spec)  # layer 1
    base = safe_basename(spec.name)

    # Before the first byte is written, exactly as packaging validates archive
    # names before writing (see packaging/twbx.py: a guard that runs after the
    # write is worse than no guard).
    _check_output_collision(spec, base, overwrite=overwrite)

    # Tableau Public only accepts extract-backed data sources, so every CSV is
    # materialised into a .hyper before compilation (see compiler/extract.py).
    #
    # The extract and the CSV are staged in the very directory the compiled XML
    # points at, because a .twb resolves data relative to ITSELF. Staging into a
    # hidden .extracts/ while emitting "Data/<id>/" is what made every generated
    # .twb unopenable on its own: the directory it named existed only inside the
    # .twbx. Inside the archive the layout must stay DATA_ROOT/<id>/ (packaging
    # writes those entries and the same .twb bytes are zipped and left on disk).
    data_root = DATA_ROOT if spec.package_twbx else f"{base}{_BARE_DATA_SUFFIX}"
    for ds in spec.data_sources:
        ds_dir = spec.output_dir / data_root / ds.id
        ds_dir.mkdir(parents=True, exist_ok=True)
        target = ds_dir / ds.hyper_name
        ds.row_count = build_hyper(ds.path, ds.fields, target)
        ds.hyper_path = target
        # The CSV is the extract's source connection. The .twbx carries a copy
        # for provenance; a bare .twb needs one on disk for the same reason.
        csv_copy = ds_dir / ds.path.name
        if csv_copy.resolve() != ds.path.resolve():
            shutil.copyfile(ds.path, csv_copy)

    compiler = WorkbookCompiler(spec)
    twb_bytes = compiler.to_bytes(data_dir_ref=data_root)

    warnings: list[str] = []
    leaks = contains_machine_identifiers(twb_bytes.decode("utf-8", errors="replace"))
    if leaks:
        raise RuntimeError(
            "generated workbook contains machine-identifying data, refusing to continue: "
            + ", ".join(leaks)
        )

    result: PackageResult = package_twbx(
        spec, twb_bytes, spec.output_dir, base_name=base, package=spec.package_twbx
    )

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
        data_dir=spec.output_dir / data_root,
    )
