"""End-to-end tests: the example course goes through slides.py, validate.py, build_deck.py, proof_sheet.py and
(when LaTeX is installed) summary.py, and the .apkg is read back from its SQLite collection."""

from __future__ import annotations

import importlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

SKILL = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL / "scripts"
EXAMPLE = SKILL / "examples" / "linear-algebra"
TESTS = Path(__file__).resolve().parent
SCRIPT_MODULES = ("slides", "validate", "build_deck", "proof_sheet", "summary")

DECK = "Linear Algebra (example)"
LECTURE_DECK = f"{DECK}::L03 Singular Value Decomposition"
EXAM_DECK = f"{DECK}::Exam practice"
ACTIVE_IDS = [f"LinAlg-L03-{n:03d}" for n in (1, 2, 3, 4, 5, 6, 7, 9, 10)]


@pytest.fixture(scope="module")
def tools():
    """Import the skill's scripts without leaving them in sys.modules (other skills may use the same names)."""
    saved_path = list(sys.path)
    saved = {n: sys.modules.pop(n) for n in (*SCRIPT_MODULES, "make_example_slides") if n in sys.modules}
    saved_bytecode, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    sys.path[:0] = [str(SCRIPTS), str(TESTS)]
    try:
        mods = {n: importlib.import_module(n) for n in SCRIPT_MODULES}
        mods["make_example_slides"] = importlib.import_module("make_example_slides")
        yield SimpleNamespace(**mods)
    finally:
        for n in (*SCRIPT_MODULES, "make_example_slides"):
            sys.modules.pop(n, None)
        sys.modules.update(saved)
        sys.path[:] = saved_path
        sys.dont_write_bytecode = saved_bytecode


def run(script: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    res = subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args], capture_output=True, text=True, env=env, check=False
    )
    assert res.returncode == 0, f"{script} {' '.join(args)} failed:\n{res.stdout}\n{res.stderr}"
    return res


def read_apkg(path: Path, tmp: Path) -> dict:
    """Notes, note types, decks and media of an .apkg (a zip holding a SQLite collection)."""
    with zipfile.ZipFile(path) as z:
        z.extract("collection.anki2", tmp)
        media = json.loads(z.read("media"))
        names = set(z.namelist())
    con = sqlite3.connect(tmp / "collection.anki2")
    try:
        models_json, decks_json = con.execute("select models, decks from col").fetchone()
        models = {int(k): v["name"] for k, v in json.loads(models_json).items()}
        decks = {int(k): v["name"] for k, v in json.loads(decks_json).items()}
        notes = {}
        for nid, guid, mid, flds, tags in con.execute("select id, guid, mid, flds, tags from notes"):
            card_decks = {decks[did] for (did,) in con.execute("select did from cards where nid = ?", (nid,))}
            fields = flds.split("\x1f")
            notes[fields[0]] = {
                "guid": guid,
                "model": models[mid],
                "mid": mid,
                "fields": fields,
                "tags": tags.split(),
                "decks": card_decks,
            }
    finally:
        con.close()
    return {"notes": notes, "models": models, "decks": set(decks.values()), "media": media, "files": names}


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """The example course copied to a temp dir, prepared, validated and built twice."""
    course = tmp_path_factory.mktemp("example") / "linear-algebra"
    shutil.copytree(EXAMPLE, course)
    prepare = run("slides.py", "prepare", str(course / "L03-slides.pdf"))
    validate = run("validate.py", str(course), "--lecture", "L03")
    run("build_deck.py", str(course), "--lecture", "L03")
    apkg = course / "Anki" / "build" / "LinAlg-L03.apkg"
    first = read_apkg(apkg, tmp_path_factory.mktemp("apkg1"))
    run("build_deck.py", str(course), "--lecture", "L03")
    second = read_apkg(apkg, tmp_path_factory.mktemp("apkg2"))
    return SimpleNamespace(
        course=course, data=course / "Anki", prepare=prepare, validate=validate, first=first, second=second
    )


def test_prepare_renders_pages_and_finds_the_figures(built):
    out = built.data / "build" / "L03-slides"
    cands = json.loads((out / "candidates.json").read_text())
    assert cands["pages"] == 10
    # the vector plot, the raster image and the table; the logo repeated on every slide is filtered out
    assert {k: [(c["id"], c["kind"]) for c in v] for k, v in cands["slides"].items()} == {
        "5": [("f1", "vector")],
        "6": [("f1", "image")],
        "8": [("f1", "vector")],
    }
    assert len(list((out / "pages").glob("p*.png"))) == 10
    assert len(list((out / "contact").glob("p*.png"))) == 10
    assert "## Slide 7" in (out / "text.md").read_text()


