#!/usr/bin/env python3
"""
build_deck.py: turn a course's card files into an Anki package (.apkg).

usage: build_deck.py COURSE_DIR (--lecture L03 | --all) [--out DIR] [--dpi 220]
       build_deck.py COURSE_DIR --concepts-only

COURSE_DIR is the course folder; the card data lives in COURSE_DIR/Anki/ (below: DATA)
and the outputs are written there. Source paths in card files are relative to COURSE_DIR.

What it does
  1. validates cards/*.yaml (stops on errors; warnings are printed)
  2. cuts every referenced figure out of its PDF into DATA/media/ (cached: a figure is
     only re-cut when its spec changed)
  3. converts Markdown + \\( math \\) to HTML (Anki renders MathJax natively)
  4. writes DATA/build/<Module>-<Lecture>.apkg (or <Module>-ALL.apkg) with stable note
     GUIDs derived from the card id, so re-importing an updated build updates the existing
     notes instead of duplicating them (choose "Update notes: Always" when re-importing)
  5. regenerates DATA/concepts.md, the compact cross-lecture index that the next session
     reads before writing new cards
  6. writes DATA/build/<Lecture>-report.md (counts, coverage, retired cards that still have
     to be deleted in Anki, import instructions)

Decks: the course deck is `deck:` in the profile. Unless the profile says `subdecks: false`,
every lecture file gets its own subdeck "<deck>::<Lxx> <short title>". The subdeck name is
fixed at the first build and recorded in DATA/decks.json, because Anki keys decks by name:
a renamed subdeck would become a second deck. Re-imports never move existing cards.

Exam practice: a card with `stage: exam` goes into "<deck>::Exam practice" (frozen in
decks.json under "exam-practice") and gets the tag <base>::exam-practice, where <base> is
"<tag_prefix>::<module>" (or just "<module>" without a tag_prefix). Once a lecture is listed
in the profile's exam_practice.released, its exam cards are filed into its own subdeck.

Summary sheet: a card with `sheet: L01.3` whose block is on the exam sheet gets the tag
<base>::sheet and a first line in Extra naming the block.

Note types: "Lecture Basic" and "Lecture Cloze" (fixed model ids, shared by all courses).
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import genanki
import markdown

sys.path.insert(0, str(Path(__file__).resolve().parent))
import slides as slides_mod
import validate as val

# Fixed ids: Anki identifies note types by id, so these must never change once cards are imported.
MODEL_ID_BASIC = 1085791534
MODEL_ID_CLOZE = 1533792899
MODEL_NAME_BASIC = "Lecture Basic"
MODEL_NAME_CLOZE = "Lecture Cloze"
SEP = " \u00b7 "  # middle dot between the parts of the source line printed on every card

CSS = """
.card { font-family: -apple-system, "Helvetica Neue", Helvetica, Arial, sans-serif; font-size: 20px;
        line-height: 1.45; color: #1c1c1e; background: #ffffff; text-align: left; max-width: 780px;
        margin: 0 auto; padding: 8px 14px; }
