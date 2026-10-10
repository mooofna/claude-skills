"""Unit tests for the text and deck helpers of build_deck.py and proof_sheet.py."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
NAMES = ("slides", "validate", "build_deck", "proof_sheet")


@pytest.fixture(scope="module")
def m():
    saved_path = list(sys.path)
    saved = {n: sys.modules.pop(n) for n in NAMES if n in sys.modules}
    saved_bytecode, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    sys.path.insert(0, str(SCRIPTS))
    try:
        yield SimpleNamespace(**{n: importlib.import_module(n) for n in NAMES})
    finally:
        for n in NAMES:
            sys.modules.pop(n, None)
        sys.modules.update(saved)
        sys.path[:] = saved_path
        sys.dont_write_bytecode = saved_bytecode


def test_math_survives_markdown(m):
    out = m.build_deck.to_html("The *rate* is \\(a_1 * b_2\\) and $x_i^2$.")
    assert out == "The <em>rate</em> is \\(a_1 * b_2\\) and \\(x_i^2\\)."


def test_display_math_keeps_line_breaks_and_escapes_html(m):
    out = m.build_deck.to_html("\\[\\begin{aligned} a &< b \\\\ c &= d \\end{aligned}\\]")
    assert out == "\\[\\begin{aligned} a &amp;&lt; b \\\\ c &amp;= d \\end{aligned}\\]"


def test_code_span_with_html_comment_is_kept_whole(m):
    assert m.build_deck.to_html("Close with `--!>` or `<!-- x -->`") == (
        "Close with <code>--!&gt;</code> or <code>&lt;!-- x --&gt;</code>"
    )


def test_tables_lists_and_hash_digits(m):
    table = m.build_deck.to_html("| a | b |\n|---|---|\n| 1 | 2 |")
    assert "<table>" in table and "<td>1</td>" in table
    assert m.build_deck.to_html("Steps:\n\n1. first\n2. second").count("<li>") == 2
    assert m.build_deck.to_html("#1 is the first item").startswith("#1")


def test_cloze_braces_are_separated(m):
    assert m.build_deck.fix_cloze_braces("{{c1::\\frac{1}{2}}}") == "{{c1::\\frac{1}{2} }}"


def test_short_title(m):
    st = m.build_deck.short_title
    assert st("Gaussian Processes - Part 2") == "Gaussian Processes"
    assert st("Gaussian Processes \u2013 inference") == "Gaussian Processes"
    assert st("Introduction: what learning means") == "Introduction"
    assert st('A "quoted" deck::name') == "A quoted deck:name"
    long = st("A very long lecture title that goes on and on beyond forty characters")
    assert len(long) == 40 and long.endswith("...")


def test_lecture_deck_is_frozen_by_the_lock_file(m):
    module = {"deck": "Course", "subdecks": True}
    locks: dict = {}
    assert m.build_deck.lecture_deck(module, {"lecture": "L01", "title": "Intro: basics"}, locks) == "Course::L01 Intro"
    assert m.build_deck.lecture_deck(module, {"lecture": "L01", "title": "Renamed"}, locks) == "Course::L01 Intro"
    assert m.build_deck.lecture_deck(module, {"lecture": "L02", "deck_title": "Own label"}, locks) == (
        "Course::L02 Own label"
    )
    assert m.build_deck.lecture_deck({"deck": "Flat", "subdecks": False}, {"lecture": "L03"}, {}) == "Flat"


def test_source_line_and_tags(m):
    module = {"id": "Mod", "tag_prefix": "", "profile": {}, "_blocks": {}}
    lec = {"lecture": "L02", "title": "Trees"}
    card = {"source": [5, 3, 4], "source_ref": "Exam 2024 Q1", "tags": ["type::pitfall"], "stage": "exam"}
    expected = "Mod \u00b7 L02 \u00b7 slides 3-5 \u00b7 Exam 2024 Q1 \u00b7 Trees"
    assert m.build_deck.source_html(module, lec, card) == expected
    assert m.build_deck.card_tags(module, lec, card) == ["Mod::L02", "type::pitfall", "Mod::exam-practice"]
    assert m.validate.tag_base({"id": "Mod", "tag_prefix": "2026S"}) == "2026S::Mod"


def test_cloze_preview_shows_answers_inside_and_outside_math(m):
    out = m.proof_sheet.cloze_preview("Rank {{c1::\\(r\\) of A}} and \\(x = {{c2::y}}\\).")
    assert '<span class="cloze" title="c1">[\\(r\\) of A]</span>' in out
    assert "\\(x = \\class{cloze}{y}\\)" in out


def test_crop_figure_applies_clip_and_mask(m, tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    from PIL import Image

    pdf = tmp_path / "one.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page(width=200, height=100)
        page.draw_rect(pymupdf.Rect(0, 0, 100, 100), color=(0, 0, 0), fill=(0, 0, 0))
        doc.save(str(pdf))
    out = m.slides.crop_figure(pdf, 1, clip=[0.0, 0.0, 1.0, 1.0], out=tmp_path / "a.png", dpi=72, pad=0)
    with Image.open(out) as img:
        rgb = img.convert("RGB")
        assert rgb.size == (200, 100)
        assert rgb.getpixel((20, 50)) == (0, 0, 0)
        assert rgb.getpixel((180, 50)) == (255, 255, 255)
    masked = m.slides.crop_figure(pdf, 1, full=True, out=tmp_path / "b.png", dpi=72, masks=[[0.0, 0.0, 0.25, 1.0]])
    with Image.open(masked) as img:
        assert img.convert("RGB").getpixel((20, 50)) == (255, 255, 255)
    with pytest.raises(ValueError, match="out of range"):
        m.slides.crop_figure(pdf, 2, full=True, out=tmp_path / "c.png")
