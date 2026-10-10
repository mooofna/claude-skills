"""Tests for prepare_pages.py: every input format, ordering, rotation, outputs."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare_pages.py"
spec = importlib.util.spec_from_file_location("prepare_pages", SCRIPT)
pp = importlib.util.module_from_spec(spec)
sys.modules["prepare_pages"] = pp
spec.loader.exec_module(pp)


def page_image(label: str, size=(600, 800), mode="RGB") -> Image.Image:
    """A portrait 'page' with a dark bar at the top so orientation is checkable."""
    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, size[0], size[1] // 10), fill="black")
    draw.text((20, size[1] // 2), label, fill="black")
    return img.convert(mode) if mode != "RGB" else img


def exif_with(time: str | None = None, orientation: int | None = None) -> Image.Exif:
    exif = Image.Exif()
    if orientation:
        exif[0x0112] = orientation
    if time:
        exif[0x0132] = time  # DateTime in IFD0
        exif.get_ifd(0x8769)[0x9003] = time  # DateTimeOriginal in the Exif IFD
    return exif


def run(tmp_path: Path, *args: str) -> tuple[int, dict]:
    out = tmp_path / "out"
    code = pp.main([*args, "-o", str(out)])
    manifest = json.loads((out / "manifest.json").read_text()) if (out / "manifest.json").exists() else {}
    return code, manifest


def top_is_dark(path: Path) -> bool:
    with Image.open(path) as img:
        gray = img.convert("L")
        w, h = gray.size
        top = gray.crop((0, 0, w, h // 20)).resize((1, 1)).getpixel((0, 0))
        bottom = gray.crop((0, h - h // 20, w, h)).resize((1, 1)).getpixel((0, 0))
    return top < 100 < bottom


@pytest.mark.parametrize(
    "suffix,fmt,mode",
    [
        (".jpg", "JPEG", "RGB"),
        (".png", "PNG", "RGBA"),
        (".webp", "WEBP", "RGB"),
        (".bmp", "BMP", "RGB"),
        (".gif", "GIF", "P"),
        (".tif", "TIFF", "RGB"),
        (".avif", "AVIF", "RGB"),
        (".heic", "HEIF", "RGB"),
    ],
)
def test_every_image_format_becomes_an_rgb_jpeg(tmp_path, suffix, fmt, mode):
    if fmt == "HEIF" and not pp.HAVE_HEIF:
        pytest.skip("pillow-heif not installed")
    if fmt == "AVIF":
        from PIL import features

        if not (features.check("avif") or pp.HAVE_HEIF):
            pytest.skip("no AVIF support in this Pillow build")
    src = tmp_path / f"page{suffix}"
    page_image("format test", mode=mode).save(src, fmt)
    code, manifest = run(tmp_path, str(src))
    assert code == 0
    assert len(manifest["pages"]) == 1
    with Image.open(tmp_path / "out" / "page-001.jpg") as out:
        assert out.mode == "RGB" and out.format == "JPEG"
    assert top_is_dark(tmp_path / "out" / "page-001.jpg")


def test_transparent_png_is_flattened_onto_white(tmp_path):
    src = tmp_path / "clear.png"
    Image.new("RGBA", (400, 400), (0, 0, 0, 0)).save(src)
    run(tmp_path, str(src))
    with Image.open(tmp_path / "out" / "page-001.jpg") as out:
        assert min(out.convert("L").getextrema()) > 240


def test_exif_rotation_is_applied(tmp_path):
    # Stored sideways with orientation 6 (rotate 90 clockwise to display)
    upright = page_image("rotated")
    stored = upright.rotate(90, expand=True)  # what a phone writes to disk
    src = tmp_path / "sideways.jpg"
    stored.save(src, "JPEG", exif=exif_with(orientation=6))
    run(tmp_path, str(src))
    with Image.open(tmp_path / "out" / "page-001.jpg") as out:
        assert out.size[1] > out.size[0]  # portrait again
    assert top_is_dark(tmp_path / "out" / "page-001.jpg")


def test_capture_time_orders_pages_even_when_names_disagree(tmp_path):
    (tmp_path / "in").mkdir()
    page_image("second").save(tmp_path / "in" / "a.jpg", exif=exif_with("2026:10:10 12:00:05"))
    page_image("first").save(tmp_path / "in" / "b.jpg", exif=exif_with("2026:10:10 12:00:01"))
    _, manifest = run(tmp_path, str(tmp_path / "in"))
    assert [p["source"] for p in manifest["pages"]] == ["b.jpg", "a.jpg"]
    assert manifest["pages"][0]["captured"] == "2026-10-10T12:00:01"


def test_name_order_is_natural(tmp_path):
    (tmp_path / "in").mkdir()
    for name in ("IMG_10.png", "IMG_2.png", "IMG_1.png"):
        page_image(name).save(tmp_path / "in" / name)
    _, manifest = run(tmp_path, str(tmp_path / "in"), "--order", "name")
    assert [p["source"] for p in manifest["pages"]] == ["IMG_1.png", "IMG_2.png", "IMG_10.png"]


def test_pages_without_capture_time_follow_the_timed_ones(tmp_path):
    (tmp_path / "in").mkdir()
    page_image("no exif").save(tmp_path / "in" / "a.png")
    page_image("timed").save(tmp_path / "in" / "z.jpg", exif=exif_with("2026:10:10 09:00:00"))
    _, manifest = run(tmp_path, str(tmp_path / "in"))
    assert [p["source"] for p in manifest["pages"]] == ["z.jpg", "a.png"]


def test_pdf_and_multipage_tiff_yield_one_output_per_page(tmp_path):
    pytest.importorskip("pypdfium2")
    pdf = tmp_path / "scan.pdf"
    first, *rest = [page_image(f"pdf {i}") for i in range(3)]
    first.save(pdf, "PDF", save_all=True, append_images=rest)
    tiff = tmp_path / "scan.tif"
    # fresh images: Pillow cannot write a TIFF from an image that was just saved as PDF
    tiff_first, tiff_second = page_image("tif 1"), page_image("tif 2")
    tiff_first.save(tiff, "TIFF", save_all=True, append_images=[tiff_second])
    _, manifest = run(tmp_path, str(pdf), str(tiff), "--order", "given")
    assert [(p["source"], p["page_in_source"]) for p in manifest["pages"]] == [
        ("scan.pdf", 1),
        ("scan.pdf", 2),
        ("scan.pdf", 3),
        ("scan.tif", 1),
        ("scan.tif", 2),
    ]


def test_animated_gif_counts_as_one_page(tmp_path):
    src = tmp_path / "anim.gif"
    frames = [page_image(str(i), mode="P") for i in range(3)]
    frames[0].save(src, save_all=True, append_images=frames[1:])
    _, manifest = run(tmp_path, str(src))
    assert len(manifest["pages"]) == 1


def test_unreadable_file_is_reported_and_others_still_processed(tmp_path):
    good = tmp_path / "good.png"
    page_image("ok").save(good)
    bad = tmp_path / "broken.jpg"
    bad.write_bytes(b"not an image")
    code, manifest = run(tmp_path, str(good), str(bad))
    assert code == 3
    assert len(manifest["pages"]) == 1
    assert manifest["failed"][0]["source"].endswith("broken.jpg")


def test_hidden_and_system_files_are_ignored(tmp_path):
    (tmp_path / "in").mkdir()
    page_image("ok").save(tmp_path / "in" / "page.png")
    (tmp_path / "in" / ".DS_Store").write_bytes(b"x")
    (tmp_path / "in" / "._page.png").write_bytes(b"x")
    code, manifest = run(tmp_path, str(tmp_path / "in"))
    assert code == 0 and len(manifest["pages"]) == 1


def test_resize_split_rotate_and_archive_pdf(tmp_path):
    src = tmp_path / "big.png"
    page_image("big", size=(3000, 4000)).save(src)
    archive = tmp_path / "archive" / "session.pdf"
    code, manifest = run(tmp_path, str(src), "--max-side", "1000", "--split", "--rotate", "1:90", "--pdf", str(archive))
    assert code == 0
    page = manifest["pages"][0]
    assert max(page["size"]) == 1000
    assert page["size"][0] > page["size"][1]  # rotated to landscape
    assert page["halves"] == ["page-001a.jpg", "page-001b.jpg"]
    for half in page["halves"]:
        assert (tmp_path / "out" / half).exists()
    assert archive.exists() and archive.read_bytes().startswith(b"%PDF")


def test_bad_rotation_spec_is_rejected(tmp_path):
    src = tmp_path / "p.png"
    page_image("x").save(src)
    with pytest.raises(SystemExit):
        pp.main([str(src), "-o", str(tmp_path / "out"), "--rotate", "1:45"])


def test_no_inputs_returns_error(tmp_path):
    assert pp.main([str(tmp_path / "missing.jpg"), "-o", str(tmp_path / "out")]) == 2


# Document scanner (--scan, --clean). Synthetic photos only: a page with a dark band on top and twelve lines of
# "handwriting", photographed by a phone-like camera at an angle and laid on a striped table.

PAGE_RATIO = 2**0.5
FIRST_LINE, LINE_STEP, LINES = 0.16, 0.06, 12


@pytest.fixture
def cv():
    pytest.importorskip("numpy")
    return pytest.importorskip("cv2")


def synthetic_page(width=500):
    import cv2
    import numpy as np

    height = round(width * PAGE_RATIO)
    page = np.full((height, width, 3), 245, np.uint8)
    page[: round(height * 0.09)] = (30, 40, 70)  # printed header band
    rng = np.random.default_rng(1)
    for i in range(LINES):
        y, x = round(height * (FIRST_LINE + LINE_STEP * i)), round(width * 0.08)
        while x < width * 0.85:
            length = int(rng.integers(20, 70))
            cv2.line(page, (x, y), (min(x + length, round(width * 0.9)), y), (35, 35, 45), 3)
            x += length + int(rng.integers(10, 22))
    return page


def table_texture(kind, width=900, height=1200):
    import numpy as np

    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    if kind == "wood":  # brown grain with diagonal stripes
        u = xx * np.sin(0.35) + yy * np.cos(0.35)
        grain = 0.5 + 0.5 * np.sin(u / 3.0 + 2 * np.sin(u / 40.0))
        img = np.array([130, 80, 40], np.float32) * (0.45 + 0.6 * grain[..., None])
    else:  # hard-edged two-tone stripes the other way
        u = xx * np.cos(-0.6) + yy * np.sin(-0.6)
        img = np.where((np.sin(u / 6.0) > 0)[..., None], np.float32([120, 90, 60]), np.float32([85, 55, 35]))
    noise = np.random.default_rng(2).normal(0, 6, (height, width, 1))
    return np.clip(img + noise, 0, 255).astype(np.uint8)


def photograph(page, table, tilt, turn, cover=0.7):
    """Lay the page on the table and take a photo: camera tilted by `tilt` (degrees about x and y), page turned."""
    import cv2
    import numpy as np

    height, width = table.shape[:2]
    f = 0.6 * np.hypot(width, height)  # a phone's main camera
    ph, pw = page.shape[:2]
    r = ph / pw
    ax, ay, az = np.radians([*tilt, turn])
    rot_x = np.array([[1, 0, 0], [0, np.cos(ax), -np.sin(ax)], [0, np.sin(ax), np.cos(ax)]])
    rot_y = np.array([[np.cos(ay), 0, np.sin(ay)], [0, 1, 0], [-np.sin(ay), 0, np.cos(ay)]])
    rot_z = np.array([[np.cos(az), -np.sin(az), 0], [np.sin(az), np.cos(az), 0], [0, 0, 1]])
    corners = np.array([[-0.5, -r / 2, 0], [0.5, -r / 2, 0], [0.5, r / 2, 0], [-0.5, r / 2, 0]])
    p = corners @ (rot_x @ rot_y @ rot_z).T + [0, 0, f * r / (cover * height)]
    seen = np.stack([width / 2 + f * p[:, 0] / p[:, 2], height / 2 + f * p[:, 1] / p[:, 2]], axis=1)
    m = cv2.getPerspectiveTransform(np.float32([[0, 0], [pw, 0], [pw, ph], [0, ph]]), np.float32(seen))
    warped = cv2.warpPerspective(page, m, (width, height), flags=cv2.INTER_LINEAR)
    alpha = cv2.warpPerspective(np.ones((ph, pw), np.float32), m, (width, height))[..., None]
    return (warped * alpha + table * (1 - alpha)).astype(np.uint8)


def ink_rows(path):
    """Fractions of the page height where text lines are, between the header band and the bottom edge."""
    import numpy as np

    with Image.open(path) as img:
        gray = np.asarray(img.convert("L"))
    h, w = gray.shape
    inner = gray[:, round(w * 0.03) : round(w * 0.97)]
    rows = np.nonzero((inner < 110).mean(axis=1) > 0.1)[0] / h
    return rows[(rows > 0.12) & (rows < 0.97)]  # the very edge may show a hair of table


@pytest.mark.parametrize(
    "table,tilt,turn",
    [("wood", (0, 0), 4), ("wood", (20, -12), 10), ("stripes", (30, 5), -3), ("stripes", (12, 8), 15)],
)
def test_scan_flattens_a_photographed_page(tmp_path, cv, table, tilt, turn):
    src = tmp_path / "photo.png"
    Image.fromarray(photograph(synthetic_page(), table_texture(table), tilt, turn)).save(src)
    code, manifest = run(tmp_path, str(src), "--scan")
    assert code == 0
    page = manifest["pages"][0]
    assert page["notes"][:2] == ["sheet detected, flattened", "lighting normalised"]
    width, height = page["size"]
    assert height / width == pytest.approx(PAGE_RATIO, rel=0.03)
    out = tmp_path / "out" / "page-001.jpg"
    with Image.open(out) as img:
        gray = img.convert("L")
        band = gray.crop((width // 10, round(height * 0.01), width - width // 10, round(height * 0.06)))
        assert band.resize((1, 1)).getpixel((0, 0)) < 90  # the printed band on top is still there
    rows = ink_rows(out)  # first and last line in place: nothing cut, nothing shifted
    assert rows.min() == pytest.approx(FIRST_LINE, abs=0.025)
    assert rows.max() == pytest.approx(FIRST_LINE + LINE_STEP * (LINES - 1), abs=0.025)


@pytest.mark.parametrize("table", ["wood", "stripes"])
def test_scan_keeps_the_full_photo_when_there_is_no_sheet(tmp_path, cv, table):
    src = tmp_path / "table.png"
    Image.fromarray(table_texture(table)).save(src)
    code, manifest = run(tmp_path, str(src), "--scan")
    assert code == 0
    page = manifest["pages"][0]
    assert page["notes"][0] == "no confident outline, kept full photo"
    assert page["scan"]["outline"] == "not found"
    assert page["size"] == [900, 1200]


def test_scan_keeps_the_full_photo_when_the_sheet_runs_off_the_edge(tmp_path, cv):
    src = tmp_path / "close.png"
    Image.fromarray(photograph(synthetic_page(), table_texture("wood"), (0, 0), 4, cover=1.05)).save(src)
    _, manifest = run(tmp_path, str(src), "--scan")
    assert manifest["pages"][0]["notes"][0] == "no confident outline, kept full photo"


def test_clean_evens_out_uneven_light_and_keeps_faint_strokes(tmp_path, cv):
    import cv2
    import numpy as np

    page = synthetic_page(1000).astype(np.float32)
    h, w = page.shape[:2]
    paper = (page > 200).all(axis=2)
    cv2.line(page, (100, round(h * 0.92)), (900, round(h * 0.92)), (196, 196, 196), 3)  # faint pencil
    yy, xx = np.mgrid[0:h, 0:w]
    light = 1.0 - 0.55 * xx / w - 0.25 * np.exp(-(((xx - 0.3 * w) ** 2 + (yy - 0.6 * h) ** 2) / (0.2 * w) ** 2))
    src = tmp_path / "dim.png"
    Image.fromarray(np.clip(page * light[..., None], 0, 255).astype(np.uint8)).save(src)
    _, manifest = run(tmp_path, str(src), "--clean")
    assert manifest["pages"][0]["notes"] == ["lighting normalised"]
    with Image.open(tmp_path / "out" / "page-001.jpg") as img:
        out = np.asarray(img.convert("L")).astype(np.float32)
    assert out.shape == (h, w)
    clear = cv2.erode(paper.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
    clear[round(h * 0.9) :] = False
    assert out[clear].mean() > 240 and out[clear].std() < 8  # dim side and shadow are gone
    assert out[: round(h * 0.08), 50:-50].mean() < 110  # printed band stays dark
    pencil = out[round(h * 0.92), 150:850]
    assert pencil.mean() < out[clear].mean() - 25  # faint pencil still readable


def test_scan_leaves_pdf_pages_alone(tmp_path):
    pytest.importorskip("pypdfium2")
    pdf = tmp_path / "scan.pdf"
    page_image("pdf").save(pdf, "PDF")
    _, manifest = run(tmp_path, str(pdf), "--scan")
    assert manifest["pages"][0]["notes"] == ["PDF page, scan step skipped (already a scan)"]


def test_scan_without_opencv_falls_back_to_plain_processing(tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "cv2", None)  # `import cv2` now fails
    spec_without = importlib.util.spec_from_file_location("prepare_pages_without_cv", SCRIPT)
    module = importlib.util.module_from_spec(spec_without)
    monkeypatch.setitem(sys.modules, "prepare_pages_without_cv", module)
    spec_without.loader.exec_module(module)
    assert module.HAVE_CV is False
    src = tmp_path / "photo.png"
    page_image("no cv").save(src)
    out = tmp_path / "out"
    assert module.main([str(src), "-o", str(out), "--scan"]) == 0
    assert "need OpenCV" in capsys.readouterr().err
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["pages"][0]["notes"] == ["scan step skipped (OpenCV not installed)"]
    assert top_is_dark(out / "page-001.jpg")
