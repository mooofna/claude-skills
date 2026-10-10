#!/usr/bin/env python3
"""Build the synthetic 10-slide lecture PDF of the example course (examples/linear-algebra/L03-slides.pdf).

It exercises the pipeline: a logo repeated on every page (must be filtered out), a vector plot (slide 5),
a raster image (slide 6), a table drawn with vector rules (slide 8) and text-only slides. Only PyMuPDF and
Pillow are needed.

usage: make_example_slides.py OUT.pdf
"""

from __future__ import annotations

import io
import math
import sys
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageOps

W, H = 720, 405  # 16:9 in points
BLUE = (0.1, 0.3, 0.6)


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def logo_png() -> bytes:
    logo = Image.new("RGB", (120, 40), "white")
    d = ImageDraw.Draw(logo)
    d.rectangle([0, 0, 119, 39], outline="black", width=2)
    d.text((14, 13), "COURSE LOGO", fill="black")
    return _png(logo)


def heatmap_png(w: int = 300, h: int = 200) -> bytes:
    """A smooth 'data matrix' heatmap: a low-rank pattern plus a little structure."""
    img = Image.new("L", (w, h))
    img.putdata(
        [
            int(127 + 60 * math.sin(x / 23.0) * math.cos(y / 17.0) + 50 * math.sin((x + 2 * y) / 41.0))
            for y in range(h)
            for x in range(w)
        ]
    )
    return _png(ImageOps.colorize(img, black="#2b0a5a", white="#f5e14a", mid="#1f8f8a"))


def draw_decay_plot(page: pymupdf.Page, box: pymupdf.Rect) -> None:
    """Vector plot of singular values (log scale) of a smooth and a noisy signal, with axes and legend."""
    sh = page.new_shape()
    sh.draw_rect(box)
    sh.finish(color=(0, 0, 0), width=0.8)
    ks = range(1, 21)

    def pt(k: int, val: float) -> pymupdf.Point:
        x = box.x0 + 10 + (k - 1) * (box.width - 20) / 19
        y = box.y1 - 8 - (math.log10(val) + 3.2) / 3.4 * (box.height - 16)
        return pymupdf.Point(x, y)

    for k_fn, color, square in (
        (lambda k: math.exp(-0.35 * k), (0.12, 0.47, 0.71), False),
        (lambda k: 0.6 * math.exp(-0.08 * k), (1.0, 0.5, 0.05), True),
    ):
        pts = [pt(k, k_fn(k)) for k in ks]
        sh.draw_polyline(pts)
        sh.finish(color=color, width=1.2, closePath=False)
        for p in pts:
            if square:
                sh.draw_rect(pymupdf.Rect(p.x - 2, p.y - 2, p.x + 2, p.y + 2))
            else:
                sh.draw_circle(p, 2)
            sh.finish(color=color, fill=color)
    for k in (1, 5, 10, 15, 20):  # x ticks
        x = pt(k, 1).x
        sh.draw_line((x, box.y1), (x, box.y1 + 4))
        sh.finish(color=(0, 0, 0), width=0.6)
    for e in (-3, -2, -1, 0):  # y ticks
        y = pt(1, 10.0**e).y
        sh.draw_line((box.x0 - 4, y), (box.x0, y))
        sh.finish(color=(0, 0, 0), width=0.6)
    legend = pymupdf.Rect(box.x1 - 112, box.y0 + 6, box.x1 - 6, box.y0 + 36)
    sh.draw_rect(legend)
    sh.finish(color=(0.6, 0.6, 0.6), fill=(1, 1, 1), width=0.5)
    sh.draw_line((legend.x0 + 5, legend.y0 + 9), (legend.x0 + 20, legend.y0 + 9))
    sh.finish(color=(0.12, 0.47, 0.71), width=1.2)
    sh.draw_line((legend.x0 + 5, legend.y0 + 22), (legend.x0 + 20, legend.y0 + 22))
    sh.finish(color=(1.0, 0.5, 0.05), width=1.2)
    sh.commit()
    page.insert_text((legend.x0 + 24, legend.y0 + 12), "smooth signal", fontsize=8, fontname="helv")
    page.insert_text((legend.x0 + 24, legend.y0 + 25), "noisy signal", fontsize=8, fontname="helv")
    for k in (1, 5, 10, 15, 20):
        page.insert_text((pt(k, 1).x - 3, box.y1 + 12), str(k), fontsize=7, fontname="helv")
    for e in (-3, -2, -1, 0):
        page.insert_text((box.x0 - 26, pt(1, 10.0**e).y + 3), f"1e{e}", fontsize=7, fontname="helv")
    page.insert_text((box.x0 + box.width / 2 - 20, box.y1 + 22), "index k", fontsize=8, fontname="helv")
    page.insert_text((box.x0 + box.width / 2 - 45, box.y0 - 5), "Singular value decay", fontsize=9, fontname="helv")