def test_montage_tiles_the_pages(built):
    run("slides.py", "montage", str(built.data / "build" / "L03-slides"), "--per", "9", "--cols", "3", "--width", "300")
    sheets = sorted(p.name for p in (built.data / "build" / "L03-slides" / "montage").glob("*.png"))
    assert sheets == ["m001-009.png", "m010-010.png"]


def test_example_validates_cleanly(built):
    assert "10 cards in 1 file(s): 0 errors, 0 warnings" in built.validate.stdout


def test_build_writes_concepts_decks_and_report(built):
    concepts = (built.data / "concepts.md").read_text()
    assert "Active cards: 9, retired: 1" in concepts
    assert "L03-003 [theorem] low-rank {sheet L03.1}" in concepts
    assert "L03-010 [example] low-rank {exam practice}" in concepts
    assert "L03-008" not in concepts
    assert json.loads((built.data / "decks.json").read_text()) == {"L03": LECTURE_DECK, "exam-practice": EXAM_DECK}
    report = (built.data / "build" / "L03-report.md").read_text()
    assert "retired cards (delete in Anki via browser search `CardID:<id>`): LinAlg-L03-008" in report
    assert f'`"deck:{EXAM_DECK}" tag:Example::LinAlg::L03`' in report


def test_apkg_notes_note_types_and_decks(built):
    pkg = built.first
    assert sorted(pkg["notes"]) == ACTIVE_IDS
    assert pkg["models"] == {1085791534: "Lecture Basic", 1533792899: "Lecture Cloze"}
    assert {LECTURE_DECK, EXAM_DECK} <= pkg["decks"]
    assert pkg["notes"]["LinAlg-L03-003"]["model"] == "Lecture Cloze"
    assert pkg["notes"]["LinAlg-L03-001"]["model"] == "Lecture Basic"
    for cid in ACTIVE_IDS:
        expected = {EXAM_DECK} if cid == "LinAlg-L03-010" else {LECTURE_DECK}
        assert pkg["notes"][cid]["decks"] == expected, cid


def test_apkg_tags_fields_and_media(built):
    notes = built.first["notes"]
    assert all("Example::LinAlg::L03" in n["tags"] for n in notes.values())
    assert "Example::LinAlg::exam-practice" in notes["LinAlg-L03-010"]["tags"]
    assert "Example::LinAlg::sheet" in notes["LinAlg-L03-003"]["tags"]
    cloze_text, cloze_extra = notes["LinAlg-L03-003"]["fields"][1:3]
    assert "{{c1::\\sigma_{k+1} }}" in cloze_text
    assert cloze_extra.startswith("<i>On the exam sheet: L03.1 Eckart-Young-Mirsky</i>")
    basic = notes["LinAlg-L03-005"]["fields"]
    assert basic[4] == '<img src="LinAlg-L03-005.png">' and basic[5] == '<img src="LinAlg-L03-005-b.png">'
    assert basic[6] == "LinAlg \u00b7 L03 \u00b7 slide 8 \u00b7 Singular Value Decomposition"
    assert sorted(built.first["media"].values()) == [
        "LinAlg-L03-004.png",
        "LinAlg-L03-005-b.png",
        "LinAlg-L03-005.png",
        "LinAlg-L03-009-b.png",
    ]
    assert sorted((built.data / "media").glob("*.png")) == sorted(
        built.data / "media" / name for name in built.first["media"].values()
    )


def test_guids_are_stable_across_builds(built, tools):
    first = {cid: n["guid"] for cid, n in built.first["notes"].items()}
    second = {cid: n["guid"] for cid, n in built.second["notes"].items()}
    assert first == second
    genanki = pytest.importorskip("genanki")
    assert first == {cid: genanki.guid_for(cid) for cid in ACTIVE_IDS}


def test_releasing_a_lecture_files_its_exam_cards_in_the_lecture_deck(built, tools, tmp_path):
    course = tmp_path / "released"
    shutil.copytree(built.course, course)
    profile = course / "Anki" / "profile.md"
    profile.write_text(profile.read_text().replace("released: []", "released: [L03]"))
    res = tools.build_deck.build(course, "L03")
    pkg = read_apkg(res["apkg"], tmp_path)
    assert pkg["notes"]["LinAlg-L03-010"]["decks"] == {LECTURE_DECK}
    assert "Example::LinAlg::exam-practice" in pkg["notes"]["LinAlg-L03-010"]["tags"]


