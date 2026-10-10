#!/usr/bin/env python3
"""
validate.py: check the card files of a course before building.

usage: validate.py COURSE_DIR [--lecture L03] [--strict] [--no-coverage]

COURSE_DIR is the course folder: it holds the course material (any file names, any
sub-folders) and an Anki/ subfolder with profile.md and cards/*.yaml. Every source path
inside a card file is relative to COURSE_DIR, so the folder can move. Passing the Anki/
folder itself also works, and so does a flat folder with profile.md at its top.

Reports errors (the build refuses to run) and warnings (judgement calls that deserve a
second look), and prints a coverage table per lecture: which slides produced cards, which
were skipped with a reason, and which fell through the cracks.
Exit status 1 on errors, or on warnings with --strict.

Importable: load_module(), load_lecture(), lecture_files(), check_module(),
coverage_table(), load_summary_blocks(), tag_base().
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

import yaml

DATA_SUBDIR = "Anki"
SUMMARY_SUBDIR = "Summary"

MODULE_RE = re.compile(r"^[A-Za-z0-9]+$")
LECTURE_RE = re.compile(r"^(L|X)\d{2}$")
ID_RE = re.compile(r"^(?P<module>[A-Za-z0-9]+)-(?P<lecture>L\d{2}|X\d{2})-(?P<num>\d{3})$")
TAG_RE = re.compile(r"^[A-Za-z0-9_:\-\.\+]+$")
CLOZE_RE = re.compile(r"\{\{c(\d+)::")
SHEET_ID_RE = re.compile(r"^(L|X)\d{2}\.\d+$")
BLOCK_RE = re.compile(r"\\begin\{(sheetblock|refblock)\}\{([^{}]*)\}\{([^{}]*)\}")

CARD_TYPES = {"basic", "cloze"}
STATUSES = {"active", "retired"}
STAGES = {"first", "exam"}  # first pass (default) | exam practice (held back until released)
SIDES = {"front", "back"}
TYPE_TAGS = {
    "type::definition",
    "type::theorem",
    "type::mechanism",
    "type::derivation",
    "type::procedure",
    "type::contrast",
    "type::figure",
    "type::code",
    "type::example",
    "type::pitfall",
    "type::intuition",
}
LONG_OK_TAGS = {"type::derivation", "type::procedure", "type::example"}
CARD_KEYS = {
    "id",
    "type",
    "front",
    "back",
    "text",
    "extra",
    "figure",
    "figure_back",
    "source",
    "source_ref",
    "tags",
    "contrast",
    "stage",
    "sheet",
    "status",
}
FIGURE_KEYS = {"slide", "candidate", "clip", "full", "side", "mask", "pdf", "pad"}


# ----------------------------------------------------------------------------
# loading
# ----------------------------------------------------------------------------


def read_front_matter(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        return {}
    try:
        data = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        raise SystemExit(f"{path}: front matter is not valid YAML: {e}") from e
    if not isinstance(data, dict):
        raise SystemExit(f"{path}: front matter must be a mapping")
    return data


def resolve_module(path: Path) -> tuple[Path, Path]:
    """Return (data_dir, root) for a course folder, its Anki/ subfolder, or a flat folder.

    data_dir holds profile.md, cards/, media/, build/, concepts.md and decks.json;
    root is the folder that source paths in card files are relative to."""
    path = Path(path).resolve()
    if (path / DATA_SUBDIR / "profile.md").exists():
        return path / DATA_SUBDIR, path
    if path.name == DATA_SUBDIR and (path / "profile.md").exists():
        return path, path.parent
    return path, path  # flat layout: profile.md, cards/ and the sources in one folder


def tag_base(module: dict) -> str:
    """Prefix of the generated tags: '<tag_prefix>::<module>' or just '<module>'."""
    return f"{module['tag_prefix']}::{module['id']}" if module.get("tag_prefix") else module["id"]


def load_module(module_dir: Path) -> dict:
    data_dir, root = resolve_module(module_dir)
    profile = data_dir / "profile.md"
    if not profile.exists():
        raise SystemExit(
            f"{Path(module_dir)}: no {DATA_SUBDIR}/profile.md here; pass the course folder "
            f"(the folder that contains {DATA_SUBDIR}/profile.md)"
        )
    fm = read_front_matter(profile)
    module_id = str(fm.get("module") or "").strip()
    if not MODULE_RE.match(module_id):
        raise SystemExit(f"{profile}: front matter needs module: <id> (letters and digits only, e.g. LinAlg)")
    deck = str(fm.get("deck") or "").strip()
    if not deck or deck.startswith("::") or deck.endswith("::"):
        raise SystemExit(f'{profile}: front matter needs deck: <Anki deck name> (e.g. "Linear Algebra")')
    prefix = str(fm.get("tag_prefix") or "").strip()
    if prefix and not TAG_RE.match(prefix):
        raise SystemExit(f"{profile}: tag_prefix {prefix!r} may contain letters, digits and :: _ - . + only")
    return {
        "dir": data_dir,
        "root": root,
        "id": module_id,
        "deck": deck,
        "tag_prefix": prefix.strip(":"),
        "subdecks": bool(fm.get("subdecks", True)),  # one Anki subdeck per lecture file
        "profile": fm,
    }


def load_lecture(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        try:
            data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise SystemExit(f"{path}: not valid YAML: {e}") from e
    if not isinstance(data, dict):
        raise SystemExit(f"{path}: top level must be a mapping")
    data["_path"] = Path(path)
    data["cards"] = data.get("cards") or []
    data["skipped"] = data.get("skipped") or []
    return data


def lecture_files(module_dir: Path, lecture: str | None = None) -> list[Path]:
    data_dir = resolve_module(module_dir)[0]
    cards_dir = data_dir / "cards"
    files = sorted(cards_dir.glob("*.yaml")) if cards_dir.exists() else []
    if lecture:
        files = [p for p in files if p.stem == lecture]
        if not files:
            raise SystemExit(f"no cards/{lecture}.yaml in {data_dir}")
    return files


def load_candidates(data_dir: Path, pdf_rel: str | None) -> dict | None:
    """candidates.json lives in build/<pdf stem>/ (written by slides.py prepare)."""
    if not pdf_rel:
        return None
    p = Path(data_dir) / "build" / Path(pdf_rel).stem / "candidates.json"
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def load_summary_blocks(root: Path) -> dict[str, dict] | None:
    """Blocks of the course summary (COURSE_DIR/Summary/lectures/*.tex), or None if the course has none.

    Returns {block id: {"on_sheet": bool, "title": str, "file": name}}. A sheetblock is printed on the exam
    sheet and in the reference; a refblock only in the reference (see summary.py)."""
    d = Path(root) / SUMMARY_SUBDIR / "lectures"
    if not d.is_dir():
        return None
    out: dict[str, dict] = {}
    for p in sorted(d.glob("*.tex")):
        for m in BLOCK_RE.finditer(p.read_text(encoding="utf-8")):
            out[m.group(2).strip()] = {
                "on_sheet": m.group(1) == "sheetblock",
                "title": m.group(3).strip(),
                "file": p.name,
            }
    return out


# ----------------------------------------------------------------------------
# checks
# ----------------------------------------------------------------------------


class Report:
    def __init__(self):
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def err(self, where, msg):
        self.errors.append(f"{where}: {msg}")

    def warn(self, where, msg):
        self.warnings.append(f"{where}: {msg}")


def _text_fields(card: dict) -> list[tuple[str, str]]:
    return [(k, card[k]) for k in ("front", "back", "extra", "text") if isinstance(card.get(k), str)]


def _is_box(x) -> bool:
    return isinstance(x, list) and len(x) == 4 and all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in x)


def _check_math(where, key, s, rep: Report):
    if s.count("\\(") != s.count("\\)"):
        rep.err(where, f"{key}: unbalanced \\( \\) inline math delimiters")
    if s.count("\\[") != s.count("\\]"):
        rep.err(where, f"{key}: unbalanced \\[ \\] display math delimiters")
    # $ delimiters are accepted (the builder converts them) but must pair up
    if len(re.findall(r"(?<!\\)\$", s)) % 2:
        rep.err(where, f"{key}: odd number of $ signs; escape a literal dollar as \\$")
    if "\\begin{align}" in s or "\\begin{equation}" in s:
        rep.warn(where, f"{key}: use \\begin{{aligned}} inside \\[ \\] instead of align/equation environments")
    if re.search(r"<img\s", s):
        rep.err(where, f"{key}: raw <img> tags are not allowed; use the figure: block")
    if key == "front" and len(s) > 400 and re.search(r"\n\s*\n", s.strip()):
        rep.warn(where, "front is long and multi-paragraph; split the card or move context to extra")


def _check_figure(where, fkey, fig, default_side, n_pages, cands, tags, rep: Report, module: dict):
    if not isinstance(fig, dict):
        rep.err(where, f"{fkey} must be a mapping {{slide, candidate|clip|full, side?, mask?, pdf?}}")
        return
    unknown = sorted(set(fig) - FIGURE_KEYS)
    if unknown:
        rep.warn(where, f"{fkey}: unknown key(s) {unknown} are ignored")
    if fig.get("pdf"):
        other = module["root"] / str(fig["pdf"])
        if not other.exists():
            rep.err(where, f"{fkey}.pdf not found: {fig['pdf']} (paths are relative to the course folder)")
            return
        import pymupdf  # local import: only needed for figures from other files

        with pymupdf.open(str(other)) as doc:
            n_pages = len(doc)
        cands = load_candidates(module["dir"], str(fig["pdf"]))
    sl = fig.get("slide")
    if not isinstance(sl, int) or isinstance(sl, bool):
        rep.err(where, f"{fkey}.slide must be a slide (page) number")
        sl = None
    elif n_pages and not 1 <= sl <= n_pages:
        rep.err(where, f"{fkey}.slide {sl} outside 1..{n_pages}")
    how = [k for k in ("candidate", "clip", "full") if fig.get(k)]
    if len(how) != 1:
        rep.err(where, f"{fkey} needs exactly one of candidate / clip / full")
    if fig.get("candidate") and sl is not None:
        if cands is None:
            rep.warn(where, f"{fkey}: no candidates.json yet; run slides.py prepare before building")
        else:
            ids = [c["id"] for c in cands.get("slides", {}).get(str(sl), [])]
            if fig["candidate"] not in ids:
                rep.err(
                    where, f"{fkey} candidate {fig['candidate']} not on slide {sl}; available: {ids} (or use clip:)"
                )
    clip = fig.get("clip")
    if clip is not None and not (_is_box(clip) and clip[0] < clip[2] and clip[1] < clip[3]):
        rep.err(where, f"{fkey}.clip must be [x0, y0, x1, y1] normalised 0..1 with x0 < x1 and y0 < y1")
    side = fig.get("side", default_side)
    if side not in SIDES:
        rep.err(where, f"{fkey}.side must be front or back")
    masks = fig.get("mask") or []
    if not isinstance(masks, list) or not all(_is_box(mk) for mk in masks):
        rep.err(where, f"each {fkey}.mask entry must be [x0, y0, x1, y1] normalised to the figure")
    if fig.get("full") and side == "front":
        rep.warn(
            where,
            "full slide on the front: the slide text usually gives the answer away; crop or mask, or use the back",
        )
    if side == "front" and "type::figure" not in tags:
        rep.warn(where, "figure on the front but no type::figure tag")


def _check_skipped(where0, lec, n_pages, rep: Report) -> dict[int, str]:
    skipped: dict[int, str] = {}
    entries = lec.get("skipped")
    if not isinstance(entries, list):
        rep.err(where0, "skipped must be a list of {slides: [..], reason: ..}")
        return skipped
    for i, s in enumerate(entries, 1):
        if not isinstance(s, dict):
            rep.err(where0, f"skipped entry {i} must be a mapping {{slides: [..], reason: ..}}")
            continue
        nums = s.get("slides", s.get("pages"))
        if not isinstance(nums, list) or not nums or not all(isinstance(n, int) for n in nums):
            rep.err(where0, f"skipped entry {i}: slides must be a non-empty list of slide numbers")
            nums = []
        reason = str(s.get("reason") or "").strip()
        if not reason:
            rep.err(where0, f"skipped entry {i} (slides {nums}) has no reason; every skipped slide needs one")
        for n in nums:
            if n_pages and not 1 <= n <= n_pages:
                rep.err(where0, f"skipped slide {n} outside 1..{n_pages}")
            skipped[n] = reason
    return skipped


def _check_card_text(where, card, ctype, tags, front, back, rep: Report):
    """Soft rules: recall speed, recognition fronts, context leaks, enumerations."""
    long_ok = any(t in LONG_OK_TAGS for t in tags)
    if len(front) > 320 and not card.get("figure"):
        rep.warn(where, f"front is {len(front)} chars; can it be answered in 5-10 s?")
    if len(back) > 800 and not long_ok:
        rep.warn(where, f"back is {len(back)} chars without a derivation/procedure/example tag; split or tag")
    if len(str(card.get("extra") or "")) > 700:
        rep.warn(where, "extra is very long; keep it to the one insight that helps encoding")
    if ctype != "basic" or card.get("figure"):
        return
    if re.match(r"^\s*(Is|Are|Does|Do|Can|Did|Was|Were|Has|Have)\b", front):
        rep.warn(where, "yes/no question; rephrase so the answer must be produced, not recognised")
    if re.search(r"\b(this slide|the slide|above|below|the following)\b", front, re.I):
        rep.warn(where, "front refers to 'this slide/the following' without a figure; it will not make sense alone")
    if len(re.findall(r"(^|\n)\s*(?:[-*]|\d+\.)\s+", back)) >= 6:
        rep.warn(where, "answer is a list of 6+ items; enumeration cards are weak, split or restructure")


def _check_sheet(where, card, status, module, rep: Report):
    refs = card["sheet"] if isinstance(card["sheet"], list) else [card["sheet"]]
    blocks = module.get("_blocks")
    for r in map(str, refs):
        if not SHEET_ID_RE.match(r):
            rep.err(where, f"sheet: {r!r} must be a summary block id such as L01.3")
        elif blocks is None:
            rep.err(where, f"sheet: {r} but the course has no {SUMMARY_SUBDIR}/lectures/ folder")
        elif r not in blocks:
            rep.err(where, f"sheet: block {r} not found in {SUMMARY_SUBDIR}/lectures/*.tex")
        elif not blocks[r]["on_sheet"] and status == "active":
            rep.warn(
                where,
                f"sheet: {r} is reference-only, so it is not on the exam sheet; restore full recall on this card "
                f"or put the block back on the sheet",
            )


def check_lecture(
    module: dict,
    lec: dict,
    rep: Report,
    all_ids: dict[str, str],
    fronts: list[tuple[str, str]],
    module_ids: set[str] | None = None,
):
    path = lec["_path"]
    where0 = path.name
    lecture_id = str(lec.get("lecture") or "")
    if not LECTURE_RE.match(lecture_id):
        rep.err(where0, "missing/invalid 'lecture' (expected e.g. L03; X01 for material that is not a lecture)")
        lecture_id = path.stem
    if path.stem != lecture_id:
        rep.err(where0, f"file name {path.stem} does not match lecture: {lecture_id}")
    if lec.get("module") is not None and str(lec["module"]) != module["id"]:
        rep.err(where0, f"module: {lec['module']} does not match the profile's module: {module['id']}")
    if not lec.get("title"):
        rep.warn(where0, "no 'title'")
    src = lec.get("source_pdf")
    if src and not (module["root"] / src).exists():
        rep.err(where0, f"source_pdf not found: {src} (paths are relative to the course folder {module['root'].name}/)")
    cands = load_candidates(module["dir"], src)
    n_pages = cands["pages"] if cands else None
    if src and cands is None:
        rep.warn(
            where0,
            f"no build/{Path(src).stem}/candidates.json; run slides.py prepare {src} first "
            f"(needed for figure candidates and the coverage table)",
        )
    held_out = [str(x).lower() for x in (module["profile"].get("held_out_exams") or []) if str(x).strip()]

    # pages: [first, last] marks the part of a shared source (a script or textbook PDF) that belongs to this
    # lecture. Coverage is then judged for that range only; cards may still cite pages outside it (warning).
    page_range = lec.get("pages")
    if page_range is not None:
        if not (
            isinstance(page_range, list)
            and len(page_range) == 2
            and all(isinstance(x, int) for x in page_range)
            and 1 <= page_range[0] <= page_range[1]
        ):
            rep.err(where0, "pages must be [first, last] (numbers, first <= last)")
            page_range = None
        elif n_pages and page_range[1] > n_pages:
            rep.err(where0, f"pages {page_range} exceed the {n_pages} pages of {src}")
            page_range = None
    unit = "page" if page_range else "slide"

    covered: dict[int, list[str]] = {}
    skipped = _check_skipped(where0, lec, n_pages, rep)

    cards = lec.get("cards")
    if not isinstance(cards, list):
        rep.err(where0, "cards must be a list")
        cards = []
    seen_local: set[str] = set()
    file_ids = {str(c.get("id")) for c in cards if isinstance(c, dict)}
    for i, card in enumerate(cards):
        if not isinstance(card, dict):
            rep.err(where0, f"card #{i + 1} is not a mapping")
            continue
        cid = str(card.get("id", f"<card #{i + 1}>"))
        where = f"{where0} {cid}"
        m = ID_RE.match(cid)
        if not m:
            rep.err(where, f"id must look like {module['id']}-{lecture_id}-017")
        else:
            if m.group("module") != module["id"]:
                rep.err(where, f"id module prefix {m.group('module')} != {module['id']}")
            if m.group("lecture") != lecture_id:
                rep.err(where, f"id lecture part {m.group('lecture')} != {lecture_id}")
        if cid in seen_local or cid in all_ids:
            rep.err(where, f"duplicate id (also in {all_ids.get(cid, where0)})")
        seen_local.add(cid)
        all_ids.setdefault(cid, where0)

        unknown = sorted(set(card) - CARD_KEYS)
        if unknown:
            rep.warn(where, f"unknown key(s) {unknown} are ignored")
        ctype = card.get("type", "basic")
        if ctype not in CARD_TYPES:
            rep.err(where, f"type must be one of {sorted(CARD_TYPES)}")
        status = card.get("status", "active")
        if status not in STATUSES:
            rep.err(where, f"status must be one of {sorted(STATUSES)}")
        if "stage" in card and card["stage"] not in STAGES:
            rep.err(where, f"stage must be one of {sorted(STAGES)} (first = default, exam = exam practice)")
        if card.get("sheet") is not None:
            _check_sheet(where, card, status, module, rep)

        if ctype == "cloze":
            text = str(card.get("text") or "")
            if not text.strip():
                rep.err(where, "cloze card needs 'text'")
            elif not CLOZE_RE.search(text):
                rep.err(where, "cloze text has no {{c1::...}} deletion")
            if card.get("front") or card.get("back"):
                rep.err(where, "cloze card uses 'text' (+ optional 'extra'), not front/back")
            if "}}}" in text:
                rep.warn(
                    where,
                    "'}}}' in cloze text; the builder inserts a space, but check that the deletion boundary is "
                    "where you intend",
                )
            nums = sorted({int(n) for n in CLOZE_RE.findall(text)})
            if nums and nums != list(range(1, len(nums) + 1)):
                rep.warn(where, f"cloze numbers are {nums}; expected 1..n without gaps")
            if len(nums) > 4:
                rep.warn(where, f"{len(nums)} cloze deletions in one note; is every one a distinct retrieval?")
        else:
            for k in ("front", "back"):
                if not str(card.get(k) or "").strip():
                    rep.err(where, f"basic card needs a non-empty '{k}'")
            if card.get("text"):
                rep.err(where, "basic card must not have 'text' (that is for cloze)")

        for k, s in _text_fields(card):
            _check_math(where, k, s, rep)

        tags = card.get("tags") or []
        if not isinstance(tags, list):
            rep.err(where, "tags must be a list")
            tags = []
        tags = [str(t) for t in tags]
        for t in tags:
            if not TAG_RE.match(t):
                rep.err(where, f"bad tag {t!r} (letters, digits, :: _ - . + only)")
        type_tags = [t for t in tags if t.startswith("type::")]
        if not type_tags:
            rep.warn(where, "no type:: tag (" + ", ".join(sorted(t[6:] for t in TYPE_TAGS)) + ")")
        for t in type_tags:
            if t not in TYPE_TAGS:
                rep.warn(where, f"unusual type tag {t}")

        front = str(card.get("front") or card.get("text") or "")
        back = str(card.get("back") or "")
        _check_card_text(where, card, ctype, tags, front, back, rep)

        # sources: slide numbers and/or a free-text reference
        srcs = card.get("source")
        source_ref = str(card.get("source_ref") or "")
        if srcs is None and not source_ref:
            rep.warn(where, f"no 'source' {unit} numbers and no 'source_ref' (e.g. \"Exercise 3, Problem 2\")")
        if held_out and source_ref and any(h in source_ref.lower() for h in held_out):
            if status == "active":
                rep.err(where, f"source_ref {source_ref!r} cites an exam the profile holds out for a mock")
            else:
                rep.warn(where, "retired card cites a held-out exam; make sure its fields are placeholders")
        if srcs is None:
            srcs = []
        if not isinstance(srcs, list):
            srcs = [srcs]
        for s in srcs:
            if not isinstance(s, int) or isinstance(s, bool):
                rep.err(where, f"source entries must be {unit} numbers, got {s!r}")
                continue
            if n_pages and not 1 <= s <= n_pages:
                rep.err(where, f"source {unit} {s} outside 1..{n_pages}")
            elif page_range and not page_range[0] <= s <= page_range[1]:
                rep.warn(where, f"source {unit} {s} lies outside this lecture's pages {page_range}")
            covered.setdefault(s, []).append(cid)

        # figures (figure: defaults to the front, figure_back: to the back)
        figs = {}
        for fkey, default_side in (("figure", "front"), ("figure_back", "back")):
            fig = card.get(fkey)
            if fig is None:
                continue
            _check_figure(where, fkey, fig, default_side, n_pages, cands, tags, rep, module)
            if isinstance(fig, dict):
                figs[fkey] = fig.get("side", default_side)
        if len(figs) == 2 and figs["figure"] == figs["figure_back"]:
            rep.err(where, "figure and figure_back end up on the same side")
        if figs and not src and not all(isinstance(card.get(k), dict) and card[k].get("pdf") for k in figs):
            rep.err(where, "figure without a pdf: and the lecture has no source_pdf")

        contrast = card.get("contrast") or []
        if not isinstance(contrast, list):
            contrast = [contrast]
        for c in contrast:
            # contrast links go both ways, so an earlier lecture may point at a later one: resolve module-wide
            if str(c) not in all_ids and str(c) not in file_ids and str(c) not in (module_ids or set()):
                rep.warn(where, f"contrast id {c} unknown in this module")

        if status == "active":
            fronts.append((cid, re.sub(r"\s+", " ", front.lower())))

    # coverage
    if n_pages:
        lo, hi = (page_range[0], page_range[1]) if page_range else (1, n_pages)
        uncovered = [n for n in range(lo, hi + 1) if n not in covered and n not in skipped]
        both = sorted(set(covered) & set(skipped))
        if uncovered:
            rep.warn(where0, f"{unit}s without cards and without a skipped: reason: {uncovered}")
        if both:
            rep.warn(where0, f"{unit}s listed as skipped but also cited by cards: {both}")
    lec["_range"] = page_range
    lec["_unit"] = unit
    return covered, skipped, n_pages


def _without_numbers(t: str) -> str:
    return re.sub(r"[\d\^{}()\\]+", "", t)


def near_duplicates(fronts: list[tuple[str, str]], thr: float = 0.86) -> list[tuple[str, str, float]]:
    """Fronts that read alike. A deliberate series whose fronts differ only in numbers or symbols
    (10^15 / 10^18 ...) is not reported."""
    out = []
    for i in range(len(fronts)):
        for j in range(i + 1, len(fronts)):
            a, b = fronts[i][1], fronts[j][1]
            if abs(len(a) - len(b)) > max(len(a), len(b)) * 0.5:
                continue
            if a != b and _without_numbers(a) == _without_numbers(b):
                continue
            r = difflib.SequenceMatcher(None, a, b).ratio()
            if r >= thr:
                out.append((fronts[i][0], fronts[j][0], round(r, 2)))
    return out


def check_profile(module: dict, rep: Report) -> None:
    fm = module["profile"]
    released = (fm.get("exam_practice") or {}).get("released") or []
    if not isinstance(released, list) or not all(LECTURE_RE.match(str(x)) for x in released):
        rep.err("profile.md", "exam_practice.released must be a list of lecture ids such as [L01, L02]")
    held = fm.get("held_out_exams")
    if held is not None and not (isinstance(held, list) and all(isinstance(x, (str, int)) for x in held)):
        rep.err("profile.md", "held_out_exams must be a list of names as they appear in source_ref, e.g. [Exam 2025]")


def check_module(module_dir: Path, lecture: str | None = None) -> tuple[Report, list[dict]]:
    module = load_module(module_dir)
    module["_blocks"] = load_summary_blocks(module["root"])
    rep = Report()
    check_profile(module, rep)
    all_ids: dict[str, str] = {}
    fronts: list[tuple[str, str]] = []
    lectures = []
    if lecture:
        lecture_files(module["dir"], lecture)  # exits if the requested file does not exist
    loaded = [(p, load_lecture(p)) for p in lecture_files(module["dir"])]
    module_ids = {str(c.get("id")) for _, lec in loaded for c in lec["cards"] if isinstance(c, dict)}
    # always check every lecture (ids must be unique module-wide); report only the requested one in detail
    for p, lec in loaded:
        sub = Report()
        covered, skipped, n_pages = check_lecture(module, lec, sub, all_ids, fronts, module_ids)
        lec["_coverage"] = (covered, skipped, n_pages)
        if lecture is None or p.stem == lecture:
            rep.errors += sub.errors
            rep.warnings += sub.warnings
            lectures.append(lec)
        else:
            rep.errors += [e for e in sub.errors if "duplicate id" in e]
    for a, b, r in near_duplicates(fronts):
        if lecture is None or f"-{lecture}-" in a or f"-{lecture}-" in b:
            rep.warnings.append(f"near-duplicate fronts: {a} ~ {b} (similarity {r}); merge, or sharpen the contrast")
    return rep, lectures


def coverage_table(lec: dict) -> str:
    covered, skipped, n_pages = lec.get("_coverage", ({}, {}, None))
    if not n_pages:
        return "(no candidates.json; run slides.py prepare to enable the coverage table)"
    lo, hi = lec.get("_range") or (1, n_pages)
    rows = [f"| {lec.get('_unit', 'slide')} | cards | note |", "|---|---|---|"]
    for n in sorted(n for n in covered if not lo <= n <= hi):
        rows.append(f"| {n} (outside {lo}-{hi}) | {len(covered[n])} | {', '.join(covered[n])} |")
    for n in range(lo, hi + 1):
        if n in covered:
            rows.append(f"| {n} | {len(covered[n])} | {', '.join(covered[n])} |")
        elif n in skipped:
            rows.append(f"| {n} | - | skipped: {skipped[n]} |")
        else:
            rows.append(f"| {n} | 0 | **not covered, no reason given** |")
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("course_dir")
    ap.add_argument("--lecture", help="report one lecture file in detail, e.g. L03 (ids are checked module-wide)")
    ap.add_argument("--strict", action="store_true", help="exit 1 on warnings too")
    ap.add_argument("--no-coverage", action="store_true", help="do not print the coverage table")
    args = ap.parse_args(argv)
    rep, lectures = check_module(Path(args.course_dir), args.lecture)
    n_cards = sum(len(lec["cards"]) for lec in lectures)
    for e in rep.errors:
        print("ERROR  ", e)
    for w in rep.warnings:
        print("WARNING", w)
    if not args.no_coverage:
        for lec in lectures:
            print(f"\n### Coverage {lec.get('lecture')}: {lec.get('title', '')}")
            print(coverage_table(lec))
    print(f"\n{n_cards} cards in {len(lectures)} file(s): {len(rep.errors)} errors, {len(rep.warnings)} warnings")
    return 1 if rep.errors or (args.strict and rep.warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
