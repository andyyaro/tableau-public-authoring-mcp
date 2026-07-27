"""Shared spec-building helper for tests."""

from __future__ import annotations

from pathlib import Path


def make_spec(csv: Path, out: Path, *, name: str = "Test Workbook", **overrides) -> dict:
    spec = {
        "spec_version": "0.1",
        "workbook": {"name": name, "description": "test"},
        "data_sources": [{"id": "d", "type": "csv", "path": str(csv)}],
        "worksheets": [
            {
                "name": "Sheet One",
                "template": "bar",
                "data_source": "d",
                "rows": ["Site"],
                "columns": [{"field": "Score", "aggregation": "Sum"}],
            }
        ],
        "output": {"directory": str(out), "package_twbx": True},
    }
    spec.update(overrides)
    return spec


def write_csv(path: Path, rows: int = 3) -> Path:
    lines = ["Site,Score,Status"]
    for i in range(rows):
        lines.append(f"Site {i},{i * 10 + 5},{'Ready' if i % 2 else 'Blocked'}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
