"""Unit tests for validate.py: the rules that keep a broken card file from being built."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest
import yaml

SKILL = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL / "scripts"


@pytest.fixture(scope="module")
def val():
    """Import scripts/validate.py without leaving it in sys.modules (other skills may own a 'validate')."""
    saved_path, saved_mod = list(sys.path), sys.modules.pop("validate", None)
    saved_bytecode, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    sys.path.insert(0, str(SCRIPTS))
    try:
        yield importlib.import_module("validate")
    finally:
        sys.modules.pop("validate", None)
        if saved_mod is not None:
            sys.modules["validate"] = saved_mod
        sys.path[:] = saved_path
        sys.dont_write_bytecode = saved_bytecode


def card(n: int, lecture: str = "L01", **kw) -> dict:
    c = {
        "id": f"Mod-{lecture}-{n:03d}",
        "type": "basic",
        "front": f"What is concept number {n} about, in terms of mechanism {n * 7}?",
        "back": f"Answer {n}.",
        "source": [1],
        "tags": ["type::definition", "topic::test"],
    }
    c.update(kw)
    return c


def make_course(
    root: Path,
    cards: list[dict],
    *,
    lecture: str = "L01",
    skipped: list | None = None,
    pages: int | None = 3,
    candidates: dict | None = None,
    profile: str = "",
) -> Path:
    """A course folder with Anki/profile.md, one card file and (optionally) a candidates.json for slides.pdf.

    The PDF itself is a stub: the validator only checks that it exists and reads page counts and figure
    candidates from candidates.json."""
    data = root / "Anki"
    (data / "cards").mkdir(parents=True, exist_ok=True)
    (data / "profile.md").write_text(f'---\nmodule: Mod\ndeck: "Test Deck"\n{profile}---\n# Test profile\n')
    (root / "slides.pdf").write_bytes(b"%PDF-1.4\n")
    if pages is not None:
        cdir = data / "build" / "slides"
        cdir.mkdir(parents=True, exist_ok=True)
        cands = {"pages": pages, "slides": candidates or {}}
        (cdir / "candidates.json").write_text(json.dumps(cands))
    lec = {
        "module": "Mod",
        "lecture": lecture,
        "title": "Test lecture",
        "source_pdf": "slides.pdf",
        "skipped": skipped if skipped is not None else [{"slides": [2, 3], "reason": "title, outline"}],
        "cards": cards,
    }
    (data / "cards" / f"{lecture}.yaml").write_text(yaml.safe_dump(lec, sort_keys=False))
    return root


def check(val, root: Path, lecture: str | None = None):
    rep, _ = val.check_module(root, lecture)
    return rep.errors, rep.warnings


def has(msgs: list[str], text: str) -> bool:
    return any(text in m for m in msgs)


def test_clean_course_has_no_errors_or_warnings(val, tmp_path):
    root = make_course(tmp_path, [card(1)])
    errors, warnings = check(val, root)
    assert errors == []
    assert warnings == []


def test_duplicate_id_in_one_file(val, tmp_path):
    root = make_course(tmp_path, [card(1), card(1, front="A different question about something else entirely?")])
    errors, _ = check(val, root)
    assert has(errors, "Mod-L01-001: duplicate id")


def test_duplicate_id_across_files_is_reported_for_the_requested_lecture(val, tmp_path):
    root = make_course(tmp_path, [card(1)])
    dup = card(1, lecture="L02", id="Mod-L01-001")
    (root / "Anki" / "cards" / "L02.yaml").write_text(
        yaml.safe_dump({"module": "Mod", "lecture": "L02", "title": "T", "cards": [dup]})
    )
    errors, _ = check(val, root, "L02")
    assert has(errors, "duplicate id")
    assert has(errors, "id lecture part L01 != L02")


def test_skipped_entry_without_reason_is_an_error(val, tmp_path):
    root = make_course(tmp_path, [card(1)], skipped=[{"slides": [2, 3]}])
    errors, _ = check(val, root)
    assert has(errors, "skipped entry 1 (slides [2, 3]) has no reason")


def test_skipped_entry_needs_a_list_of_slides(val, tmp_path):
    root = make_course(tmp_path, [card(1)], skipped=[{"slides": "2-3", "reason": "title"}])
    errors, _ = check(val, root)
    assert has(errors, "slides must be a non-empty list of slide numbers")


def test_slide_without_card_or_reason_is_a_warning(val, tmp_path):
    root = make_course(tmp_path, [card(1)], skipped=[{"slides": [2], "reason": "title"}])
    errors, warnings = check(val, root)
    assert errors == []
    assert has(warnings, "slides without cards and without a skipped: reason: [3]")


def test_figure_candidate_not_on_slide(val, tmp_path):
    cands = {"1": [{"id": "f1", "kind": "vector", "bbox": [0.1, 0.1, 0.5, 0.5]}]}
    fig = {"slide": 1, "candidate": "f2"}
    root = make_course(tmp_path, [card(1, figure=fig, tags=["type::figure"])], candidates=cands)
    errors, _ = check(val, root)
    assert has(errors, "figure candidate f2 not on slide 1; available: ['f1']")


def test_figure_slide_out_of_range(val, tmp_path):
    root = make_course(tmp_path, [card(1, figure_back={"slide": 9, "full": True})])
    errors, _ = check(val, root)
    assert has(errors, "figure_back.slide 9 outside 1..3")


def test_figure_needs_exactly_one_way_to_select_the_region(val, tmp_path):
    fig = {"slide": 1, "candidate": "f1", "clip": [0.1, 0.1, 0.5, 0.5]}
    cands = {"1": [{"id": "f1", "kind": "image", "bbox": [0.1, 0.1, 0.5, 0.5]}]}
    root = make_course(tmp_path, [card(1, figure_back=fig)], candidates=cands)
    errors, _ = check(val, root)
    assert has(errors, "figure_back needs exactly one of candidate / clip / full")


def test_figure_clip_must_be_a_normalised_box(val, tmp_path):
    root = make_course(tmp_path, [card(1, figure_back={"slide": 1, "clip": [0.5, 0.1, 0.2, 1.4]})])
    errors, _ = check(val, root)
    assert has(errors, "figure_back.clip must be [x0, y0, x1, y1]")


def test_figure_from_missing_pdf(val, tmp_path):
    root = make_course(tmp_path, [card(1, figure_back={"slide": 1, "full": True, "pdf": "solution.pdf"})])
    errors, _ = check(val, root)
    assert has(errors, "figure_back.pdf not found: solution.pdf")


def test_figure_on_front_wants_type_figure_tag(val, tmp_path):
    root = make_course(tmp_path, [card(1, figure={"slide": 1, "clip": [0.1, 0.1, 0.5, 0.5]})])
    errors, warnings = check(val, root)
    assert errors == []
    assert has(warnings, "figure on the front but no type::figure tag")


def test_bad_id_and_module_prefix(val, tmp_path):
    root = make_course(tmp_path, [card(1, id="Mod-L1-001"), card(2, id="Other-L01-002")])
    errors, _ = check(val, root)
    assert has(errors, "Mod-L1-001: id must look like Mod-L01-017")
    assert has(errors, "id module prefix Other != Mod")


def test_cloze_rules(val, tmp_path):
    no_deletion = {"id": "Mod-L01-001", "type": "cloze", "text": "No deletion here.", "source": [1]}
    with_front = {"id": "Mod-L01-002", "type": "cloze", "text": "A {{c1::b}}.", "front": "x", "source": [1]}
    root = make_course(tmp_path, [no_deletion, with_front])
    errors, _ = check(val, root)
    assert has(errors, "cloze text has no {{c1::...}} deletion")
    assert has(errors, "cloze card uses 'text'")


def test_unbalanced_math_and_raw_img(val, tmp_path):
    root = make_course(tmp_path, [card(1, back="\\(x^2 and <img src='a.png'>")])
    errors, _ = check(val, root)
    assert has(errors, "unbalanced \\( \\) inline math delimiters")
    assert has(errors, "raw <img> tags are not allowed")


def test_sheet_reference_must_point_at_a_summary_block(val, tmp_path):
    root = make_course(tmp_path, [card(1, sheet="L01.1")])
    errors, _ = check(val, root)
    assert has(errors, "sheet: L01.1 but the course has no Summary/lectures/ folder")

    lectures = root / "Summary" / "lectures"
    lectures.mkdir(parents=True)
    (lectures / "L01.tex").write_text(
        "\\lecture{L01}{Test}\n\\begin{sheetblock}{L01.1}{A formula}\n\\(x\\)\n\\end{sheetblock}\n"
        "\\begin{refblock}{L01.2}{Background}\ntext\n\\end{refblock}\n"
    )
    errors, warnings = check(val, root)
    assert errors == []
    assert not has(warnings, "reference-only")

    make_course(root, [card(1, sheet="L01.9"), card(2, sheet="L01.2")])
    errors, warnings = check(val, root)
    assert has(errors, "sheet: block L01.9 not found")
    assert has(warnings, "sheet: L01.2 is reference-only")


def test_card_citing_a_held_out_exam_is_an_error(val, tmp_path):
    root = make_course(
        tmp_path,
        [card(1, source_ref="Exam 2025 Q3"), card(2, source_ref="exam 2024 Q1")],
        profile='held_out_exams: ["Exam 2025"]\n',
    )
    errors, _ = check(val, root)
    assert has(errors, "Mod-L01-001: source_ref 'Exam 2025 Q3' cites an exam the profile holds out")
    assert not has(errors, "Mod-L01-002")


def test_stage_and_status_values(val, tmp_path):
    root = make_course(tmp_path, [card(1, stage="later"), card(2, status="deleted")])
    errors, _ = check(val, root)
    assert has(errors, "stage must be one of ['exam', 'first']")
    assert has(errors, "status must be one of ['active', 'retired']")


def test_profile_needs_module_and_deck(val, tmp_path):
    root = make_course(tmp_path, [card(1)])
    (root / "Anki" / "profile.md").write_text("---\nmodule: Mod\n---\n")
    with pytest.raises(SystemExit, match="deck"):
        val.load_module(root)
    (root / "Anki" / "profile.md").write_text('---\nmodule: "Bad id"\ndeck: D\n---\n')
    with pytest.raises(SystemExit, match="letters and digits"):
        val.load_module(root)


def test_course_folder_anki_folder_and_flat_folder_resolve(val, tmp_path):
    root = make_course(tmp_path / "course", [card(1)])
    assert val.load_module(root)["dir"] == (root / "Anki").resolve()
    assert val.load_module(root / "Anki")["root"] == root.resolve()
    flat = tmp_path / "flat"
    flat.mkdir()
    (flat / "profile.md").write_text("---\nmodule: Flat\ndeck: Flat deck\n---\n")
    assert val.load_module(flat)["dir"] == flat.resolve()


def test_released_must_list_lecture_ids(val, tmp_path):
    root = make_course(tmp_path, [card(1)], profile="exam_practice:\n  released: [3]\n")
    errors, _ = check(val, root)
    assert has(errors, "exam_practice.released must be a list of lecture ids")


def test_unknown_card_key_warns(val, tmp_path):
    root = make_course(tmp_path, [card(1, figureback={"slide": 1, "full": True})])
    _, warnings = check(val, root)
    assert has(warnings, "unknown key(s) ['figureback'] are ignored")


def test_recognition_fronts_and_near_duplicates_warn(val, tmp_path):
    a = card(1, front="Why does the gradient vanish in deep sigmoid networks?")
    b = card(2, front="Why does the gradient vanish in deep sigmoid networks ?")
    c = card(3, front="Is the SVD unique?")
    root = make_course(tmp_path, [a, b, c])
    _, warnings = check(val, root)
    assert has(warnings, "near-duplicate fronts: Mod-L01-001 ~ Mod-L01-002")
    assert has(warnings, "Mod-L01-003: yes/no question")


def test_requested_lecture_must_exist(val, tmp_path):
    root = make_course(tmp_path, [card(1)])
    with pytest.raises(SystemExit, match=r"no cards/L07\.yaml"):
        val.check_module(root, "L07")


def test_cli_exit_codes(val, tmp_path, capsys):
    root = make_course(tmp_path, [card(1)], skipped=[{"slides": [2], "reason": "title"}])
    assert val.main([str(root), "--lecture", "L01"]) == 0
    assert val.main([str(root), "--strict"]) == 1  # slide 3 is uncovered: a warning
    out = capsys.readouterr().out
    assert "| 3 | 0 | **not covered, no reason given** |" in out
    make_course(root, [card(1), card(1)])
    assert val.main([str(root), "--no-coverage"]) == 1
