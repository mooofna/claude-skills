#!/usr/bin/env python3
"""Turn photos or scans of handwritten pages into clean, ordered page images.

Takes any mix of files and folders in common formats: JPEG, PNG, WebP, TIFF
(every page), BMP, GIF, AVIF, HEIC/HEIF and PDF (every page). For each page it
applies the camera's rotation, flattens transparency onto white, scales the
page to a size a vision model reads well and writes page-001.jpg,
page-002.jpg, ... plus manifest.json. It can also write all pages into one
archive PDF and split dense pages into overlapping top and bottom halves.

With --scan it works like a phone document scanner on photos: it finds the
sheet, flattens it to a straight rectangle and evens out the lighting (white
paper, dark ink, printed colour kept). Every detected outline is checked; when
the script is not confident, it keeps the whole photo and only fixes the
lighting, so nothing on the page is cut off. --clean fixes the lighting only.
PDF pages are already scans and are left as they are. The manifest notes say
what happened to each page.

Only Pillow is required. Optional extras unlock more:
  pillow-heif              HEIC/HEIF photos (iPhone default), AVIF on older Pillow builds
  pypdfium2                PDF input (falls back to the pdftoppm command from poppler)
  opencv-python-headless   --scan and --clean (together with numpy)
ImageMagick, if installed, is tried for anything Pillow cannot open.

Examples:
  prepare_pages.py ~/Downloads/IMG_*.HEIC -o /tmp/pages --scan --pdf "2026-10-10 Meeting.pdf"
  prepare_pages.py scans/ -o /tmp/pages --order name --split
  prepare_pages.py photo.jpg -o /tmp/pages --rotate 1:90
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

try:
    from PIL import ExifTags, Image, ImageOps
except ImportError:  # pragma: no cover
    sys.exit("Pillow is required: pip install pillow")

try:  # HEIC/HEIF, and AVIF where Pillow lacks it
    import pillow_heif

    pillow_heif.register_heif_opener()
    HAVE_HEIF = True
except ImportError:  # pragma: no cover - depends on the environment
    HAVE_HEIF = False

try:  # the document scanner (--scan, --clean)
    import cv2
    import numpy as np

    HAVE_CV = True
except ImportError:  # pragma: no cover - depends on the environment
    HAVE_CV = False

__version__ = "1.1.0"

Image.MAX_IMAGE_PIXELS = 400_000_000  # large phone photos and 600 dpi scans

SKIP_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}
EXIF_TIME_TAGS = ("DateTimeOriginal", "DateTimeDigitized", "DateTime")


@dataclass
class Page:
    source: Path
    page_in_source: int  # 1-based; above 1 only for PDFs and multi-page TIFFs
    image: Image.Image
    captured: datetime | None = None
    notes: list[str] = field(default_factory=list)
    focal: float | None = None  # camera focal length as a fraction of the photo's diagonal, from EXIF


def natural_key(text: str) -> list:
    """Sort 'IMG_2' before 'IMG_10'."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", text)]


def collect_inputs(inputs: list[str]) -> list[Path]:
    files: list[Path] = []
    for raw in inputs:
        path = Path(raw).expanduser()
        if path.is_dir():
            files.extend(sorted((p for p in path.rglob("*") if p.is_file()), key=lambda p: natural_key(str(p))))
        elif path.is_file():
            files.append(path)
        else:
            print(f"warning: not found, skipped: {raw}", file=sys.stderr)
    return [f for f in files if f.name.lower() not in SKIP_NAMES and not f.name.startswith(".")]


def exif_time(img: Image.Image) -> datetime | None:
    try:
        exif = img.getexif()
    except Exception:
        return None
    if not exif:
        return None
    tags = dict(exif)
    with contextlib.suppress(Exception):  # DateTimeOriginal sits in the Exif sub-IFD
        tags.update(exif.get_ifd(ExifTags.IFD.Exif))
    named = {ExifTags.TAGS.get(k, k): v for k, v in tags.items()}
    for tag in EXIF_TIME_TAGS:
        value = named.get(tag)
        if isinstance(value, bytes):
            value = value.decode(errors="ignore")
        if isinstance(value, str):
            try:
                return datetime.strptime(value.strip()[:19], "%Y:%m:%d %H:%M:%S")
            except ValueError:
                continue
    return None


def exif_focal(img: Image.Image) -> float | None:
    """Focal length relative to the image diagonal, from the 35 mm equivalent a phone records."""
    try:
        value = float(img.getexif().get_ifd(ExifTags.IFD.Exif).get(0xA405) or 0)  # FocalLengthIn35mmFilm
    except Exception:
        return None
    return value / 43.27 if 8 <= value <= 800 else None  # 43.27 mm: diagonal of a 35 mm frame


def to_rgb(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, "white")
        canvas.paste(rgba, mask=rgba.getchannel("A"))
        return canvas
    return img if img.mode == "RGB" else img.convert("RGB")


