"""Layer 2 validation — generated-file structural checks (§14)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path

from ..models.spec import WorkbookSpec
from ..security.paths import PathSecurityError, safe_archive_name


@dataclass
class Issue:
    severity: str  # "error" | "warning"
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "code": self.code, "message": self.message}


def validate_generated(
    twb_path: Path, twbx_path: Path | None, spec: WorkbookSpec
) -> list[Issue]:
    issues: list[Issue] = []

    # --- .twb is well-formed XML with the required skeleton ----------------
    try:
        root = ET.parse(twb_path).getroot()
    except ET.ParseError as exc:
        return [Issue("error", "xml_malformed", f".twb is not well-formed XML: {exc}")]

    if root.tag != "workbook":
        issues.append(Issue("error", "bad_root", f"root element is <{root.tag}>, expected <workbook>"))
    for attr in ("version", "source-build", "source-platform"):
        if not root.get(attr):
            issues.append(Issue("error", "missing_attr", f"workbook is missing @{attr}"))

    ds_nodes = root.find("datasources")
    ws_nodes = root.find("worksheets")
    if ds_nodes is None or not len(ds_nodes):
        issues.append(Issue("error", "no_datasources", "workbook contains no <datasource>"))
    if ws_nodes is None or not len(ws_nodes):
        issues.append(Issue("error", "no_worksheets", "workbook contains no <worksheet>"))

    if ds_nodes is not None and ws_nodes is not None:
        ds_names = {d.get("name") for d in ds_nodes}

        # worksheet names unique and matching the spec
        seen: set[str] = set()
        for w in ws_nodes:
            nm = w.get("name") or ""
            if nm in seen:
                issues.append(Issue("error", "dup_worksheet", f"duplicate worksheet name: {nm!r}"))
            seen.add(nm)

        expected = {w.name for w in spec.worksheets}
        if seen != expected:
            issues.append(
                Issue(
                    "error",
                    "worksheet_mismatch",
                    f"worksheets in file {sorted(seen)} do not match spec {sorted(expected)}",
                )
            )

        # every datasource reference resolves
        for w in ws_nodes:
            for dep in w.iter("datasource-dependencies"):
                ref = dep.get("datasource")
                if ref not in ds_names:
                    issues.append(
                        Issue(
                            "error",
                            "unresolved_datasource",
                            f"worksheet {w.get('name')!r} references unknown data source {ref!r}",
                        )
                    )

            # a publishable sheet must carry at least one encoding or shelf entry
            has_shelf = w.find(".//rows") is not None or w.find(".//cols") is not None
            has_enc = any(True for _ in w.iter("encodings"))
            if not (has_shelf or has_enc):
                issues.append(
                    Issue(
                        "error",
                        "empty_worksheet",
                        f"worksheet {w.get('name')!r} has no fields on any shelf; Tableau will "
                        f"not offer 'Save to Tableau Public' for a field-less viz",
                    )
                )

            # every column-instance must point at a declared column
            for dep in w.iter("datasource-dependencies"):
                declared = {c.get("name") for c in dep.findall("column")}
                for ci in dep.findall("column-instance"):
                    if ci.get("column") not in declared:
                        issues.append(
                            Issue(
                                "error",
                                "unresolved_column",
                                f"worksheet {w.get('name')!r}: column-instance references "
                                f"undeclared column {ci.get('column')!r}",
                            )
                        )

    # --- .twbx archive contents -------------------------------------------
    if twbx_path is not None:
        if not zipfile.is_zipfile(twbx_path):
            issues.append(Issue("error", "not_zip", f"{twbx_path.name} is not a valid ZIP archive"))
        else:
            with zipfile.ZipFile(twbx_path) as zf:
                names = zf.namelist()
            for n in names:
                try:
                    safe_archive_name(n)
                except PathSecurityError as exc:
                    issues.append(Issue("error", "unsafe_entry", str(exc)))

            twbs = [n for n in names if n.lower().endswith(".twb")]
            if len(twbs) != 1:
                issues.append(
                    Issue("error", "twb_count", f"expected exactly one .twb in package, found {len(twbs)}")
                )

            expected = {ds.path.name for ds in spec.data_sources}
            expected |= {ds.hyper_name for ds in spec.data_sources}
            found = {Path(n).name for n in names}
            missing = expected - found
            if missing:
                issues.append(
                    Issue("error", "missing_data", f"package is missing data files: {sorted(missing)}")
                )
            # Tableau Public requires every data source to be extract-backed.
            for ds in spec.data_sources:
                if ds.hyper_name not in found:
                    issues.append(
                        Issue(
                            "error",
                            "missing_extract",
                            f"data source {ds.id!r} has no .hyper extract in the package; "
                            f"Tableau Public rejects non-extract sources (Error 3C242D89)",
                        )
                    )

            unexpected = [
                n
                for n in names
                if not n.lower().endswith((".twb", ".csv", ".hyper"))
            ]
            if unexpected:
                issues.append(
                    Issue("warning", "unexpected_entry", f"unexpected package entries: {unexpected}")
                )

    return issues
