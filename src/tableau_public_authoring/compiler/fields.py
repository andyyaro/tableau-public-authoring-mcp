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

# Geographic roles, matched case-insensitively against the whole column name.
#
# These values are not guesses. They are copied from a published workbook that
# renders a real map (docs/fixtures/REFERENCE_WORKBOOK_ANALYSIS.md):
#   <column aggregation="Avg" datatype="real" name="[Latitude]" role="measure"
#           semantic-role="[Geographical].[Latitude]" type="quantitative" />
# An earlier version of this table mapped BOTH latitude and longitude to
# "[Country].[Name]", which is the role for a country *name* column. It was never
# called by anything, so the error was invisible until maps were implemented.
#
# Whole-name matching only. A substring rule would claim "Longest Wait" as a
# longitude and silently produce a map of the Gulf of Guinea.
GEO_LATITUDE = "[Geographical].[Latitude]"
GEO_LONGITUDE = "[Geographical].[Longitude]"

_GEO_ROLES = {
    "latitude": GEO_LATITUDE,
    "lat": GEO_LATITUDE,
    "longitude": GEO_LONGITUDE,
    "long": GEO_LONGITUDE,
    "lon": GEO_LONGITUDE,
    "lng": GEO_LONGITUDE,
}

# Tableau averages a geographic coordinate rather than summing it: summing
# latitudes is meaningless, and a sheet that does it plots a single mark in the
# middle of the ocean.
GEO_AGGREGATION = "Avg"


def bracket(name: str) -> str:
    """Wrap an identifier in Tableau's ``[...]`` form, escaping any ``]``.

    Tableau escapes a closing bracket inside an identifier by **doubling** it.
    Without this, a CSV column called ``Val]ue`` compiles to ``[Val]ue]``, which
    Tableau's identifier grammar reads as the field ``Val`` followed by garbage.
    The XML stays well-formed and layer-2 validation still passes -- it compares
    the same corrupt string on both sides -- so the damage reaches Tableau
    silently. A header crafted as ``X]:nk].[sum:Other`` can make one column's
    shelf reference resolve to a *different* field.

    The compiler is immune to XML injection because it never concatenates markup
    (T1). Identifiers are a second, independent grammar nested inside attribute
    values, and this is its escape.
    """
    return f"[{name.replace(']', ']]')}]"


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
    semantic_role: str | None = None

    @property
    def bracketed(self) -> str:
        return bracket(self.name)

    @property
    def reference_name(self) -> str:
        """The name used in ``column-instance/@column`` references."""
        base = self.calc_name if self.is_calculated and self.calc_name else self.name
        return bracket(base)

    @property
    def is_measure(self) -> bool:
        return self.role == "measure"

    @property
    def is_geographic(self) -> bool:
        return bool(self.semantic_role)

    @property
    def is_coordinate(self) -> bool:
        """A latitude or longitude, i.e. a field that can go on a map's axes."""
        return self.semantic_role in (GEO_LATITUDE, GEO_LONGITUDE)

    @property
    def default_aggregation(self) -> str:
        """The aggregation Tableau applies when this field lands on a shelf."""
        return GEO_AGGREGATION if self.is_coordinate else "Sum"


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
        # A coordinate role is only claimed for a numeric column. A CSV whose
        # "Latitude" column holds text ("unknown", "n/a") is not a coordinate, and
        # tagging it as one produces a map that silently plots nothing.
        semantic = geographic_role(name) if datatype in ("real", "integer") else None
        fields.append(
            Field(
                name=name,
                datatype=datatype,
                role=role,
                type=ftype,
                ordinal=ordinal,
                semantic_role=semantic,
            )
        )
    return fields