def test_deck_names_stay_frozen_after_a_title_change(built, tools, tmp_path):
    course = tmp_path / "renamed"
    shutil.copytree(built.course, course)
    cards = course / "Anki" / "cards" / "L03.yaml"
    cards.write_text(cards.read_text().replace("title: Singular Value Decomposition", "title: SVD and PCA"))
    res = tools.build_deck.build(course, "L03")
    assert LECTURE_DECK in res["decks"]
    assert json.loads((course / "Anki" / "decks.json").read_text())["L03"] == LECTURE_DECK


def test_build_refuses_a_course_with_validation_errors(built, tools, tmp_path):
    course = tmp_path / "broken"
    shutil.copytree(built.course, course)
    cards = course / "Anki" / "cards" / "L03.yaml"
    data = yaml.safe_load(cards.read_text())
    data["cards"][1]["id"] = data["cards"][0]["id"]
    cards.write_text(yaml.safe_dump(data, sort_keys=False))
    with pytest.raises(SystemExit, match="validation error"):
        tools.build_deck.build(course, "L03")


def test_proof_sheet_shows_every_card(built):
    run("proof_sheet.py", str(built.course), "--lecture", "L03")
    page = (built.data / "build" / "LinAlg-L03-proof.html").read_text()
    for n in range(1, 11):
        assert f"id='LinAlg-L03-{n:03d}'" in page
    assert "EXAM PRACTICE (held)" in page
    assert "RETIRED" in page
    assert "On the exam sheet: L03.1" in page
    assert "src='../media/LinAlg-L03-004.png'" in page


def test_proof_sheet_renders_in_headless_chromium(built, tools):
    pytest.importorskip("playwright.sync_api")
    page = tools.proof_sheet.write_proof(built.course, "L03")
    build = built.data / "build"
    try:
        res = tools.proof_sheet.check(page, build / "L03-check.json", 2, build / "proof", timeout_s=15)
    except Exception as e:  # no Chromium installed for Playwright
        pytest.skip(f"headless Chromium not available: {e}")
    assert res["cards"] == 10
    assert res["broken_images"] == []
    assert len(res["screenshots"]) == 2
    if res["mathjax"] != "ok":
        pytest.skip(f"MathJax could not load (offline?): {res['mathjax']}")
    assert res["mathjax_errors"] == []


@pytest.mark.skipif(not shutil.which("pdflatex"), reason="needs a LaTeX installation with pdflatex")
def test_summary_sheet_builds(built, tmp_path):
    course = tmp_path / "summary"
    shutil.copytree(built.course, course)
    run("summary.py", "init", str(course))
    run("summary.py", "build", str(course))
    sdir = course / "Summary"
    assert (sdir / "LinAlg-exam-sheet.pdf").stat().st_size > 1000
    assert (sdir / "LinAlg-reference.pdf").stat().st_size > 1000
    report = (sdir / "build" / "report.md").read_text()
    assert "| L03.1 | yes | Eckart-Young-Mirsky |" in report
    assert "| L03.2 | - | Existence of the SVD |" in report
    assert "| L03 |" in report  # the page budget was measured


def test_summary_lint_rejects_font_size_commands(tools, tmp_path):
    lectures = tmp_path / "lectures"
    lectures.mkdir()
    (lectures / "L01.tex").write_text(
        "\\lecture{L01}{T}\n\\begin{sheetblock}{L01.1}{Ok}\n{\\small tiny text}\n\\end{sheetblock}\n"
        "\\begin{sheetblock}{L01.1}{Again}\nx % \\footnotesize in a comment is fine\n\\end{sheetblock}\n"
        "\\begin{refblock}{L02.1}{Wrong file}\n\\begin{itemize}\n\\end{refblock}\n"
    )
    errors, _, blocks = tools.summary.lint(tmp_path)
    assert any("\\small" in e for e in errors)
    assert not any("\\footnotesize" in e for e in errors)
    assert any("duplicate block id L01.1" in e for e in errors)
    assert any("block id L02.1 does not belong to L01.tex" in e for e in errors)
    assert any("\\begin{itemize} of line" in e for e in errors)
    assert set(blocks) == {"L01.1", "L02.1"}


def test_example_slides_generator_matches_the_shipped_pdf(tools, tmp_path):
    import pymupdf

    fresh = tools.make_example_slides.build(tmp_path / "L03-slides.pdf")
    with pymupdf.open(str(fresh)) as a, pymupdf.open(str(EXAMPLE / "L03-slides.pdf")) as b:
        ca, cb = tools.slides.detect_candidates(a), tools.slides.detect_candidates(b)
        assert [p.get_text() for p in a] == [p.get_text() for p in b]
    assert ca == cb
