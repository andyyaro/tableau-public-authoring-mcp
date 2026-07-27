"""Hyper extract generation.

Tableau **Public** cannot save or publish a workbook backed by a live connection.
Verified empirically against Tableau Public 2026.2.0, which rejects a CSV-backed
workbook with:

    Workbooks saved to Tableau Public must use extracts.
    The data source, <id>, is not an extract.  (Error Code: 3C242D89)

Every data source therefore ships as a ``.hyper`` extract inside the ``.twbx``.
This is a Tableau Public product constraint, not an implementation choice.
"""

from __future__ import annotations

from pathlib import Path

from .fields import Field

EXTRACT_SCHEMA = "Extract"
EXTRACT_TABLE = "Extract"


class ExtractError(RuntimeError):
    """Raised when a Hyper extract cannot be produced."""


def _sql_type(datatype: str):
    from tableauhyperapi import SqlType

    return {
        "string": SqlType.text,
        "integer": SqlType.big_int,
        "real": SqlType.double,
        "boolean": SqlType.bool,
        "date": SqlType.date,
        "datetime": SqlType.timestamp,
    }.get(datatype, SqlType.text)()


def _coerce(value: str, datatype: str):
    """Convert a CSV cell into the Python type Hyper expects. '' -> None."""
    import datetime as _dt

    v = (value or "").strip()
    if v == "":
        return None
    try:
        if datatype == "integer":
            return int(v)
        if datatype == "real":
            return float(v)
        if datatype == "boolean":
            return v.lower() in ("true", "yes", "1")
        if datatype == "date":
            y, m, d = (int(x) for x in v.split("-"))
            return _dt.date(y, m, d)
        if datatype == "datetime":
            return _dt.datetime.fromisoformat(v.replace(" ", "T"))
    except (ValueError, TypeError):
        # A single unparseable cell must not abort the build; Tableau treats a
        # null the same way it would treat an unparseable value on import.
        return None
    return v


def build_hyper(csv_path: Path, fields: list[Field], out_path: Path) -> int:
    """Write ``out_path`` as a Hyper extract of ``csv_path``. Returns row count.

    Only physical (non-calculated) fields are materialised; calculated fields are
    evaluated by Tableau at query time from the workbook definition.
    """
    try:
        from tableauhyperapi import (
            Connection,
            CreateMode,
            HyperProcess,
            Inserter,
            SqlType,  # noqa: F401  (imported for _sql_type resolution)
            TableDefinition,
            TableName,
            Telemetry,
        )
    except ImportError as exc:  # pragma: no cover - environment guard
        raise ExtractError(
            "tableauhyperapi is required to build extracts (Tableau Public only "
            "accepts extract-backed workbooks). Install it with: uv pip install tableauhyperapi"
        ) from exc

    import csv as _csv

    physical = [f for f in fields if not f.is_calculated]
    if not physical:
        raise ExtractError("data source has no physical columns to extract")

    if out_path.exists():
        out_path.unlink()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    table = TableName(EXTRACT_SCHEMA, EXTRACT_TABLE)
    definition = TableDefinition(
        table_name=table,
        columns=[
            TableDefinition.Column(f.name, _sql_type(f.datatype)) for f in physical
        ],
    )

    rows: list[list] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = _csv.reader(fh)
        next(reader, None)  # header already inferred
        for raw in reader:
            padded = list(raw) + [""] * (len(physical) - len(raw))
            rows.append([_coerce(padded[f.ordinal], f.datatype) for f in physical])

    with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hyper:
        with Connection(
            endpoint=hyper.endpoint,
            database=str(out_path),
            create_mode=CreateMode.CREATE_AND_REPLACE,
        ) as conn:
            conn.catalog.create_schema(EXTRACT_SCHEMA)
            conn.catalog.create_table(definition)
            if rows:
                with Inserter(conn, definition) as inserter:
                    inserter.add_rows(rows)
                    inserter.execute()

    if not out_path.exists() or out_path.stat().st_size == 0:
        raise ExtractError(f"hyper extract was not written: {out_path}")
    return len(rows)