def build(out: Path) -> Path:
    logo = logo_png()
    doc = pymupdf.open()

    def slide(title: str, body: tuple[str, ...] = (), fontsize: float = 13) -> pymupdf.Page:
        page = doc.new_page(width=W, height=H)
        page.insert_image(pymupdf.Rect(W - 130, H - 45, W - 10, H - 5), stream=logo)
        page.draw_line((30, 52), (W - 30, 52), color=BLUE, width=1.2)  # repeated rule
        page.insert_text((30, 40), title, fontsize=20, fontname="helv", color=BLUE)
        y = 80
        for line in body:
            page.insert_text((40, y), line, fontsize=fontsize, fontname="helv")
            y += fontsize * 1.7
        page.insert_text((W - 40, H - 12), str(len(doc)), fontsize=9, fontname="helv")
        return page

    slide("Linear Algebra for Data Science, Lecture 3", ("Singular Value Decomposition", "Example lecturer"))
    slide("Outline", ("1. Existence of the SVD", "2. Low-rank approximation", "3. Numerical considerations"))
    slide(
        "Definition (SVD)",
        (
            "Every A in R^{m x n} can be written as A = U S V^T with",
            "U in R^{m x m}, V in R^{n x n} orthogonal and S diagonal with",
            "s_1 >= s_2 >= ... >= s_r > 0, r = rank(A).",
            "The columns of U (V) are the left (right) singular vectors.",
        ),
    )
    slide(
        "Why does the SVD always exist?",
        (
            "A^T A is symmetric positive semidefinite  =>  spectral theorem applies:",
            "A^T A = V L V^T with L = diag(l_1,...,l_n), l_i >= 0.",
            "Set s_i = sqrt(l_i) and u_i = A v_i / s_i for s_i > 0; complete U orthonormally.",
            "Contrast: the eigendecomposition needs A square and diagonalisable.",
        ),
    )
    p = slide("Singular value decay in practice", ("Smooth signals: exponential decay; noise: flat tail.",))
    draw_decay_plot(p, pymupdf.Rect(90, 110, 390, 320))
    p.insert_text((430, 150), "Effective rank = number of", fontsize=12, fontname="helv")
    p.insert_text((430, 170), "sigma_k above the noise floor", fontsize=12, fontname="helv")
    p = slide("The data matrix", ("Rows = samples, columns = features.",))
    p.insert_image(pymupdf.Rect(80, 100, 380, 300), stream=heatmap_png())
    p.insert_text((400, 150), "Centering: subtract the column means", fontsize=12, fontname="helv")
    slide(
        "Eckart-Young-Mirsky theorem",
        (
            "For k < r, the best rank-k approximation in Frobenius and spectral norm is",
            "A_k = sum_{i<=k} s_i u_i v_i^T,   with",
            "||A - A_k||_2 = s_{k+1},   ||A - A_k||_F = sqrt(sum_{i>k} s_i^2).",
        ),
    )
    p = slide("Comparison of decompositions")
    rows = [
        ["", "Eigen", "SVD"],
        ["Matrix shape", "square", "any"],
        ["Always exists", "no", "yes"],
        ["Basis", "eigenvectors (not nec. orthogonal)", "two orthonormal bases"],
        ["Cost (n x n)", "O(n^3)", "O(n^3)"],
    ]
    y0 = 80
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            x = 40 + c * 220
            p.draw_rect(pymupdf.Rect(x, y0 + r * 28, x + 220, y0 + (r + 1) * 28), color=(0, 0, 0), width=0.6)
            p.insert_text((x + 6, y0 + r * 28 + 19), cell, fontsize=11, fontname="helv")
    slide(
        "Numerical considerations",
        (
            "Never form A^T A explicitly to compute the SVD: squares the condition number.",
            "kappa(A^T A) = kappa(A)^2  =>  small singular values are lost in floating point.",
            "Use Golub-Kahan bidiagonalisation (LAPACK gesvd / gesdd).",
        ),
    )
    slide(
        "Summary",
        ("SVD exists for every matrix; Eckart-Young gives optimal low-rank approximation;", "avoid A^T A numerically."),
    )
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out), garbage=4, deflate=True)
    doc.close()
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    print("wrote", build(Path(sys.argv[1])))
