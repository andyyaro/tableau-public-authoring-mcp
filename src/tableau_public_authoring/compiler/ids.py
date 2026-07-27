"""Deterministic identifier generation.

Tableau uses opaque lowercase-alphanumeric identifiers such as
``federated.0suvv931dig9zi19tlvc60umhvkd``. Their exact derivation is internal to
Tableau and irrelevant to correctness: the only requirement is that identifiers
are unique within a workbook and referenced consistently.

We derive them from a SHA-256 of stable inputs so that the same specification
always compiles to a byte-identical workbook (required by §13 "deterministic
generated IDs" and tested by ``test_determinism``).
"""

from __future__ import annotations

import hashlib

_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"
_TABLEAU_ID_LEN = 28


def _base36(data: bytes, length: int) -> str:
    n = int.from_bytes(data, "big")
    out: list[str] = []
    while n and len(out) < length:
        n, rem = divmod(n, 36)
        out.append(_ALPHABET[rem])
    return "".join(out).ljust(length, "0")[:length]


def stable_id(*parts: str, prefix: str = "", length: int = _TABLEAU_ID_LEN) -> str:
    """Return a deterministic Tableau-style identifier derived from ``parts``."""
    payload = "\x1f".join(parts).encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    ident = _base36(digest, length)
    return f"{prefix}{ident}" if prefix else ident


def datasource_name(workbook_name: str, datasource_id: str) -> str:
    """``federated.<stable>`` — the workbook-level data source identifier."""
    return stable_id(workbook_name, datasource_id, "datasource", prefix="federated.")


def connection_name(workbook_name: str, datasource_id: str) -> str:
    """``textscan.<stable>`` — the named CSV connection inside a data source."""
    return stable_id(workbook_name, datasource_id, "connection", prefix="textscan.")


def calculation_name(workbook_name: str, datasource_id: str, field_name: str) -> str:
    """``[Calculation_<digits>]`` — Tableau's internal name for a calculated field.

    Tableau uses a numeric suffix; we derive a stable 16-digit value so repeated
    compilation of the same spec yields the same identifier.
    """
    payload = f"{workbook_name}\x1f{datasource_id}\x1f{field_name}".encode()
    digest = hashlib.sha256(payload).digest()
    number = int.from_bytes(digest[:8], "big") % (10**16)
    return f"Calculation_{number:016d}"


def object_id(table_name: str, workbook_name: str) -> str:
    """Uppercase hex object id used in ``<object-graph>``."""
    payload = f"{workbook_name}\x1f{table_name}".encode()
    return f"{table_name}_{hashlib.sha256(payload).hexdigest()[:32].upper()}"
