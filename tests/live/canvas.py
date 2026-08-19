"""Decide whether a Tableau window screenshot actually rendered anything.

WHY THIS EXISTS
---------------
Two of the defects found during development produced workbooks that Tableau
opened without a single complaint and then drew **nothing** into. "It opened" is
therefore not evidence that it works, and "no error dialog" is not either. The
only automatable evidence is the pixels.

HOW IT WORKS
------------
1. The window screenshot (``screencapture -x -o -l <window id>``) is decoded to
   straight RGBA8 with CoreGraphics/ImageIO.
2. A rectangle of the image is cropped to the *viz canvas* - right of the
   Marks/Filters card column, below the toolbar and shelves, above the sheet
   tabs. Everything excluded is chrome that Tableau draws whether or not the
   workbook rendered, so including it would make a blank canvas look busy.
3. Every sampled pixel is classified as **background** or **ink**:
      background = near-white or a pale, near-grey gridline
      ink        = anything else (marks, headers, axis labels, borders)
   Coloured ink is counted separately as ``chroma``, which is what distinguishes
   "marks were drawn" from "only black axis text was drawn".

NO IMAGE LIBRARY IS INSTALLED (no Pillow, no numpy) and none was added. Decoding
goes through ``Quartz`` (pyobjc), which the live tier already hard-requires:
``desktop.tableau_app.list_windows`` cannot enumerate a single window without it.

CALIBRATION
-----------
See ``MIN_INK_RATIO`` / ``MIN_CHROMA_RATIO`` below. Both are deliberately far
below what any real viz produces and far above what a blank canvas produces
(which is *zero*), because the measurement is a rendering smoke test, not a
pixel-perfect comparison. Every assertion prints the measured value so a
borderline result can be judged by a human instead of being a bare ``False``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# --- pixel classification ---------------------------------------------------
# Tableau's canvas is pure white (255,255,255); its gridlines and pane borders
# are pale, unsaturated greys in the #D0D0D0..#F0F0F0 range. A pixel counts as
# background when it is bright AND essentially colourless, which covers both.
BACKGROUND_MIN_CHANNEL = 200
BACKGROUND_MAX_CHROMA = 12

# A pixel is "coloured" when its channel spread is well past the grey range.
# Tableau's default mark blue (#4E79A7) has a spread of ~89; its orange, red and
# green palette entries are higher still. Black text and grey rules have a
# spread of ~0 and are excluded, which is the point.
CHROMA_MIN_SPREAD = 25

# --- thresholds -------------------------------------------------------------
# Both floors are measured, not guessed. ``_calibration.py`` in this package
# draws synthetic Tableau-shaped captures and reports what the code below
# measures on them; re-run it before touching either number:
#
#     .venv/bin/python -m tests.live._calibration
#
#     case                                   ink_ratio      chroma
#     blank canvas                             0.00000     0.00000  <- the failure
#     axis text only, no marks                 0.00683     0.00000
#     6 marks, radius 10px @2x                 0.00783     0.00100
#     6 marks, radius 26px @2x                 0.01356     0.00672
#
# Fraction of sampled canvas pixels that must carry ink. A canvas that failed to
# render measures *exactly zero*: the region is a flat white fill and PNG is
# lossless, so there is no noise floor to clear. The floor is set an order of
# magnitude below the sparsest case that has any content at all, which leaves
# room for a differently-proportioned window without ever admitting a blank one.
# Anything landing between zero and a real viz is genuinely ambiguous and wants a
# human, which is why every failure message prints the measurement and the path
# to the screenshot instead of just failing.
MIN_INK_RATIO = 0.0005

# Fraction of sampled canvas pixels that must be *coloured*, required for every
# template except text_table (whose marks are black text). The row above it in
# the table is the reason this exists: a canvas showing axis labels and headers
# and no marks measures 0.0068 ink - comfortably "not blank" - and 0.00000
# colour. Sparse marks still measure 5x this floor.
MIN_CHROMA_RATIO = 0.0002


@dataclass(frozen=True)
class CropBox:
    """A crop expressed as fractions of the image, so it survives Retina scaling
    and any window size. Fractions are measured from the top-left."""

    left: float
    top: float
    right: float
    bottom: float

    def pixels(self, width: int, height: int) -> tuple[int, int, int, int]:
        x0 = max(0, min(width - 1, int(width * self.left)))
        x1 = max(x0 + 1, min(width, int(width * self.right)))
        y0 = max(0, min(height - 1, int(height * self.top)))
        y1 = max(y0 + 1, min(height, int(height * self.bottom)))
        return x0, y0, x1, y1


# Where the viz lives inside a *worksheet* window, as a fraction of the window.
# Measured against Tableau Public 2026.2.0's document window (1291x949 logical):
#   * Data pane ~230px and the Pages/Filters/Marks strip ~160px sit on the left,
#     so the viz starts at roughly x=0.33 -> crop from 0.42 to stay clear of it;
#   * the title bar, toolbar and the Columns/Rows shelves occupy the top ~150px,
#     and the worksheet *title* is drawn immediately below them. The title
#     renders from static spec text even when no data reaches the canvas, so the
#     crop starts below it at 0.30 rather than counting it as evidence;
#   * the sheet-tab strip and status bar occupy the bottom ~60px -> stop at 0.88.
# The result is a rectangle that contains only pane content.
WORKSHEET_CANVAS = CropBox(left=0.42, top=0.30, right=0.97, bottom=0.88)

# A *dashboard* window has no shelves and no Marks card, so its canvas starts
# higher and further left; the left pane is the Dashboard/Objects list only. The
# top of the crop still skips the dashboard title zone (6000/100000 of the grid,
# i.e. 48px of an 800px canvas), for the same reason: a title that renders proves
# nothing about the worksheet zones underneath it.
DASHBOARD_CANVAS = CropBox(left=0.30, top=0.28, right=0.97, bottom=0.93)


class ImageDecodeError(RuntimeError):
    """The screenshot could not be decoded into pixels."""


@dataclass(frozen=True)
class Raster:
    """Straight (un-premultiplied over white) RGBA8 pixels, row-major, top-down."""

    width: int
    height: int
    stride: int
    data: bytes


def load_png(path: Path) -> Raster:
    """Decode a PNG to RGBA8 using CoreGraphics.

    The image is composited over opaque white before being read, which does two
    useful things: it removes the transparent rounded corners ``screencapture``
    leaves on a window capture (they would otherwise decode as pure black and
    read as ink), and it makes the result independent of the capture's alpha
    format. The source colour space (Display P3, sRGB, ...) is converted to
    device RGB by the same draw, so an HDR or wide-gamut display cannot change
    the classification.
    """
    try:
        import Quartz
    except ImportError as exc:  # pragma: no cover - environment guard
        raise ImageDecodeError(
            "Quartz (pyobjc) is required to decode screenshots; the live tier cannot run without it"
        ) from exc

    if not path.exists() or path.stat().st_size == 0:
        raise ImageDecodeError(f"screenshot is missing or empty: {path}")

    url = Quartz.CFURLCreateWithFileSystemPath(
        None, str(path.resolve()), Quartz.kCFURLPOSIXPathStyle, False
    )
    source = Quartz.CGImageSourceCreateWithURL(url, None)
    if source is None:
        raise ImageDecodeError(f"not a decodable image: {path}")
    image = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
    if image is None:
        raise ImageDecodeError(f"image contained no frame: {path}")

    width = int(Quartz.CGImageGetWidth(image))
    height = int(Quartz.CGImageGetHeight(image))
    if width <= 0 or height <= 0:
        raise ImageDecodeError(f"image has degenerate size {width}x{height}: {path}")

    stride = width * 4
    ctx = Quartz.CGBitmapContextCreate(
        None,
        width,
        height,
        8,
        stride,
        Quartz.CGColorSpaceCreateDeviceRGB(),
        Quartz.kCGImageAlphaPremultipliedLast,
    )
    if ctx is None:
        raise ImageDecodeError(f"could not create a bitmap context for {width}x{height}")
    Quartz.CGContextSetRGBFillColor(ctx, 1.0, 1.0, 1.0, 1.0)
    Quartz.CGContextFillRect(ctx, Quartz.CGRectMake(0, 0, width, height))
    Quartz.CGContextDrawImage(ctx, Quartz.CGRectMake(0, 0, width, height), image)

    raw = Quartz.CGBitmapContextGetData(ctx)
    if raw is None:
        raise ImageDecodeError("CGBitmapContextGetData returned nothing")
    return Raster(
        width=width, height=height, stride=stride, data=bytes(raw.as_buffer(height * stride))
    )


@dataclass(frozen=True)
class CanvasStats:
    """What was measured in the cropped canvas region."""

    image: Path
    width: int
    height: int
    crop: tuple[int, int, int, int]
    step: int
    sampled: int
    ink: int
    chroma: int
    distinct_colours: int

    @property
    def ink_ratio(self) -> float:
        return self.ink / self.sampled if self.sampled else 0.0

    @property
    def chroma_ratio(self) -> float:
        return self.chroma / self.sampled if self.sampled else 0.0

    @property
    def looks_blank(self) -> bool:
        return self.ink_ratio < MIN_INK_RATIO

    def describe(self) -> str:
        x0, y0, x1, y1 = self.crop
        return (
            f"image={self.image} ({self.width}x{self.height}px) "
            f"canvas crop=({x0},{y0})-({x1},{y1}) step={self.step} "
            f"sampled={self.sampled} "
            f"ink={self.ink} ({self.ink_ratio:.5f}, floor {MIN_INK_RATIO:.5f}) "
            f"coloured={self.chroma} ({self.chroma_ratio:.5f}, floor {MIN_CHROMA_RATIO:.5f}) "
            f"distinct_colours={self.distinct_colours}"
        )


def analyse(
    raster: Raster, crop: CropBox, *, image: Path, max_samples: int = 400_000
) -> CanvasStats:
    """Count ink in the cropped region of ``raster``.

    Sampling: a Retina window capture is ~2600x1900 and a full scan in pure
    Python costs a second or two *per screenshot*, and the render wait takes
    several. Pixels are therefore sampled on a regular lattice sized so that at
    most ``max_samples`` are examined. Ratios are unbiased under regular
    sampling, and the smallest feature that matters (a mark glyph, a glyph
    stroke) is several device pixels across, so nothing real is stepped over.
    """
    x0, y0, x1, y1 = crop.pixels(raster.width, raster.height)
    box_w, box_h = x1 - x0, y1 - y0
    total = box_w * box_h
    step = 1
    while (box_w // step) * (box_h // step) > max_samples:
        step += 1

    data = raster.data
    stride = raster.stride
    lo_bg = BACKGROUND_MIN_CHANNEL
    max_grey = BACKGROUND_MAX_CHROMA
    min_chroma = CHROMA_MIN_SPREAD

    sampled = 0
    ink = 0
    chroma = 0
    seen: set[int] = set()

    for y in range(y0, y1, step):
        base = y * stride
        for x in range(x0, x1, step):
            i = base + x * 4
            r = data[i]
            g = data[i + 1]
            b = data[i + 2]
            sampled += 1
            hi = r if r > g else g
            if b > hi:
                hi = b
            lo = r if r < g else g
            if b < lo:
                lo = b
            spread = hi - lo
            if lo >= lo_bg and spread <= max_grey:
                continue  # white canvas or a pale gridline
            ink += 1
            if spread >= min_chroma:
                chroma += 1
            if len(seen) < 4096:
                seen.add(((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4))

    return CanvasStats(
        image=image,
        width=raster.width,
        height=raster.height,
        crop=(x0, y0, x1, y1),
        step=step,
        sampled=sampled or total,
        ink=ink,
        chroma=chroma,
        distinct_colours=len(seen),
    )


def analyse_png(path: Path, crop: CropBox, *, max_samples: int = 400_000) -> CanvasStats:
    """Decode a screenshot and measure its canvas region."""
    return analyse(load_png(path), crop, image=path, max_samples=max_samples)