def open_image(path: Path) -> list[Page]:
    pages = []
    with Image.open(path) as img:
        captured = exif_time(img)
        focal = exif_focal(img)
        frames = getattr(img, "n_frames", 1)
        # A multi-page TIFF is a document; extra frames of a GIF or WebP are animation.
        count = frames if img.format == "TIFF" else 1
        for index in range(count):
            img.seek(index)
            frame = ImageOps.exif_transpose(img.copy())
            pages.append(Page(path, index + 1, to_rgb(frame), captured, focal=focal))
    return pages


def open_pdf(path: Path, dpi: int) -> list[Page]:
    try:
        import pypdfium2 as pdfium
    except ImportError:
        pdfium = None
    if pdfium is not None:
        pdf = pdfium.PdfDocument(str(path))
        try:
            return [Page(path, i + 1, to_rgb(pdf[i].render(scale=dpi / 72).to_pil())) for i in range(len(pdf))]
        finally:
            pdf.close()
    if shutil.which("pdftoppm"):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["pdftoppm", "-r", str(dpi), "-png", str(path), f"{tmp}/p"], check=True, capture_output=True)
            pages = []
            for i, png in enumerate(sorted(Path(tmp).glob("p*.png"), key=lambda p: natural_key(p.name))):
                with Image.open(png) as img:
                    pages.append(Page(path, i + 1, to_rgb(img.copy())))
            return pages
    raise RuntimeError(f"cannot read {path.name}: PDF input needs pypdfium2 (pip install pypdfium2) or pdftoppm")


def open_with_imagemagick(path: Path) -> list[Page]:
    tool = shutil.which("magick") or shutil.which("convert")
    if not tool:
        raise RuntimeError("ImageMagick not installed")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "page.png"
        subprocess.run([tool, f"{path}[0]", "-auto-orient", str(out)], check=True, capture_output=True)
        with Image.open(out) as img:
            return [Page(path, 1, to_rgb(img.copy()), notes=["decoded with ImageMagick"])]


def load(path: Path, dpi: int) -> list[Page]:
    if path.suffix.lower() == ".pdf":
        return open_pdf(path, dpi)
    try:
        return open_image(path)
    except Exception as error:
        try:
            return open_with_imagemagick(path)
        except Exception:
            hint = (
                " (install pillow-heif for HEIC/HEIF)"
                if path.suffix.lower() in {".heic", ".heif"} and not HAVE_HEIF
                else ""
            )
            raise RuntimeError(f"cannot read {path.name}{hint}: {error}") from None


def order_pages(pages: list[Page], mode: str) -> list[Page]:
    if mode == "given":
        return pages
    if mode == "name":
        return sorted(pages, key=lambda p: (natural_key(p.source.name), p.page_in_source))
    # capture: pages with a capture time first, oldest first; the rest after them by name
    return sorted(
        pages,
        key=lambda p: (p.captured is None, p.captured or datetime.min, natural_key(p.source.name), p.page_in_source),
    )


def parse_rotations(specs: list[str]) -> dict[int, int]:
    rotations = {}
    for spec in specs:
        try:
            page, degrees = spec.split(":")
            degrees_int = int(degrees) % 360
            if degrees_int not in (0, 90, 180, 270):
                raise ValueError
            rotations[int(page)] = degrees_int
        except ValueError:
            raise SystemExit(f"--rotate expects PAGE:DEGREES with 90, 180 or 270, got {spec!r}") from None
    return rotations


def fit(img: Image.Image, max_side: int) -> Image.Image:
    if max(img.size) <= max_side:
        return img
    out = img.copy()
    out.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return out