.night_mode .card, .nightMode .card { color: #e8e8ea; background: #1f1f21; }
.q p:first-child, .a p:first-child, .extra p:first-child { margin-top: 0; }
.q p:last-child, .a p:last-child, .extra p:last-child { margin-bottom: 0; }
hr#answer { border: 0; border-top: 1px solid #c8c8cc; margin: 14px 0; }
.night_mode hr#answer { border-top-color: #48484a; }
.extra { margin-top: 14px; padding: 8px 12px; border-left: 3px solid #a0a0a5; color: #48484a; font-size: 0.88em; }
.night_mode .extra { color: #b8b8bd; border-left-color: #6e6e73; }
.fig { text-align: center; margin: 10px 0; }
.fig img { max-width: 100%; max-height: 62vh; height: auto; border-radius: 4px; background: #fff; }
.src { margin-top: 16px; font-size: 0.7em; color: #8e8e93; text-align: right; }
code { font-family: "SF Mono", Menlo, Consolas, monospace; font-size: 0.86em; background: rgba(127,127,127,0.14);
       padding: 1px 4px; border-radius: 3px; }
pre { background: rgba(127,127,127,0.12); padding: 10px 12px; border-radius: 6px; overflow-x: auto;
      text-align: left; font-size: 0.86em; line-height: 1.35; }
pre code { background: none; padding: 0; font-size: 1em; }
table { border-collapse: collapse; margin: 8px auto; font-size: 0.9em; }
th, td { border: 1px solid #c8c8cc; padding: 4px 10px; vertical-align: top; }
th { background: rgba(127,127,127,0.12); }
.cloze { font-weight: 600; color: #0a84ff; }
.night_mode .cloze { color: #5eaaff; }
ul, ol { padding-left: 1.3em; margin: 6px 0; }
li { margin: 2px 0; }
blockquote { margin: 6px 0; padding-left: 10px; border-left: 3px solid #c8c8cc; color: #6e6e73; }
"""

FIGURE_BACK = '{{#FigureBack}}<div class="fig">{{FigureBack}}</div>{{/FigureBack}}'
EXTRA = '{{#Extra}}<div class="extra">{{Extra}}</div>{{/Extra}}'
SRC_LINE = '<div class="src">{{Source}}' + SEP + "{{CardID}}</div>"
BASIC_FRONT = '<div class="q">{{Front}}</div>\n{{#Figure}}<div class="fig">{{Figure}}</div>{{/Figure}}'
BASIC_BACK = "\n".join([BASIC_FRONT, "<hr id=answer>", '<div class="a">{{Back}}</div>', FIGURE_BACK, EXTRA, SRC_LINE])
CLOZE_FRONT = '<div class="q">{{cloze:Text}}</div>\n{{#Figure}}<div class="fig">{{Figure}}</div>{{/Figure}}'
CLOZE_BACK = "\n".join([CLOZE_FRONT, FIGURE_BACK, EXTRA, SRC_LINE])

BASIC_MODEL = genanki.Model(
    MODEL_ID_BASIC,
    MODEL_NAME_BASIC,
    fields=[{"name": n} for n in ("CardID", "Front", "Back", "Extra", "Figure", "FigureBack", "Source")],
    templates=[{"name": "Card 1", "qfmt": BASIC_FRONT, "afmt": BASIC_BACK}],
    css=CSS,
    sort_field_index=1,
)
CLOZE_MODEL = genanki.Model(
    MODEL_ID_CLOZE,
    MODEL_NAME_CLOZE,
    fields=[{"name": n} for n in ("CardID", "Text", "Extra", "Figure", "FigureBack", "Source")],
    templates=[{"name": "Cloze", "qfmt": CLOZE_FRONT, "afmt": CLOZE_BACK}],
    css=CSS,
    model_type=genanki.Model.CLOZE,
    sort_field_index=1,
)

_MD = markdown.Markdown(extensions=["tables", "fenced_code", "sane_lists", "nl2br", "md_in_html"])

# Math is protected from Markdown by hand (placeholders), because Markdown eats backslashes (\\ in
# aligned, \[ \]) and underscores inside formulas. Accepted delimiters: \( \), \[ \], $$ $$, and $ $
# (no space after the opening or before the closing $, single line). Output uses Anki's MathJax
# delimiters \( \) and \[ \].
_MATH_RE = re.compile(
    r"""(?P<disp>\\\[(?P<disp_body>.+?)\\\])
      | (?P<dd>\$\$(?P<dd_body>.+?)\$\$)
      | (?P<inl>\\\((?P<inl_body>.+?)\\\))
      | (?P<dol>(?<![\\\w$])\$(?P<dol_body>(?!\s)[^$\n]+?(?<!\s))\$(?![\w$]))""",
    re.S | re.X,
)

# Inline code spans are converted by hand (placeholders), like math: Python-Markdown drops characters of a
# code span that contains "<!--" (e.g. the "!" of "--!>"), because its raw-HTML preprocessor sees the comment
# before the inline patterns run. Fenced blocks are left to Markdown, which handles them correctly. Output is
# the same as Markdown's otherwise: content stripped, & < > escaped, wrapped in <code>.
_FENCE_RE = re.compile(r"(?ms)^[ \t]*(```|~~~).*?^[ \t]*\1[ \t]*$")
_CODE_SPAN_RE = re.compile(r"(?<![\\`])(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.S)

EXAM_DECK_KEY = "exam-practice"
EXAM_DECK_LABEL = "Exam practice"


# ----------------------------------------------------------------------------
# text to HTML
# ----------------------------------------------------------------------------


def fix_cloze_braces(s: str) -> str:
    """Anki cannot parse `{{c1::\\frac{1}{2}}}`: the `}}}` is ambiguous. Insert a space."""
    return re.sub(r"\}(\}\})", r"} \1", s)


def _protect_math(s: str) -> tuple[str, list[str]]:
    store: list[str] = []

    def repl(m: re.Match) -> str:
        if m.group("disp") or m.group("dd"):
            body = m.group("disp_body") or m.group("dd_body")
            store.append("\\[" + html.escape(body, quote=False) + "\\]")
        else:
            body = m.group("inl_body") or m.group("dol_body")
            store.append("\\(" + html.escape(body, quote=False) + "\\)")
        return f"MATHPH{len(store) - 1}Z"

    return _MATH_RE.sub(repl, s), store


def _protect_code_spans(s: str) -> tuple[str, list[str]]:
    store: list[str] = []

    def repl(m: re.Match) -> str:
        body = m.group(2)
        if "\n\n" in body:  # a code span never crosses a paragraph break
            return m.group(0)
        store.append("<code>" + html.escape(body.strip(), quote=False) + "</code>")
        return f"CODEPH{len(store) - 1}Z"

    out, pos = [], 0
    for f in _FENCE_RE.finditer(s):
        out.append(_CODE_SPAN_RE.sub(repl, s[pos : f.start()]))
        out.append(f.group(0))
        pos = f.end()
    out.append(_CODE_SPAN_RE.sub(repl, s[pos:]))
    return "".join(out), store


def to_html(s: str | None) -> str:
    if not s:
        return ""
    s = fix_cloze_braces(str(s).strip("\n"))
    # "#69 is ..." would become a heading: escape a line-initial # glued to a digit
    # (real headings and code comments have a space after the #)
    s = re.sub(r"(?m)^(\s*)#(?=\d)", r"\1\\#", s)
    protected, store = _protect_math(s)
    protected, codes = _protect_code_spans(protected)
    _MD.reset()
    out = _MD.convert(protected)
    out = re.sub(r"CODEPH(\d+)Z", lambda m: codes[int(m.group(1))], out)
    out = re.sub(r"MATHPH(\d+)Z", lambda m: store[int(m.group(1))], out)
    # single-paragraph answers do not need the <p> wrapper (keeps cards compact)
    if out.count("<p>") == 1 and out.startswith("<p>") and out.endswith("</p>"):
        out = out[3:-4]
    return out.strip()


def strip_for_index(s: str, n: int = 110) -> str:
    s = re.sub(r"\s+", " ", str(s)).strip()
    s = re.sub(r"\{\{c\d+::(.*?)(::.*?)?\}\}", r"\1", s)
    s = s.replace("**", "").replace("`", "")
    return (s[: n - 3] + "...") if len(s) > n else s


def deck_id_for(name: str) -> int:
    return (1 << 30) + int(hashlib.sha1(name.encode()).hexdigest()[:8], 16)


# ----------------------------------------------------------------------------
# exam practice, summary sheet, tags
# ----------------------------------------------------------------------------


def released_lectures(module: dict) -> set[str]:
    return {str(x) for x in ((module["profile"].get("exam_practice") or {}).get("released") or [])}


def is_held(module: dict, lec: dict, card: dict) -> bool:
    """True if the card is exam practice whose lecture has not been released yet."""
    return card.get("stage") == "exam" and lec["lecture"] not in released_lectures(module)


def exam_deck(module: dict, locks: dict) -> str:
    if EXAM_DECK_KEY not in locks:
        locks[EXAM_DECK_KEY] = f"{module['deck']}::{EXAM_DECK_LABEL}"
    return locks[EXAM_DECK_KEY]


def summary_blocks(module: dict) -> dict:
    if "_blocks" not in module:
        module["_blocks"] = val.load_summary_blocks(module["root"])
    return module["_blocks"] or {}


def sheet_refs(module: dict, card: dict) -> list[tuple[str, dict]]:
    """(block id, block) for every summary block the card points to that is on the exam sheet."""
    refs = card.get("sheet")
    if refs is None:
        return []
    refs = refs if isinstance(refs, list) else [refs]
    blocks = summary_blocks(module)
    return [(str(r), blocks[str(r)]) for r in refs if str(r) in blocks and blocks[str(r)]["on_sheet"]]


def extra_html(module: dict, card: dict) -> str:
    """Extra field: the sheet line (if the card's formula is on the exam sheet) above the card's own extra."""
    body = to_html(card.get("extra"))
    refs = sheet_refs(module, card)
    if not refs:
        return body
    names = "; ".join(f"{bid} {html.escape(b['title'])}" for bid, b in refs)
    line = f"<i>On the exam sheet: {names}</i>"
    return line + ("<br>" + body if body else "")


def card_tags(module: dict, lec: dict, card: dict) -> list[str]:
    base = val.tag_base(module)
    tags = [f"{base}::{lec['lecture']}"] + [str(t) for t in (card.get("tags") or [])]
    if card.get("stage") == "exam":
        tags.append(f"{base}::exam-practice")
    if sheet_refs(module, card):
        tags.append(f"{base}::sheet")
    return tags


# ----------------------------------------------------------------------------
# figures
# ----------------------------------------------------------------------------


def figure_spec_key(spec: dict, dpi: int) -> str:
    return hashlib.sha1(json.dumps({**spec, "dpi": dpi}, sort_keys=True).encode()).hexdigest()[:12]


def ensure_figure(module: dict, lec: dict, cid: str, spec: dict, suffix: str, dpi: int, index: dict) -> Path:
    data_dir: Path = module["dir"]
    pdf_rel = spec.get("pdf") or lec["source_pdf"]
    out = data_dir / "media" / f"{cid}{suffix}.png"
    key = figure_spec_key(spec, dpi)
    if out.exists() and index.get(out.name) == key:
        return out
    slides_mod.crop_figure(
        module["root"] / pdf_rel,
        int(spec["slide"]),
        candidate=spec.get("candidate"),
        clip=spec.get("clip"),
        full=bool(spec.get("full")),
        out=out,
        dpi=dpi,
        pad=float(spec.get("pad", 0.012)),
        masks=spec.get("mask"),
        candidates=val.load_candidates(data_dir, pdf_rel),
    )
    index[out.name] = key
    return out


# ----------------------------------------------------------------------------
# notes
# ----------------------------------------------------------------------------


def source_html(module: dict, lec: dict, card: dict) -> str:
    srcs = card.get("source") or []
    if not isinstance(srcs, list):
        srcs = [srcs]
    srcs = sorted({int(s) for s in srcs})
    unit, units = ("p.", "pp.") if lec.get("pages") else ("slide", "slides")
    if not srcs:
        s = ""
    elif len(srcs) == 1:
        s = f"{unit} {srcs[0]}"
    elif srcs == list(range(srcs[0], srcs[-1] + 1)):
        s = f"{units} {srcs[0]}-{srcs[-1]}"
    else:
        s = f"{units} " + ", ".join(map(str, srcs))
    if card.get("source_ref"):
        s = (s + SEP if s else "") + html.escape(str(card["source_ref"]))
    parts = [html.escape(module["id"]), lec["lecture"] + (SEP + s if s else "")]
    if lec.get("title"):
        parts.append(html.escape(str(lec["title"])))
    return SEP.join(parts)


def build_notes(
    module: dict, lec: dict, dpi: int, media: set[Path], index: dict, stats: dict
) -> list[tuple[genanki.Note, bool]]:
    """Notes of one lecture file, each with a flag: True = held back in the Exam practice subdeck."""
    notes = []
    for card in lec["cards"]:
        cid = card["id"]
        if card.get("status", "active") == "retired":
            stats["retired"].append(cid)
            continue
        figs = {"front": "", "back": ""}
        for key, default_side in (("figure", "front"), ("figure_back", "back")):
            spec = card.get(key)
            if not spec:
                continue
            side = spec.get("side", default_side)
            p = ensure_figure(module, lec, cid, spec, "" if side == "front" else "-b", dpi, index)
            media.add(p)
            figs[side] = f'<img src="{p.name}">'
        tags = card_tags(module, lec, card)
        for t in tags:
            if t.startswith("type::"):
                stats["types"][t[6:]] = stats["types"].get(t[6:], 0) + 1
        src = source_html(module, lec, card)
        guid = genanki.guid_for(cid)
        if card.get("type", "basic") == "cloze":
            fields = [cid, to_html(card["text"]), extra_html(module, card), figs["front"], figs["back"], src]
            note = genanki.Note(model=CLOZE_MODEL, fields=fields, guid=guid, tags=tags)
        else:
            fields = [
                cid,
                to_html(card["front"]),
                to_html(card["back"]),
                extra_html(module, card),
                figs["front"],
                figs["back"],
                src,
            ]
            note = genanki.Note(model=BASIC_MODEL, fields=fields, guid=guid, tags=tags)
        held = is_held(module, lec, card)
        notes.append((note, held))
        stats["active"] += 1
        if card.get("stage") == "exam":
            stats["exam"].setdefault(lec["lecture"], []).append(cid)
        if held:
            stats["held"].append(cid)
        if sheet_refs(module, card):
            stats["sheet"].append(cid)
    return notes


# ----------------------------------------------------------------------------
# decks
# ----------------------------------------------------------------------------


def short_title(title: str, n: int = 40) -> str:
    """Deck-friendly version of a lecture title: up to the first dash or colon, at most n characters."""
    t = re.split(r"\s+[-\u2013\u2014]\s+|:\s", str(title or "").strip(), maxsplit=1)[0].strip()
    t = t.replace("::", ":").replace('"', "")
    return (t[: n - 3].rstrip() + "...") if len(t) > n else t


def lecture_deck(module: dict, lec: dict, locks: dict) -> str:
    """Deck name for one lecture file. Frozen in decks.json at the first build (see module docstring)."""
    if not module["subdecks"]:
        return module["deck"]
    lid = lec["lecture"]
    if lid in locks:
        return locks[lid]
    label = str(lec.get("deck_title") or short_title(lec.get("title") or ""))
    name = f"{module['deck']}::{lid}" + (f" {label}" if label else "")
    locks[lid] = name
    return name


def load_locks(module: dict) -> dict:
    p = module["dir"] / "decks.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save_locks(module: dict, locks: dict) -> None:
    p = module["dir"] / "decks.json"
    p.write_text(json.dumps(dict(sorted(locks.items())), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


# ----------------------------------------------------------------------------
# concepts.md
# ----------------------------------------------------------------------------


def write_concepts(module: dict) -> Path:
    data_dir: Path = module["dir"]
    lines: list[str] = []
    n_active = n_retired = 0
    for p in val.lecture_files(data_dir):
        lec = val.load_lecture(p)
        cards = [c for c in lec["cards"] if isinstance(c, dict)]
        active = [c for c in cards if c.get("status", "active") == "active"]
        n_active += len(active)
        n_retired += len(cards) - len(active)
        lines += [f"## {lec.get('lecture')}: {lec.get('title', '')} ({len(active)} cards)", ""]
        for c in active:
            tags = [str(t) for t in (c.get("tags") or [])]
            ctype = next((t[6:] for t in tags if t.startswith("type::")), c.get("type", "basic"))
            topics = ", ".join(t[7:] for t in tags if t.startswith("topic::"))
            cid = str(c.get("id"))
            short_id = cid.split("-", 1)[1] if "-" in cid else cid
            front = strip_for_index(c.get("front") or c.get("text") or "")
            marks = ""
            if c.get("stage") == "exam":
                marks += " {exam practice}"
            if c.get("sheet") is not None:
                refs = c["sheet"] if isinstance(c["sheet"], list) else [c["sheet"]]
                marks += " {sheet " + ", ".join(map(str, refs)) + "}"
            lines.append(f"- {short_id} [{ctype}] {topics}{marks}: {front}")
        lines.append("")
    header = [
        f"# {module['id']}: concept index",
        "",
        "_Generated by build_deck.py from cards/*.yaml; do not edit. One line per card: "
        "id [type] topics {exam practice} {sheet block}: front. Grep cards/*.yaml for the full text "
        "of any card._",
        "",
        f"Active cards: {n_active}, retired: {n_retired}, updated {datetime.now():%Y-%m-%d %H:%M}",
        "",
    ]
    out = data_dir / "concepts.md"
    out.write_text("\n".join(header + lines), encoding="utf-8")
    return out


# ----------------------------------------------------------------------------
# report
# ----------------------------------------------------------------------------


def write_report(module, label, apkg, decks, media, stats, rep, lectures, locks, lecture_decks, out_dir) -> Path:
    data_dir: Path = module["dir"]

    def rel(p: Path) -> str:
        try:
            return str(p.relative_to(data_dir))
        except ValueError:  # --out outside the course folder
            return str(p)

    types = ", ".join(f"{k} {v}" for k, v in sorted(stats["types"].items()))
    retired = ", ".join(stats["retired"]) if stats["retired"] else "none"
    lines = [
        f"# Build report {module['id']} {label} ({datetime.now():%Y-%m-%d %H:%M})",
        "",
        f"- package: `{rel(apkg)}` with deck(s): " + "; ".join(f"**{d}**" for d in decks),
        f"- notes written: {stats['active']} ({types})",
        f"- media files: {len(media)}",
        f"- retired cards (delete in Anki via browser search `CardID:<id>`): {retired}",
        f"- concept index: `{rel(data_dir / 'concepts.md')}`",
    ]
    if stats["exam"] or stats["sheet"]:
        lines.append(
            f"- exam practice: {sum(len(v) for v in stats['exam'].values())} "
            f"({len(stats['held'])} held in the Exam practice subdeck); cards marked as on the exam sheet: "
            f"{len(stats['sheet'])}"
        )
    lines.append("")
    if rep.warnings:
        lines += ["## Validator warnings", "", *[f"- {w}" for w in rep.warnings], ""]
    for lec in lectures:
        lines += [f"## Coverage {lec['lecture']}: {lec.get('title', '')}", "", val.coverage_table(lec), ""]
    lines += [
        "## Import",
        "",
        "Anki: File > Import, choose the .apkg. First import of a lecture: the defaults are fine. "
        "Re-import after corrections: set *Update notes* to **Always** and keep *Update note types* on; "
        "review history is preserved because the note GUIDs are stable. A re-import never moves existing "
        "cards to another deck and never deletes notes.",
        "",
    ]
    if module["subdecks"]:
        lines += [
            "New lecture decks get Anki's **Default** preset on import (the package cannot carry a preset), so "
            "keep your study settings in the Default preset. Study from the course deck, not from a single "
            "lecture deck, so that reviews stay interleaved across lectures.",
            "",
        ]
    if stats["exam"]:
        edeck = locks.get(EXAM_DECK_KEY, f"{module['deck']}::{EXAM_DECK_LABEL}")
        base = val.tag_base(module)
        released = released_lectures(module)
        lines += [
            "## Exam practice",
            "",
            f"Cards with `stage: exam` wait in **{edeck}** until their lecture is released. When the import "
            "creates that subdeck for the first time, give it a preset **Hold** (a clone of Default with "
            "*New cards/day* = 0), applied to that subdeck only.",
            "",
        ]
        for lid, ids in sorted(stats["exam"].items()):
            state = "released (filed in the lecture subdeck)" if lid in released else "held"
            lines.append(f"- {lid}: {len(ids)} cards, {state}: {', '.join(ids)}")
        pending = sorted(lid for lid in stats["exam"] if lid not in released)
        if pending:
            lid = pending[0]
            lines += [
                "",
                f'To release a lecture, e.g. {lid}: Anki browser, search `"deck:{edeck}" tag:{base}::{lid}`, '
                f"select all, *Change Deck* to `{lecture_decks.get(lid, lid)}`; then add {lid} to "
                "`exam_practice.released` in profile.md.",
            ]
        lines.append("")
    report = out_dir / f"{label}-report.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    return report


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------


def build(course_dir: Path, lecture: str | None, out: Path | None = None, dpi: int = 220) -> dict:
    """Validate and build; returns paths and stats. Raises SystemExit on validation errors."""
    module = val.load_module(course_dir)
    data_dir: Path = module["dir"]
    rep, lectures = val.check_module(Path(course_dir), lecture)
    for w in rep.warnings:
        print("WARNING", w)
    if rep.errors:
        for e in rep.errors:
            print("ERROR  ", e)
        raise SystemExit(f"{len(rep.errors)} validation error(s); fix them and build again")
    if not lectures:
        raise SystemExit(f"no card files in {data_dir / 'cards'}")

    out_dir = Path(out) if out else data_dir / "build"
    out_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "media").mkdir(exist_ok=True)
    index_path = data_dir / "media" / ".index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}

    locks = load_locks(module)
    decks: dict[str, genanki.Deck] = {}
    lecture_decks: dict[str, str] = {}
    media: set[Path] = set()
    stats = {"active": 0, "retired": [], "types": {}, "exam": {}, "held": [], "sheet": []}
    for lec in lectures:
        dname = lecture_deck(module, lec, locks)
        lecture_decks[lec["lecture"]] = dname
        decks.setdefault(dname, genanki.Deck(deck_id_for(dname), dname))
        for note, held in build_notes(module, lec, dpi, media, index, stats):
            target = exam_deck(module, locks) if held else dname
            decks.setdefault(target, genanki.Deck(deck_id_for(target), target)).add_note(note)
    index_path.write_text(json.dumps(index, indent=1, sort_keys=True), encoding="utf-8")
    if module["subdecks"] or EXAM_DECK_KEY in locks:
        save_locks(module, locks)

    label = lecture or "ALL"
    apkg = out_dir / f"{module['id']}-{label}.apkg"
    pkg = genanki.Package(list(decks.values()))
    pkg.media_files = sorted(str(p) for p in media)
    pkg.write_to_file(str(apkg))
    concepts = write_concepts(module)
    report = write_report(module, label, apkg, decks, media, stats, rep, lectures, locks, lecture_decks, out_dir)
    return {"apkg": apkg, "report": report, "concepts": concepts, "decks": list(decks), "stats": stats}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("course_dir")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--lecture", help="build one lecture file, e.g. L03")
    g.add_argument("--all", action="store_true", help="build every lecture of the course into one .apkg")
    g.add_argument("--concepts-only", action="store_true", help="only regenerate concepts.md")
    ap.add_argument("--out", help="output directory (default COURSE_DIR/Anki/build)")
    ap.add_argument("--dpi", type=int, default=220, help="figure crop resolution")
    args = ap.parse_args(argv)

    if args.concepts_only:
        print("wrote", write_concepts(val.load_module(Path(args.course_dir))))
        return 0
    if not (args.lecture or args.all):
        ap.error("need --lecture Lxx or --all")
    res = build(Path(args.course_dir), None if args.all else args.lecture, args.out, args.dpi)
    stats = res["stats"]
    print(f"wrote {res['apkg']}  ({stats['active']} notes)")
    print(f"wrote {res['report']}")
    print(f"wrote {res['concepts']}")
    if stats["retired"]:
        print(f"retired (delete in Anki): {', '.join(stats['retired'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
