#!/usr/bin/env python3
"""
slides.py: turn a lecture PDF into material Claude can look at and cut figures from.

Subcommands
-----------
prepare  <pdf> [--out DIR] [--dpi 110]
    Default DIR: <course>/Anki/build/<pdf stem>/ when the pdf lies inside a course folder
    (a folder with Anki/profile.md), which is where build_deck.py and validate.py look for
    candidates.json. Renders every page (DIR/pages/pNNN.png), writes the extracted text
    (DIR/text.md, one "## Slide N" section per page), detects figure candidates (embedded
    raster images and clusters of vector drawings) and draws them, numbered, on contact
    sheets (DIR/contact/pNNN.png) together with a 0.1 coordinate grid, so that a card can
    reference a figure either as {slide: 17, candidate: f2} or as
    {slide: 17, clip: [x0, y0, x1, y1]} in page-normalised coordinates (0..1, origin top
    left). Candidate metadata goes to DIR/candidates.json.

montage  DIR [--per 4] [--cols 2] [--width 800]
    Tiles the rendered pages of a prepared DIR into numbered overview sheets
    (DIR/montage/m001-004.png ...) for a cheap first reading pass; open single pages from
    DIR/pages/ wherever a sheet is too small to read. For long decks, --per 9 --cols 3
    --width 600 gives a quick pass over text slides.

crop     <pdf> --slide N (--candidate fK | --clip x0 y0 x1 y1 | --full)
         --out FILE.png [--dpi 220] [--pad 0.012] [--mask x0 y0 x1 y1 ...]
         [--candidates DIR/candidates.json]
    Cuts one figure at high resolution. Masks are white boxes painted over the figure
    (coordinates normalised to the *figure*, not the page) to hide an answer that is
    visible in the picture.

build_deck.py imports this module (function crop_figure).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import pymupdf  # PyMuPDF >= 1.24.3 (the `pymupdf` module name)
from PIL import Image, ImageDraw, ImageFont

DATA_SUBDIR = "Anki"  # same as validate.DATA_SUBDIR

# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------


def _norm(rect: pymupdf.Rect, page: pymupdf.Page) -> list[float]:
    w, h = page.rect.width, page.rect.height
    return [round(rect.x0 / w, 4), round(rect.y0 / h, 4), round(rect.x1 / w, 4), round(rect.y1 / h, 4)]


def _denorm(box: list[float], page: pymupdf.Page) -> pymupdf.Rect:
    w, h = page.rect.width, page.rect.height
    return pymupdf.Rect(box[0] * w, box[1] * h, box[2] * w, box[3] * h)


def _area_frac(rect: pymupdf.Rect, page: pymupdf.Page) -> float:
    return (rect.width * rect.height) / (page.rect.width * page.rect.height)


def _iou(a: pymupdf.Rect, b: pymupdf.Rect) -> float:
    inter = a & b
    if inter.is_empty:
        return 0.0
    ia = inter.width * inter.height
    ua = a.width * a.height + b.width * b.height - ia
    return ia / ua if ua else 0.0


def _merge_rects(rects: list[pymupdf.Rect], iou_thr: float = 0.25) -> list[pymupdf.Rect]:
    """Union rectangles that overlap substantially or contain each other."""
    rects = [pymupdf.Rect(r) for r in rects]
    changed = True
    while changed:
        changed = False
        out: list[pymupdf.Rect] = []
        while rects:
            r = rects.pop()
            for i, o in enumerate(out):
                if _iou(r, o) > iou_thr or o.contains(r) or r.contains(o):
                    out[i] = o | r
                    changed = True
                    break
            else:
                out.append(r)
        rects = out
    return rects


def _grow_with_labels(
    rect: pymupdf.Rect,
    page: pymupdf.Page,
    blocks,
    margin: float = 9.0,
    max_block_height: float = 42.0,
    max_words: int = 6,
) -> pymupdf.Rect:
    """Extend a drawing cluster so axis labels, tick labels and legends that sit right next to it
    end up inside the crop. Only short text blocks that touch the drawing qualify; sentences of
    slide text and captions are left out on purpose (a caption often contains the answer)."""
    grown = pymupdf.Rect(rect)
    for _ in range(3):
        probe = pymupdf.Rect(grown.x0 - margin, grown.y0 - margin, grown.x1 + margin, grown.y1 + margin)
        for b in blocks:
            br = pymupdf.Rect(b[:4])
            words = len(str(b[4]).split()) if len(b) > 4 else 0
            if (
                br.height <= max_block_height
                and words <= max_words
                and br.intersects(probe)
                and _area_frac(br, page) < 0.08
            ):
                grown |= br
    return grown


# ----------------------------------------------------------------------------
# candidate detection
# ----------------------------------------------------------------------------


def _vector_clusters(page: pymupdf.Page) -> list[pymupdf.Rect]:
    try:
        # PowerPoint exports draw an invisible content-area rectangle on every page; it would swallow every
        # table and diagram into one page-sized cluster. Drop oversized drawings before clustering.
        page_area = page.rect.width * page.rect.height
        drawings = [
            d
            for d in page.get_drawings()
            if d.get("rect") is not None and (d["rect"].width * d["rect"].height) < 0.45 * page_area
        ]
        vecs = page.cluster_drawings(drawings=drawings, x_tolerance=4, y_tolerance=4) if drawings else []
    except Exception:  # older PyMuPDF without cluster_drawings, or a malformed page
        vecs = []
    return [pymupdf.Rect(v) & page.rect for v in vecs]


def _vec_key(v: pymupdf.Rect) -> tuple[int, ...]:
    return tuple(round(x / 4) for x in (v.x0, v.y0, v.x1, v.y1))


def detect_candidates(doc: pymupdf.Document) -> dict:
    """Return {"pages": n, "page_size": [w, h], "slides": {"17": [{id, kind, bbox, area}, ...]}}."""
    n = len(doc)
    # pass 1: things that repeat on many pages are decoration (logos, frames, footers)
    img_xref_pages: Counter = Counter()
    vec_key_pages: Counter = Counter()
    per_page_imgs: list[list[tuple[int, pymupdf.Rect]]] = []
    per_page_vecs: list[list[pymupdf.Rect]] = []
    for page in doc:
        imgs = []
        seen_xrefs = set()
        for info in page.get_image_info(xrefs=True):
            xref = info.get("xref", 0)
            r = pymupdf.Rect(info["bbox"]) & page.rect
            if r.is_empty:
                continue
            imgs.append((xref, r))
            if xref and xref not in seen_xrefs:
                img_xref_pages[xref] += 1
                seen_xrefs.add(xref)
        per_page_imgs.append(imgs)
        vecs = _vector_clusters(page)
        for key in {_vec_key(v) for v in vecs}:
            vec_key_pages[key] += 1
        per_page_vecs.append(vecs)

    repeat_thr = max(3, int(0.35 * n)) if n >= 6 else n + 1
    slides: dict[str, list[dict]] = {}
    for pno, page in enumerate(doc):
        blocks = page.get_text("blocks")
        cands: list[tuple[str, pymupdf.Rect]] = []
        for xref, r in per_page_imgs[pno]:
            af = _area_frac(r, page)
            if af < 0.012 or af > 0.96:
                continue
            if xref and img_xref_pages[xref] >= repeat_thr:
                continue
            cands.append(("image", r))
        for v in per_page_vecs[pno]:
            af = _area_frac(v, page)
            if af < 0.006 or af > 0.92:
                continue
            if min(v.width, v.height) < 9:  # rules, underlines, bullets
                continue
            if vec_key_pages[_vec_key(v)] >= repeat_thr:
                continue
            cands.append(("vector", _grow_with_labels(v, page, blocks)))
        merged: list[dict] = []
        # keep the kind of the original components inside each merged rect
        for r in _merge_rects([r for _, r in cands]):
            kinds = [k for k, o in cands if r.contains(o) or _iou(r, o) > 0.25]
            kind = "image" if "image" in kinds and kinds.count("image") >= kinds.count("vector") else "vector"
            if "image" in kinds and "vector" in kinds:
                kind = "mixed"
            merged.append({"kind": kind, "rect": r})
        merged.sort(key=lambda d: (round(d["rect"].y0 / 20), d["rect"].x0))
        out = [
            {
                "id": f"f{i}",
                "kind": d["kind"],
                "bbox": _norm(d["rect"], page),
                "area": round(_area_frac(d["rect"], page), 3),
            }
            for i, d in enumerate(merged, 1)
        ]
        if out:
            slides[str(pno + 1)] = out
    return {"pages": n, "page_size": [round(doc[0].rect.width, 1), round(doc[0].rect.height, 1)], "slides": slides}


# ----------------------------------------------------------------------------
# rendering
# ----------------------------------------------------------------------------

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
)


def _font(size: int):
    for cand in _FONT_CANDIDATES:
        if Path(cand).exists():
            return ImageFont.truetype(cand, size)
    try:
        return ImageFont.load_default(size)  # Pillow >= 10.1 scales the built-in font
    except TypeError:
        return ImageFont.load_default()


def render_page(page: pymupdf.Page, dpi: int) -> Image.Image:
    pix = page.get_pixmap(dpi=dpi, alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def contact_sheet(page: pymupdf.Page, cands: list[dict], dpi: int) -> Image.Image:
    img = render_page(page, dpi).convert("RGBA")
    w, h = img.size
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    # coordinate grid every 0.1, labels along the top and left edges
    small = _font(max(11, w // 90))
    for i in range(1, 10):
        x = int(w * i / 10)
        y = int(h * i / 10)
        d.line([(x, 0), (x, h)], fill=(0, 120, 255, 70), width=1)
        d.line([(0, y), (w, y)], fill=(0, 120, 255, 70), width=1)
        d.text((x + 2, 2), f".{i}", fill=(0, 90, 220, 230), font=small)
        d.text((2, y + 2), f".{i}", fill=(0, 90, 220, 230), font=small)
    colors = {"image": (220, 40, 40, 255), "vector": (30, 160, 60, 255), "mixed": (200, 120, 0, 255)}
    big = _font(max(16, w // 45))
    size = getattr(big, "size", 16)
    for c in cands:
        x0, y0, x1, y1 = c["bbox"]
        box = [x0 * w, y0 * h, x1 * w, y1 * h]
        col = colors.get(c["kind"], (0, 0, 0, 255))
        d.rectangle(box, outline=col, width=3)
        label = f"{c['id']} {c['kind']}"
        tw = d.textlength(label, font=big)
        top = max(0, box[1] - size - 6)
        d.rectangle([box[0], top, box[0] + tw + 10, top + size + 6], fill=col)
        d.text((box[0] + 5, max(0, box[1] - size - 4)), label, fill=(255, 255, 255, 255), font=big)
    return Image.alpha_composite(img, overlay).convert("RGB")


def crop_figure(
    pdf: str | Path,
    slide: int,
    *,
    candidate: str | None = None,
    clip: list[float] | None = None,
    full: bool = False,
    out: str | Path,
    dpi: int = 220,
    pad: float = 0.012,
    masks: list[list[float]] | None = None,
    candidates: dict | None = None,
    max_width: int = 1600,
) -> Path:
    with pymupdf.open(str(pdf)) as doc:
        if not 1 <= slide <= len(doc):
            raise ValueError(f"slide {slide} out of range 1..{len(doc)}")
        page = doc[slide - 1]
        if full:
            rect = page.rect
        elif clip:
            rect = _denorm(clip, page)
        elif candidate:
            if candidates is None:
                candidates = detect_candidates(doc)
            on_slide = candidates["slides"].get(str(slide), [])
            entry = next((c for c in on_slide if c["id"] == candidate), None)
            if entry is None:
                raise ValueError(f"slide {slide}: no candidate {candidate}; available: {[c['id'] for c in on_slide]}")
            rect = _denorm(entry["bbox"], page)
        else:
            raise ValueError("need one of candidate / clip / full")
        if not full:
            p = pad * max(page.rect.width, page.rect.height)
            rect = pymupdf.Rect(rect.x0 - p, rect.y0 - p, rect.x1 + p, rect.y1 + p) & page.rect
        pix = page.get_pixmap(dpi=dpi, clip=rect, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    if masks:
        d = ImageDraw.Draw(img)
        w, h = img.size
        for m in masks:
            d.rectangle([m[0] * w, m[1] * h, m[2] * w, m[3] * h], fill=(255, 255, 255))
    if img.width > max_width:
        img = img.resize((max_width, int(img.height * max_width / img.width)), Image.LANCZOS)
    # Diagrams, tables and plots have few colours: a 256-colour palette cuts the file to a third with no
    # visible loss, which matters for mobile sync. Photographs keep full colour.
    probe = img.copy()
    probe.thumbnail((128, 128))
    if probe.getcolors(3999) is not None:  # fewer than 4000 distinct colours
        img = img.quantize(colors=256, method=Image.MEDIANCUT, dither=Image.NONE)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, optimize=True)
    return out


def montage(pages_dir: Path, out_dir: Path, per: int = 4, cell_width: int = 800, cols: int = 2) -> list[Path]:
    """Tile rendered pages (2x2 for per=4, 3x3 for per=9 with cols=3) into overview sheets with slide
    numbers, so a first reading pass costs a fraction of the images; dense slides are then opened singly."""
    files = sorted(Path(pages_dir).glob("p*.png"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cols = max(1, cols)
    rows = max(1, -(-per // cols))
    outs = []
    font = _font(22)
    gutter = 14
    for start in range(0, len(files), per):
        chunk = files[start : start + per]
        thumbs = []
        for f in chunk:
            with Image.open(f) as src:
                im = src.convert("RGB")
            im = im.resize((cell_width, int(im.height * cell_width / im.width)), Image.LANCZOS)
            thumbs.append((f, im))
        ch = max(im.height for _, im in thumbs)
        sheet = Image.new("RGB", (cols * cell_width + (cols + 1) * gutter, rows * (ch + 30) + gutter), (235, 235, 238))
        d = ImageDraw.Draw(sheet)
        for i, (f, im) in enumerate(thumbs):
            r, c = divmod(i, cols)
            x = gutter + c * (cell_width + gutter)
            y = gutter + r * (ch + 30)
            d.rectangle([x, y, x + 70, y + 26], fill=(30, 30, 30))
            d.text((x + 8, y + 2), f"#{int(f.stem[1:])}", fill=(255, 255, 255), font=font)
            sheet.paste(im, (x, y + 28))
            d.rectangle([x - 1, y + 27, x + im.width, y + 28 + im.height], outline=(180, 180, 185))
        first, last = int(chunk[0].stem[1:]), int(chunk[-1].stem[1:])
        out = out_dir / f"m{first:03d}-{last:03d}.png"
        sheet.save(out, optimize=True)
        outs.append(out)
    return outs


def default_out_dir(pdf: Path) -> Path | None:
    """<course>/Anki/build/<pdf stem> for a pdf inside a course folder (or <folder>/build/<stem> in a flat
    folder with profile.md); None if the pdf is not inside one."""
    pdf = Path(pdf).resolve()
    for d in pdf.parents:
        if (d / DATA_SUBDIR / "profile.md").exists():
            return d / DATA_SUBDIR / "build" / pdf.stem
        if (d / "profile.md").exists():
            return d / "build" / pdf.stem
    return None


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------


def prepare(pdf: Path, out: Path, dpi: int = 110) -> dict:
    out = Path(out)
    (out / "pages").mkdir(parents=True, exist_ok=True)
    (out / "contact").mkdir(parents=True, exist_ok=True)
    with pymupdf.open(str(pdf)) as doc:
        cands = detect_candidates(doc)
        (out / "candidates.json").write_text(json.dumps(cands, indent=1), encoding="utf-8")
        lines = [f"# {Path(pdf).name}: extracted text ({len(doc)} pages)", ""]
        for i, page in enumerate(doc, 1):
            render_page(page, dpi).save(out / "pages" / f"p{i:03d}.png", optimize=True)
            contact_sheet(page, cands["slides"].get(str(i), []), dpi).save(
                out / "contact" / f"p{i:03d}.png", optimize=True
            )
            txt = page.get_text("text").strip()
            lines += [f"## Slide {i}", "", txt if txt else "_(no extractable text)_", ""]
    (out / "text.md").write_text("\n".join(lines), encoding="utf-8")
    return cands


def cmd_prepare(args) -> int:
    cands = prepare(Path(args.pdf), Path(args.out), args.dpi)
    n_cand = sum(len(v) for v in cands["slides"].values())
    out = args.out
    print(
        f"{cands['pages']} pages rendered to {out}/pages, contact sheets in {out}/contact, "
        f"{n_cand} figure candidates on {len(cands['slides'])} slides -> {out}/candidates.json"
    )
    return 0


def cmd_montage(args) -> int:
    d = Path(args.dir)
    outs = montage(d / "pages", d / "montage", per=args.per, cell_width=args.width, cols=args.cols)
    print(f"{len(outs)} montage sheets in {d / 'montage'}")
    return 0


def cmd_crop(args) -> int:
    cands = None
    if args.candidates and Path(args.candidates).exists():
        cands = json.loads(Path(args.candidates).read_text(encoding="utf-8"))
    masks = None
    if args.mask:
        if len(args.mask) % 4:
            print("--mask needs groups of four numbers", file=sys.stderr)
            return 2
        masks = [args.mask[i : i + 4] for i in range(0, len(args.mask), 4)]
    p = crop_figure(
        args.pdf,
        args.slide,
        candidate=args.candidate,
        clip=args.clip,
        full=args.full,
        out=args.out,
        dpi=args.dpi,
        pad=args.pad,
        masks=masks,
        candidates=cands,
    )
    print(p)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("prepare", help="render pages, extract text, detect figure candidates")
    a.add_argument("pdf")
    a.add_argument("--out", help="default: <course>/Anki/build/<pdf stem>")
    a.add_argument("--dpi", type=int, default=110)
    a.set_defaults(func=cmd_prepare)
    c = sub.add_parser("crop", help="cut one figure out of a page")
    c.add_argument("pdf")
    c.add_argument("--slide", type=int, required=True)
    c.add_argument("--candidate")
    c.add_argument("--clip", type=float, nargs=4)
    c.add_argument("--full", action="store_true")
    c.add_argument("--out", required=True)
    c.add_argument("--dpi", type=int, default=220)
    c.add_argument("--pad", type=float, default=0.012)
    c.add_argument("--mask", type=float, nargs="+")
    c.add_argument("--candidates")
    c.set_defaults(func=cmd_crop)
    m = sub.add_parser("montage", help="tile pages of a prepared DIR into overview sheets (DIR/montage)")
    m.add_argument("dir")
    m.add_argument("--per", type=int, default=4, help="pages per sheet")
    m.add_argument("--cols", type=int, default=2, help="pages per row")
    m.add_argument("--width", type=int, default=800, help="width of one page in pixels")
    m.set_defaults(func=cmd_montage)
    args = ap.parse_args(argv)
    if args.cmd == "prepare" and not args.out:
        out = default_out_dir(Path(args.pdf))
        if out is None:
            ap.error("--out is required when the pdf is not inside a course folder with Anki/profile.md")
        args.out = str(out)
        print("out:", args.out)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
