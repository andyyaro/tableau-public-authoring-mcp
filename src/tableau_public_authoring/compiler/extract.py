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

import tempfile
from pathlib import Path

from ..security.paths import MAX_CSV_ROWS, PathSecurityError
from .fields import Field

EXTRACT_SCHEMA = "Extract"
EXTRACT_TABLE = "Extract"


def _hyper_log_dir() -> Path:
    """Where hyperd writes its log.

    HyperProcess was started with no ``log_dir``, and hyperd's default is the
    **current working directory** of whoever started it. For an MCP server that
    is wherever the client happened to launch it: this repository accumulated a
    48 MB ``hyperd.log`` in its root that way. The log also records absolute
    paths of every database it touches, so it is exactly the machine-identifying
    material T6 exists to keep out of things the user might hand to someone else which is an
    argument against dropping it in the user's output directory
    too.

    A fixed directory under the OS temp dir keeps it off the repo, off the
    output, and findable when a Hyper failure needs diagnosing. ``log_config``
    is left at its default so that diagnostic survives.
    """
    d = Path(tempfile.gettempdir()) / "tableau-public-authoring" / "hyper-logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


# Bound hyperd's own log growth as well. Left unset, it rotates forever.
_HYPER_PARAMETERS = {
    "log_file_size_limit": "10M",
    "log_file_max_count": "2",
}


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

    Rows are streamed into the Inserter and counted against ``MAX_CSV_ROWS``.
    Neither used to be true here. ``MAX_CSV_ROWS`` was declared in
    ``security/paths.py`` and enforced only in ``compiler/fields.py``, which
    reads the CSV during *inference*; this function re-opens the same path later
    and had no limit of its own, so the cap depended on the file not having
    changed in between and on nobody calling ``build_hyper`` directly. And the
    entire CSV was accumulated into a ``list[list]`` before a single row was
    inserted, so a file at the 64 MB ``MAX_CSV_BYTES`` ceiling became on the
    order of a gigabyte of live Python objects - the tuples, the per-cell str,
    int, date objects, all of it resident at once.
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
        columns=[TableDefinition.Column(f.name, _sql_type(f.datatype)) for f in physical],
    )

    row_count = 0
    with HyperProcess(
        telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU,
        parameters={"log_dir": str(_hyper_log_dir()), **_HYPER_PARAMETERS},
    ) as hyper:
        with Connection(
            endpoint=hyper.endpoint,
            database=str(out_path),
            create_mode=CreateMode.CREATE_AND_REPLACE,
        ) as conn:
            conn.catalog.create_schema(EXTRACT_SCHEMA)
            conn.catalog.create_table(definition)
            with (
                csv_path.open("r", encoding="utf-8-sig", newline="") as fh,
                Inserter(conn, definition) as inserter,
            ):
                reader = _csv.reader(fh)
                next(reader, None)  # header already inferred
                for raw in reader:
                    # csv.reader yields [] for a blank line. Padding that to the
                    # column count produces a full row of NULLs, which reaches the
                    # extract, the <approx-count>, and every viz as a phantom null
                    # mark. A trailing newline at the end of a file is enough to
                    # trigger it.
                    if not any(cell.strip() for cell in raw):
                        continue
                    row_count += 1
                    if row_count > MAX_CSV_ROWS:
                        # Raised before execute(), so the half-built extract is
                        # never committed and out_path stays the empty table.
                        raise PathSecurityError(
                            f"CSV exceeds {MAX_CSV_ROWS} rows: {csv_path}"
                        )
                    padded = list(raw) + [""] * (len(physical) - len(raw))
                    inserter.add_row([_coerce(padded[f.ordinal], f.datatype) for f in physical])
                if row_count:
                    inserter.execute()

    if not out_path.exists() or out_path.stat().st_size == 0:
        raise ExtractError(f"hyper extract was not written: {out_path}")
    return row_count
