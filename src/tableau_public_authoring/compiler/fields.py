"""CSV field inference and Tableau type mapping."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from ..security.paths import MAX_CSV_COLUMNS, MAX_CSV_ROWS, PathSecurityError

# Tableau datatype -> (role, type) defaults
_ROLE_BY_DATATYPE = {
    "string": ("dimension", "nominal"),
    "boolean": ("dimension", "nominal"),
    "date": ("dimension", "ordinal"),
    "datetime": ("dimension", "ordinal"),
    "integer": ("measure", "quantitative"),
    "real": ("measure", "quantitative"),
}

VALID_DATATYPES = tuple(_ROLE_BY_DATATYPE)

_INT_RE = re.compile(r"^[+-]?\d+$")
_REAL_RE = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?")
_BOOL_VALUES = {"true", "false", "yes", "no"}

# Geographic role hints, matched case-insensitively against the column name.
_GEO_ROLES = {
    "latitude": "[Country].[Name]",
    "longitude": "[Country].[Name]",
}


@dataclass(frozen=True)
class Field:
    """A single inferred or declared column."""

    name: str
    datatype: str
    role: str
    type: str
    ordinal: int
    is_calculated: bool = False
    formula: str | None = None
    calc_name: str | None = None

    @property
    def bracketed(self) -> str:
        return f"[{self.name}]"

    @property
    def reference_name(self) -> str:
        """The name used in ``column-instance/@column`` references."""
        return f"[{self.calc_name}]" if self.is_calculated and self.calc_name else f"[{self.name}]"

    @property
    def is_measure(self) -> bool:
        return self.role == "measure"


def _infer_datatype(values: list[str]) -> str:
    """Infer a Tableau datatype from sample values. Empty strings are ignored."""
    seen = [v.strip() for v in values if v is not None and v.strip() != ""]
    if not seen:
        return "string"
    if all(_INT_RE.match(v) for v in seen):
        return "integer"
    if all(_REAL_RE.match(v) for v in seen):
        return "real"
    if all(_DATE_RE.match(v) for v in seen):
        return "date"
    if all(_DATETIME_RE.match(v) for v in seen):
        return "datetime"
    if all(v.lower() in _BOOL_VALUES for v in seen):
        return "boolean"
    return "string"


def role_and_type(datatype: str) -> tuple[str, str]:
    if datatype not in _ROLE_BY_DATATYPE:
        raise ValueError(f"unsupported datatype {datatype!r}; expected one of {VALID_DATATYPES}")
    return _ROLE_BY_DATATYPE[datatype]


def geographic_role(field_name: str) -> str | None:
    return _GEO_ROLES.get(field_name.strip().lower())


def infer_fields(csv_path: Path, *, sample_rows: int = 500) -> list[Field]:
    """Read a CSV header plus a sample of rows and infer typed fields.

    Raises PathSecurityError for structurally unusable CSVs (T9).
    """
    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise PathSecurityError(f"CSV has no header row: {csv_path}") from exc

        header = [h.strip() for h in header]
        if not header or all(h == "" for h in header):
            raise PathSecurityError(f"CSV header row is empty: {csv_path}")
        if len(header) > MAX_CSV_COLUMNS:
            raise PathSecurityError(f"CSV has too many columns ({len(header)} > {MAX_CSV_COLUMNS})")

        seen_names: dict[str, int] = {}
        clean_header: list[str] = []
        for raw in header:
            name = raw or "Column"
            if name in seen_names:
                seen_names[name] += 1
                name = f"{name} {seen_names[name]}"
            else:
                seen_names[name] = 0
            clean_header.append(name)

        samples: list[list[str]] = [[] for _ in clean_header]
        row_count = 0
        for row in reader:
            row_count += 1
            if row_count > MAX_CSV_ROWS:
                raise PathSecurityError(f"CSV exceeds {MAX_CSV_ROWS} rows")
            if row_count <= sample_rows:
                for i in range(min(len(row), len(clean_header))):
                    samples[i].append(row[i])

    if row_count == 0:
        raise PathSecurityError(f"CSV contains a header but no data rows: {csv_path}")

    fields: list[Field] = []
    for ordinal, name in enumerate(clean_header):
        datatype = _infer_datatype(samples[ordinal])
        role, ftype = role_and_type(datatype)
        fields.append(Field(name=name, datatype=datatype, role=role, type=ftype, ordinal=ordinal))
    return fields