def split_halves(img: Image.Image, overlap: float = 0.08) -> list[Image.Image]:
    """Top and bottom half with a small overlap so no line is cut in two."""
    w, h = img.size
    pad = int(h * overlap / 2)
    return [img.crop((0, 0, w, min(h, h // 2 + pad))), img.crop((0, max(0, h // 2 - pad), w, h))]


# Document scanner (--scan, --clean), needs OpenCV and numpy.
#
# The sheet is searched on a small copy of the photo by several independent methods: a GrabCut segmentation
# seeded with the photo border as table and the centre as sheet, a colour model of the border, and closed
# edge contours. Every outline they propose goes through the same checks (shape, fit to its region, a colour
# step along every side, table colour just outside, no table inside), and the photo is only cropped when one
# passes all of them. The sides are then snapped to the paper's edge on a sharper copy and the crop is widened
# by a hair, so the paper's edge stays in the picture.

SCAN_WORK_SIDE = 512  # detection size, long side in pixels
SCAN_REFINE_SIDE = 1600  # edge snapping size
SCAN_MARGIN = 0.002  # extra room around the sheet, as a fraction of the photo's long side
GRABCUT_SECONDS = 3.0  # time budget for the segmentation of one photo


@dataclass
class Outline:
    corners: np.ndarray  # top-left, top-right, bottom-right, bottom-left
    method: str
    region: np.ndarray | None = None  # the segmented area the corners were fitted to
    area: float = 0.0  # fraction of the photo
    score: float = 0.0
    problems: list[str] = field(default_factory=list)


def order_corners(points) -> np.ndarray:
    """Top-left, top-right, bottom-right, bottom-left."""
    pts = np.asarray(points, np.float64).reshape(4, 2)
    center = pts.mean(axis=0)
    pts = pts[np.argsort(np.arctan2(pts[:, 1] - center[1], pts[:, 0] - center[0]))]
    return np.roll(pts, -int(np.argmin(pts.sum(axis=1))), axis=0)


def quad_sides(quad: np.ndarray) -> list[tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Start, end and outward unit normal of each side; side i runs from corner i to corner i + 1."""
    center = quad.mean(axis=0)
    sides = []
    for i in range(4):
        a, b = quad[i], quad[(i + 1) % 4]
        d = (b - a) / max(float(np.linalg.norm(b - a)), 1e-9)
        n = np.array([-d[1], d[0]])
        sides.append((a, b, n if n @ (a - center) >= 0 else -n))
    return sides


def corners_from_lines(lines: list[tuple[np.ndarray, float]]) -> np.ndarray | None:
    """Corner i is where line i - 1 meets line i; each line is (unit normal n, offset c) with n . x = c."""
    corners = []
    for (n1, c1), (n2, c2) in zip(lines[-1:] + lines[:-1], lines, strict=True):
        m = np.array([n1, n2])
        if abs(np.linalg.det(m)) < 1e-6:
            return None
        corners.append(np.linalg.solve(m, [c1, c2]))
    return np.array(corners)


def expand_quad(quad: np.ndarray, margin: float) -> np.ndarray:
    widened = corners_from_lines([(n, float(n @ a) + margin) for a, _, n in quad_sides(quad)])
    return quad if widened is None else widened


def sample(img: np.ndarray, pts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Nearest pixel values at the points, and which points lie inside the image."""
    h, w = img.shape[:2]
    valid = (pts[:, 0] >= 0) & (pts[:, 0] <= w - 1) & (pts[:, 1] >= 0) & (pts[:, 1] <= h - 1)
    x = np.clip(np.round(pts[:, 0]).astype(int), 0, w - 1)
    y = np.clip(np.round(pts[:, 1]).astype(int), 0, h - 1)
    return img[y, x], valid


def table_border(lab: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The photo's border strip, and the part of it that shows the table.

    Stretches whose colour stands out from the rest (a sheet or a hand reaching the edge) are left out, so
    they cannot pass for table."""
    h, w = lab.shape[:2]
    m = max(2, round(0.03 * min(h, w)))
    stretches = []
    for i in range(6):
        across, down = slice(w * i // 6, w * (i + 1) // 6), slice(h * i // 6, h * (i + 1) // 6)
        stretches += [(slice(0, m), across), (slice(h - m, h), across), (down, slice(0, m)), (down, slice(w - m, w))]
    medians = np.array([np.median(lab[part].reshape(-1, 3), axis=0) for part in stretches])
    distance = np.sqrt((((medians - np.median(medians, axis=0)) * (1.0, 2.0, 2.0)) ** 2).sum(axis=1))
    typical = distance < 30 if np.mean(distance < 30) >= 0.5 else np.ones(len(stretches), bool)
    strip, table = np.zeros((h, w), bool), np.zeros((h, w), bool)
    for part, keep in zip(stretches, typical, strict=True):
        strip[part] = True
        table[part] |= keep
    return strip, table


def table_likeness(lab: np.ndarray, border: np.ndarray) -> np.ndarray:
    """True where a colour is common along the photo's border, which is usually the table."""
    bins = np.array([8, 32, 32])
    idx = np.minimum((lab * (bins / 256.0)).astype(np.int32), bins - 1)
    flat = (idx[..., 0] * bins[1] + idx[..., 1]) * bins[2] + idx[..., 2]
    hist = np.bincount(flat[border], minlength=int(bins.prod())).astype(np.float32).reshape(tuple(bins))
    for i in range(len(hist)):
        hist[i] = cv2.GaussianBlur(hist[i], (0, 0), 0.8)
    likeness = hist.reshape(-1)[flat]
    return likeness >= max(float(np.quantile(likeness[border], 0.05)), 1e-6)


def filled_largest_region(mask: np.ndarray) -> np.ndarray | None:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=4)
    if count <= 1:
        return None
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    contours, _ = cv2.findContours((labels == largest).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    filled = np.zeros(mask.shape, np.uint8)
    cv2.drawContours(filled, contours, -1, 1, thickness=cv2.FILLED)
    return filled.astype(bool)


def quad_from_region(region: np.ndarray) -> np.ndarray | None:
    """Four corners around a region: sides fitted to its outline, then moved out until they enclose it."""
    contours, _ = cv2.findContours(region.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    hull = cv2.convexHull(contour)
    perimeter = cv2.arcLength(hull, True)
    rough = None
    for eps in np.linspace(0.005, 0.1, 40):
        poly = cv2.approxPolyDP(hull, eps * perimeter, True)
        if len(poly) <= 4:
            rough = poly if len(poly) == 4 else None
            break
    if rough is None:
        return None
    points = contour.reshape(-1, 2).astype(np.float64)
    lines = []
    for a, b, n in quad_sides(order_corners(rough)):
        length = float(np.linalg.norm(b - a))
        along = (points - a) @ ((b - a) / length)
        near = points[(along > 0.1 * length) & (along < 0.9 * length) & (np.abs((points - a) @ n) < 0.05 * length)]
        if len(near) < 10:
            return None
        vx, vy, x0, y0 = cv2.fitLine(near.astype(np.float32), cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
        normal = np.array([-vy, vx], np.float64)
        normal = normal if normal @ n >= 0 else -normal
        offset = float(normal @ (x0, y0))
        offset += max(0.0, float(np.quantile(near @ normal - offset, 0.98)))  # enclose the outline
        lines.append((normal, offset))
    corners = corners_from_lines(lines)
    return None if corners is None else order_corners(corners)


def grabcut_region(bgr: np.ndarray, strip: np.ndarray, border: np.ndarray) -> np.ndarray:
    """GrabCut foreground, seeded with the table along the photo border and with the centre as sheet."""
    h, w = border.shape
    mask = np.full((h, w), cv2.GC_PR_FGD, np.uint8)
    mask[strip] = cv2.GC_PR_BGD
    mask[border] = cv2.GC_BGD
    mask[int(h * 0.4) : int(h * 0.6), int(w * 0.4) : int(w * 0.6)] = cv2.GC_FGD
    bgd, fgd = np.zeros((1, 65)), np.zeros((1, 65))
    start = time.monotonic()
    cv2.grabCut(bgr, mask, None, bgd, fgd, 1, cv2.GC_INIT_WITH_MASK)
    for _ in range(4):
        if time.monotonic() - start > GRABCUT_SECONDS:
            break
        before = mask & 1
        cv2.grabCut(bgr, mask, None, bgd, fgd, 1, cv2.GC_EVAL)
        if np.mean((mask & 1) != before) < 0.002:
            break
    return (mask & 1).astype(bool)  # GC_FGD and GC_PR_FGD are odd


def edge_quads(lab: np.ndarray) -> list[np.ndarray]:
    """Closed colour-edge contours that simplify to four corners."""
    h, w = lab.shape[:2]
    vivid = lab.copy()
    vivid[..., 1:] = (vivid[..., 1:] - 128) * 3 + 128  # chroma counts more than brightness
    edges = cv2.Canny(np.clip(vivid, 0, 255).astype(np.uint8), 50, 130, L2gradient=True)
    k = max(3, round(min(h, w) * 0.006)) | 1
    edges = cv2.dilate(edges, np.ones((k, k), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    quads = []
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:8]:
        if cv2.contourArea(contour) < 0.1 * h * w:
            break
        hull = cv2.convexHull(contour)
        poly = cv2.approxPolyDP(hull, 0.02 * cv2.arcLength(hull, True), True)
        if len(poly) == 4:
            quads.append(order_corners(poly))
    return quads


def outline_candidates(
    bgr: np.ndarray, lab: np.ndarray, strip: np.ndarray, border: np.ndarray, table: np.ndarray
) -> list[Outline]:
    h, w = table.shape
    k = max(3, round(min(h, w) * 0.01)) | 1
    kernel = np.ones((k, k), np.uint8)
    regions = [("colour", cv2.morphologyEx((~table).astype(np.uint8), cv2.MORPH_CLOSE, kernel))]
    if table[int(h * 0.4) : int(h * 0.6), int(w * 0.4) : int(w * 0.6)].mean() < 0.5:
        # GrabCut needs the sheet under the centre seed; on bare table it is slow and finds nothing
        regions.append(("grabcut", grabcut_region(bgr, strip, border)))
    outlines = []
    for method, raw in regions:
        region = filled_largest_region(cv2.morphologyEx(raw.astype(np.uint8), cv2.MORPH_OPEN, kernel))
        quad = quad_from_region(region) if region is not None else None
        if quad is not None:
            outlines.append(Outline(quad, method, region))
    outlines.extend(Outline(quad, "edges") for quad in edge_quads(lab))
    return outlines


def check_outline(outline: Outline, lab: np.ndarray, table: np.ndarray, focal: float | None = None) -> Outline:
    """Record every reason not to trust the outline in outline.problems."""
    h, w = table.shape
    q = outline.corners
    problems = outline.problems
    outline.area = float(cv2.contourArea(q.astype(np.float32))) / (h * w)
    if not cv2.isContourConvex(q.astype(np.float32)):
        problems.append("not convex")
        return outline
    for i in range(4):
        u, v = q[i - 1] - q[i], q[(i + 1) % 4] - q[i]
        cos = float(u @ v) / max(float(np.linalg.norm(u) * np.linalg.norm(v)), 1e-9)
        if not 60 <= math.degrees(math.acos(min(1.0, max(-1.0, cos)))) <= 120:
            problems.append("corner angle")
            break
    sides = [float(np.linalg.norm(q[(i + 1) % 4] - q[i])) for i in range(4)]
    pairs = ((sides[0], sides[2]), (sides[1], sides[3]))
    if any(min(pair) < 0.55 * max(pair) for pair in pairs):  # a phone held more than about 35 degrees off
        problems.append("opposite sides differ")
    if not 0.12 <= outline.area <= 0.98:
        problems.append("size")
    ratio = page_aspect(q, w, h, focal)
    if max(ratio, 1 / ratio) > 1.9:
        problems.append("not paper-shaped")
    tol = 0.01 * max(h, w)
    if q.min() < -tol or q[:, 0].max() > w - 1 + tol or q[:, 1].max() > h - 1 + tol:
        problems.append("outside the photo")
    inside = np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(inside, np.round(q).astype(np.int32), 1)
    inside = inside.astype(bool)
    around = cv2.dilate(inside.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=max(2, round(0.03 * min(h, w))))
    rest = cv2.morphologyEx((~table & (around == 0)).astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(rest, connectivity=8)
    if count > 1 and stats[1:, cv2.CC_STAT_AREA].max() > 0.15 * np.count_nonzero(inside):
        problems.append("more paper outside")  # a second sheet, or the photo cuts through this one
    if outline.region is not None:
        overlap = np.count_nonzero(inside & outline.region)
        if overlap < 0.9 * np.count_nonzero(inside) or overlap < 0.97 * np.count_nonzero(outline.region):
            problems.append("does not fit the region")
    step = max(2.0, 0.008 * min(h, w))
    weights = np.array([1.0, 2.0, 2.0], np.float32)
    t = np.linspace(0.08, 0.92, 60)[:, None]
    edge, outside = [], []
    for a, b, n in quad_sides(q):
        line = a + t * (b - a)
        inner, _ = sample(lab, line - step * n)
        outer, _ = sample(lab, line + step * n)
        edge.append(float(np.mean(np.sqrt((((inner - outer) * weights) ** 2).sum(axis=1)) > 12)))
        far, valid = sample(table, line + 2.5 * step * n)
        outside.append(float(np.mean(far & valid)))  # beyond the photo's edge is unknown, not table
    interior = float(table[inside].mean()) if inside.any() else 1.0
    if min(edge) < 0.6:
        problems.append("weak edge")
    if min(outside) < 0.6:
        problems.append("no table outside")
    if interior > 0.5:
        problems.append("table inside")
    outline.score = float(np.mean(edge) + np.mean(outside) + 1 - interior)
    return outline


def refine_corners(rgb: np.ndarray, corners: np.ndarray) -> np.ndarray | None:
    """Snap each side to the straight line nearby along which the colour changes most consistently."""
    h, w = rgb.shape[:2]
    s = min(1.0, SCAN_REFINE_SIDE / max(h, w))
    img = cv2.resize(rgb, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else rgb
    lab = cv2.cvtColor(cv2.GaussianBlur(img, (0, 0), 1.2), cv2.COLOR_RGB2LAB).astype(np.float32)
    gx = cv2.Sobel(lab, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(lab, cv2.CV_32F, 0, 1, ksize=3)
    weights = np.array([1.0, 2.0, 2.0], np.float32)
    reach = max(3, round(0.012 * max(img.shape[:2])))
    offsets = np.arange(-reach, reach + 1, dtype=np.float32)
    d0, d1 = np.meshgrid(offsets, offsets, indexing="ij")  # shift of the side's start and end
    t = np.linspace(0.06, 0.94, 160, dtype=np.float32)
    shift = (d0[..., None] * (1 - t) + d1[..., None] * t).reshape(-1, len(t))
    lines = []
    for a, b, n in quad_sides(corners * s):
        px = (a[0] + t * (b[0] - a[0]) + shift * n[0]).astype(np.float32)
        py = (a[1] + t * (b[1] - a[1]) + shift * n[1]).astype(np.float32)
        across = (
            cv2.remap(gx, px, py, cv2.INTER_LINEAR) * n[0] + cv2.remap(gy, px, py, cv2.INTER_LINEAR) * n[1]
        ) * weights
        # along the paper's edge the colour changes the same way for long stretches; table texture averages out
        stretches = across.reshape(len(across), 8, -1, 3).mean(axis=2)
        score = np.sqrt((stretches**2).sum(axis=-1)).mean(axis=1)
        best = int(np.argmax(score))
        pa, pb = a + float(d0.flat[best]) * n, b + float(d1.flat[best]) * n
        e = (pb - pa) / float(np.linalg.norm(pb - pa))
        normal = np.array([-e[1], e[0]])
        lines.append((normal, float(normal @ pa)))
    refined = corners_from_lines(lines)
    return None if refined is None else order_corners(refined / s)


def page_aspect(corners: np.ndarray, frame_w: float, frame_h: float, focal: float | None = None) -> float:
    """Height / width of the real sheet, undoing perspective (Zhang and He, whiteboard scanning, 2007).

    `focal` is the camera's focal length as a fraction of the photo diagonal. Without it, it is measured from
    the outline when both pairs of sides clearly converge, else a phone's main camera is assumed."""
    tl, tr, br, bl = corners
    width = (np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) / 2
    height = (np.linalg.norm(bl - tl) + np.linalg.norm(br - tr)) / 2
    naive = float(height / max(width, 1e-9))
    m1, m2, m4, m3 = (np.array([x - frame_w / 2, y - frame_h / 2, 1.0]) for x, y in corners)
    den2, den3 = np.dot(np.cross(m2, m4), m3), np.dot(np.cross(m3, m4), m2)
    if abs(den2) < 1e-9 or abs(den3) < 1e-9:
        return naive
    n2 = np.dot(np.cross(m1, m4), m3) / den2 * m2 - m1
    n3 = np.dot(np.cross(m1, m4), m2) / den3 * m3 - m1
    diag = math.hypot(frame_w, frame_h)
    f2 = (focal * diag) ** 2 if focal else 0.0
    converging = min(abs(n[2]) / max(math.hypot(n[0], n[1]), 1e-9) for n in (n2, n3)) * diag
    if not f2 and converging > 0.15:
        f2 = -(n2[0] * n3[0] + n2[1] * n3[1]) / (n2[2] * n3[2])
    if not (0.3 * diag) ** 2 <= f2 <= (3 * diag) ** 2:
        f2 = (0.6 * diag) ** 2  # main camera of a phone, about 26 mm equivalent
    w2 = (n2[0] ** 2 + n2[1] ** 2) / f2 + n2[2] ** 2
    h2 = (n3[0] ** 2 + n3[1] ** 2) / f2 + n3[2] ** 2
    ratio = math.sqrt(h2 / w2) if w2 > 0 and h2 > 0 else naive
    return ratio if 0.75 <= ratio / naive <= 1.33 else naive


def find_outline(
    rgb: np.ndarray, focal: float | None = None
) -> tuple[np.ndarray | None, Outline | None, list[Outline]]:
    """The sheet's corners in photo pixels and the outline they came from, or None when not confident."""
    h, w = rgb.shape[:2]
    scale = min(1.0, SCAN_WORK_SIDE / max(h, w))
    small = cv2.resize(rgb, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_AREA)
    bgr = cv2.cvtColor(small, cv2.COLOR_RGB2BGR)
    lab = cv2.cvtColor(cv2.GaussianBlur(bgr, (0, 0), 1.0), cv2.COLOR_BGR2LAB).astype(np.float32)
    strip, border = table_border(lab)
    table = table_likeness(lab, border)
    outlines = [check_outline(o, lab, table, focal) for o in outline_candidates(bgr, lab, strip, border, table)]
    valid = [o for o in outlines if not o.problems]
    if not valid:
        return None, None, outlines
    top = max(o.score for o in valid)
    best = max((o for o in valid if o.score >= top - 0.1), key=lambda o: o.area)  # near tie: the larger one
    corners = best.corners / scale
    refined = refine_corners(rgb, corners)  # kept only if it stays close and passes the same checks
    close = refined is not None and np.abs(refined - corners).max() < 0.03 * max(h, w)
    if close and not check_outline(Outline(refined * scale, best.method), lab, table, focal).problems:
        corners = refined
    return corners, best, outlines


def warp_page(rgb: np.ndarray, corners: np.ndarray, max_side: int, focal: float | None = None) -> np.ndarray:
    h, w = rgb.shape[:2]
    ratio = page_aspect(corners, w, h, focal)
    longest = max(float(np.linalg.norm(corners[(i + 1) % 4] - corners[i])) for i in range(4))
    long_side = min(longest, max_side)
    out_w, out_h = (long_side / ratio, long_side) if ratio >= 1 else (long_side, long_side * ratio)
    out_w, out_h = max(1, round(out_w)), max(1, round(out_h))
    shrink = min(1.0, 1.25 * max(out_w, out_h) / longest)  # warpPerspective has no area filter
    if shrink < 1.0:
        rgb = cv2.resize(rgb, (round(w * shrink), round(h * shrink)), interpolation=cv2.INTER_AREA)
        corners = corners * shrink
    dst = np.float32([[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]])
    matrix = cv2.getPerspectiveTransform(corners.astype(np.float32), dst)
    return cv2.warpPerspective(rgb, matrix, (out_w, out_h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def normalise_lighting(rgb: np.ndarray, rim: float = 0.0) -> np.ndarray | None:
    """Divide out the light falling on the paper: paper turns white, ink and print keep their colour.

    `rim` is a border, as a fraction of the size, that may show table and is not used to measure the light.
    Returns None when the image shows too little plain paper to measure the light."""
    h, w = rgb.shape[:2]
    img = rgb.astype(np.float32)
    s = 256 / max(h, w)
    small = cv2.resize(img, (max(8, round(w * s)), max(8, round(h * s))), interpolation=cv2.INTER_AREA)
    sh, sw = small.shape[:2]
    paper_only = cv2.dilate(small, np.ones((5, 5), np.uint8))  # thin dark strokes take the paper's colour
    bright = paper_only.max(axis=2)
    local_top = cv2.dilate(bright, np.ones((max(3, sh // 4), max(3, sw // 4)), np.uint8))
    local_top = cv2.GaussianBlur(local_top, (0, 0), max(sh, sw) / 12)
    chroma = paper_only / (paper_only.sum(axis=2, keepdims=True) + 1e-3)
    reference = np.median(chroma[bright >= np.quantile(bright, 0.6)], axis=0)
    # paper: not much darker than the brightest paper nearby and of the same tint (shadows qualify, print not)
    paper = (bright >= 0.5 * local_top) & (np.abs(chroma - reference).max(axis=2) < 0.035)
    if rim:
        r = math.ceil(rim * max(sh, sw))
        paper[:r], paper[-r:], paper[:, :r], paper[:, -r:] = False, False, False, False
    if paper.mean() < 0.05:
        return None
    weight = paper.astype(np.float32)
    light = np.zeros_like(paper_only)
    known = np.zeros((sh, sw), bool)
    for sigma in (max(sh, sw) / 40, max(sh, sw) / 15, max(sh, sw) / 5, max(sh, sw)):
        weights = cv2.GaussianBlur(weight, (0, 0), sigma)
        values = cv2.GaussianBlur(paper_only * weight[..., None], (0, 0), sigma)
        fresh = (weights > 0.05) & ~known  # areas without paper borrow the light from paper further away
        light[fresh] = values[fresh] / weights[fresh, None]
        known |= fresh
    light[~known] = np.median(paper_only[paper], axis=0)
    light = cv2.resize(cv2.GaussianBlur(light, (0, 0), max(sh, sw) / 100), (w, h), interpolation=cv2.INTER_CUBIC)
    relative = img / np.maximum(light, 1.0)
    white, black = 0.9, 0.08  # paper and its grain to white; faint pencil stays visible, ink gets darker
    out = np.clip((relative - black) / (white - black), 0, 1) ** 1.15
    return (out * 255 + 0.5).astype(np.uint8)


def scan_image(
    img: Image.Image, flatten: bool, max_side: int, focal: float | None = None
) -> tuple[Image.Image, list[str], dict]:
    rgb = np.asarray(img.convert("RGB"))
    notes: list[str] = []
    info: dict = {}
    corners = None
    if flatten:
        corners, best, outlines = find_outline(rgb, focal)
        if corners is not None and best is not None:
            corners = expand_quad(corners, SCAN_MARGIN * max(rgb.shape[:2]))
            rgb = warp_page(rgb, corners, max_side, focal)
            notes.append("sheet detected, flattened")
            info.update(outline="detected", method=best.method, corners=np.round(corners).astype(int).tolist())
        else:
            notes.append("no confident outline, kept full photo")
            closest = max(outlines, key=lambda o: o.score, default=None)
            reason = f"{closest.method}: {', '.join(closest.problems)}" if closest else "no candidate"
            info.update(outline="not found", reason=reason)
    if corners is None and max(rgb.shape[:2]) > max_side:
        scale = max_side / max(rgb.shape[:2])
        size = (round(rgb.shape[1] * scale), round(rgb.shape[0] * scale))
        rgb = cv2.resize(rgb, size, interpolation=cv2.INTER_AREA)
    even = normalise_lighting(rgb, rim=0.015 if corners is not None else 0.0)
    notes.append("lighting normalised" if even is not None else "lighting kept (too little plain paper)")
    info["lighting"] = even is not None
    return Image.fromarray(even if even is not None else rgb), notes, info


def scan_page(page: Page, flatten: bool, max_side: int) -> tuple[Image.Image, dict | None]:
    """The page after --scan or --clean, never losing it: on any trouble the photo is kept as it was."""
    if page.source.suffix.lower() == ".pdf":
        page.notes.append("PDF page, scan step skipped (already a scan)")
        return page.image, None
    if not HAVE_CV:
        page.notes.append("scan step skipped (OpenCV not installed)")
        return page.image, None
    try:
        img, notes, info = scan_image(page.image, flatten, max_side, page.focal)
    except Exception as error:  # a scanner bug must not cost a page
        page.notes.append(f"scan step failed, kept the photo as it was: {error}")
        return page.image, None
    page.notes.extend(notes)
    return img, info


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("inputs", nargs="+", help="image files, PDFs or folders")
    parser.add_argument("-o", "--outdir", required=True, help="folder for page-NNN.jpg and manifest.json")
    parser.add_argument("--pdf", help="also write all pages into this archive PDF")
    parser.add_argument(
        "--order",
        choices=["capture", "name", "given"],
        default="capture",
        help="capture time from the photo (default), file name, or the order given",
    )
    parser.add_argument("--max-side", type=int, default=2000, help="longest side in pixels (default 2000)")
    parser.add_argument("--pdf-max-side", type=int, default=1800, help="longest side inside the archive PDF")
    parser.add_argument("--dpi", type=int, default=200, help="render resolution for PDF input (default 200)")
    parser.add_argument(
        "--rotate",
        action="append",
        default=[],
        metavar="PAGE:DEGREES",
        help="rotate an output page clockwise, e.g. 2:90; repeatable",
    )
    parser.add_argument("--split", action="store_true", help="also write overlapping top and bottom halves")
    parser.add_argument(
        "--scan",
        action="store_true",
        help="photos: find the sheet, flatten it and even out the lighting; keeps the full photo when unsure",
    )
    parser.add_argument("--clean", action="store_true", help="photos: even out the lighting only, no cropping")
    parser.add_argument("--quality", type=int, default=88, help="JPEG quality (default 88)")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    rotations = parse_rotations(args.rotate)
    scanning = args.scan or args.clean
    if scanning and not HAVE_CV:
        print(
            "warning: --scan and --clean need OpenCV and numpy (pip install opencv-python-headless numpy); "
            "the pages are prepared without them",
            file=sys.stderr,
        )

    files = collect_inputs(args.inputs)
    if not files:
        print("error: no input files", file=sys.stderr)
        return 2

    pages: list[Page] = []
    failures = []
    for path in files:
        try:
            pages.extend(load(path, args.dpi))
        except Exception as error:  # keep going and report at the end
            failures.append({"source": str(path), "error": str(error)})
            print(f"warning: {error}", file=sys.stderr)
    if not pages:
        print("error: none of the inputs could be read", file=sys.stderr)
        return 1

    pages = order_pages(pages, args.order)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"version": __version__, "pages": [], "failed": failures}
    archive: list[Image.Image] = []

    for number, page in enumerate(pages, start=1):
        img, scan_info = page.image, None
        if scanning:
            img, scan_info = scan_page(page, flatten=args.scan, max_side=max(args.max_side, args.pdf_max_side))
        if rotations.get(number):
            img = img.rotate(-rotations[number], expand=True)  # PIL rotates counter-clockwise
            page.notes.append(f"rotated {rotations[number]} degrees")
        full = fit(img, args.max_side)
        name = f"page-{number:03d}.jpg"
        full.save(outdir / name, "JPEG", quality=args.quality, optimize=True)
        entry = {
            "page": number,
            "file": name,
            "source": page.source.name,
            "page_in_source": page.page_in_source,
            "captured": page.captured.isoformat(timespec="seconds") if page.captured else None,
            "size": list(full.size),
            "notes": page.notes,
        }
        if scan_info:
            entry["scan"] = scan_info
        if args.split:
            entry["halves"] = []
            for label, half in zip("ab", split_halves(full), strict=True):
                half_name = f"page-{number:03d}{label}.jpg"
                half.save(outdir / half_name, "JPEG", quality=args.quality, optimize=True)
                entry["halves"].append(half_name)
        manifest["pages"].append(entry)
        if args.pdf:
            archive.append(fit(img, args.pdf_max_side))

    if args.pdf:
        pdf_path = Path(args.pdf).expanduser()
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        archive[0].save(pdf_path, "PDF", save_all=True, append_images=archive[1:], resolution=150, quality=82)
        manifest["archive_pdf"] = str(pdf_path)

    (outdir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        json.dumps(
            {
                "pages": len(pages),
                "failed": len(failures),
                "outdir": str(outdir),
                "archive_pdf": manifest.get("archive_pdf"),
            }
        )
    )
    return 0 if not failures else 3


if __name__ == "__main__":
    sys.exit(main())
