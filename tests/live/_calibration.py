"""Reproducible evidence for the blank-canvas thresholds in ``canvas.py``.

Run it:

    .venv/bin/python -m tests.live._calibration

It draws synthetic Tableau-shaped window captures — a blank canvas, a canvas with
only axis furniture, and canvases with a handful of marks — and reports what
``canvas.analyse_png`` measures on each. No Tableau, no GUI, no screenshots: this
is arithmetic, and it exists so that "0.0005 is the right floor" is a claim
anyone can re-check instead of a number someone once picked.

Measured on the shipped thresholds (MIN_INK_RATIO=0.0005, MIN_CHROMA_RATIO=0.0002):

    case                                   ink_ratio      chroma
    blank canvas                             0.00000     0.00000   <- the failure
    axis text only, no marks                 0.00683     0.00000
    6 marks, radius 10px @2x                 0.00783     0.00100
    6 marks, radius 26px @2x                 0.01356     0.00672

The gap between "blank" and everything else is total: a canvas that did not render
measures exactly zero, because the region is a flat white fill and PNG is lossless.
The floors sit roughly an order of magnitude below the sparsest real case, which
is the margin that keeps a slightly-differently-laid-out window from failing.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

from .canvas import MIN_CHROMA_RATIO, MIN_INK_RATIO, WORKSHEET_CANVAS, analyse_png

# A 1291x949 logical document window captured on a 2x display.
WIDTH, HEIGHT = 2582, 1898


def _blank_window() -> list[bytearray]:
    """White window with realistic chrome and an empty, gridlined canvas."""
    rows = [bytearray(b"\xff\xff\xff\xff" * WIDTH) for _ in range(HEIGHT)]

    def fill(x0: int, y0: int, x1: int, y1: int, rgb: tuple[int, int, int]) -> None:
        run = bytes(rgb) + b"\xff"
        for y in range(y0, y1):
            rows[y][x0 * 4 : x1 * 4] = run * (x1 - x0)

    fill(0, 0, WIDTH, 56, (60, 60, 60))  # title bar
    fill(0, 56, WIDTH, 140, (240, 240, 240))  # toolbar
    fill(0, 140, 460, HEIGHT, (246, 246, 246))  # data pane
    fill(460, 140, 780, HEIGHT, (250, 250, 250))  # pages/filters/marks strip
    fill(0, HEIGHT - 120, WIDTH, HEIGHT, (235, 235, 235))  # tabs + status bar
    for gy in range(300, HEIGHT - 140, 120):  # pale gridlines
        fill(800, gy, WIDTH - 40, gy + 2, (221, 221, 221))
    return rows


def _add_axis_text(rows: list[bytearray], count: int = 8) -> None:
    """Black tick labels: chrome that draws even when the marks do not."""
    y = int(HEIGHT * 0.85)
    for i in range(count):
        x = 900 + i * 180
        for dy in range(0, 22, 2):
            for dx in range(0, 70, 2):
                rows[y + dy][(x + dx) * 4 : (x + dx) * 4 + 3] = b"\x28\x28\x28"


def _add_marks(rows: list[bytearray], n: int, radius: int) -> None:
    """Filled circles in Tableau's default mark blue (#4E79A7)."""
    blue = bytes((78, 121, 167))
    for i in range(n):
        cx = 900 + (i % 6) * 260
        cy = 700 + (i // 6) * 300
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dx * dx + dy * dy <= radius * radius:
                    px, py = cx + dx, cy + dy
                    rows[py][px * 4 : px * 4 + 3] = blue


def _write_png(path: Path, rows: list[bytearray]) -> Path:
    raw = b"".join(b"\x00" + bytes(r) for r in rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 1))
    png += chunk(b"IEND", b"")
    path.write_bytes(png)
    return path


def main() -> None:
    import tempfile

    out = Path(tempfile.mkdtemp(prefix="canvas-calibration-"))
    cases: list[tuple[str, list[bytearray]]] = []

    rows = _blank_window()
    cases.append(("blank canvas", rows))

    rows = _blank_window()
    _add_axis_text(rows)
    cases.append(("axis text only, no marks", rows))

    for radius in (10, 26):
        rows = _blank_window()
        _add_axis_text(rows)
        _add_marks(rows, 6, radius)
        cases.append((f"6 marks, radius {radius}px @2x", rows))

    print(f"floors: ink >= {MIN_INK_RATIO:.5f}   colour >= {MIN_CHROMA_RATIO:.5f}")
    print(f"{'case':32} {'ink_ratio':>10} {'chroma':>10}   verdict")
    for label, pixels in cases:
        stats = analyse_png(
            _write_png(out / f"{label.replace(' ', '_')}.png", pixels), WORKSHEET_CANVAS
        )
        verdict = "BLANK" if stats.looks_blank else "rendered"
        colour = "colour" if stats.chroma_ratio >= MIN_CHROMA_RATIO else "no colour"
        print(
            f"{label:32} {stats.ink_ratio:10.5f} {stats.chroma_ratio:10.5f}   {verdict:8} {colour}"
        )
    print(f"\nimages written to {out}")


if __name__ == "__main__":
    main()
