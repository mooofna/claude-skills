#!/usr/bin/env python3
"""
summary.py: build a course's summary: the exam sheet and the full reference.

usage: summary.py init  COURSE_DIR             copy the LaTeX template into COURSE_DIR/Summary/
       summary.py build COURSE_DIR [--strict]  lint, compile both PDFs, measure the page budget

Needs a LaTeX installation with pdflatex (latexmk is used when present); only courses whose
exam allows a summary or formula sheet need this tool.

Layout (COURSE_DIR/Summary/):
  lectures/L01.tex ...  the content, one file per lecture (the only files written per session)
  preamble.tex          shared layout and macros; course notation at its end
  sheet.tex             exam sheet: sheetblocks only, at the minimum font size
  reference.tex         reference: every block, source pointers, sheetblocks marked with a square
  title.tex             \\SummaryTitle for the reference
  summary.yaml          sheet_pages, min_font_pt, per-lecture budget targets
  <Module>-exam-sheet.pdf, <Module>-reference.pdf   the two outputs
  build/                LaTeX aux files and report.md

Blocks: \\begin{sheetblock}{L01.3}{Title} ... \\end{sheetblock} (on the sheet and in the
reference) or \\begin{refblock}{L01.9}{Title} ... (reference only). Ids are Lxx.n, unique,
never renumbered or reused; cards point at them with `sheet: L01.3`. Titles are plain text.

build
  1. lint every lectures/*.tex: block ids and titles, no font-size or scaling commands (a typed
     exam sheet usually has a minimum font size), balanced environments
  2. compile sheet.tex and reference.tex into build/
  3. measure the sheet: pages, how much of the budget (sheet_pages x 2 columns) each lecture
     uses (from the lec-Lxx anchors), smallest font size in the PDF
  4. write build/report.md and copy the PDFs to Summary/
Exit status 1 on lint or LaTeX errors, and with --strict also when the sheet is over budget.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate as val

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "summary"
TEMPLATE_FILES = ("preamble.tex", "sheet.tex", "reference.tex", "title.tex", "summary.yaml")
FORBIDDEN = [
    r"\\tiny\b",
    r"\\scriptsize\b",
    r"\\footnotesize\b",
    r"\\small\b",
    r"\\fontsize\b",
    r"\\scalebox\b",
    r"\\resizebox\b",
    r"\\adjustbox\b",
    r"\\selectfont\b",
    r"\\textsmaller\b",
]
ID_RE = re.compile(r"^(L|X)\d{2}\.\d+$")
ENV_RE = re.compile(r"\\(begin|end)\{([A-Za-z*]+)\}")


def summary_dir(course: Path) -> Path:
    return val.resolve_module(course)[1] / val.SUMMARY_SUBDIR


def init(course: Path) -> None:
    sdir = summary_dir(course)
    module = val.load_module(course)
    (sdir / "lectures").mkdir(parents=True, exist_ok=True)
    for name in TEMPLATE_FILES:
        dst = sdir / name
        if dst.exists():
            print("kept", dst)
            continue
        text = (TEMPLATE_DIR / name).read_text(encoding="utf-8").replace("COURSE", str(module["id"]))
        dst.write_text(text, encoding="utf-8")
        print("wrote", dst)


def _strip_comments(text: str) -> str:
    """Drop LaTeX comments (an unescaped % to the end of the line)."""
    return "\n".join(re.split(r"(?<!\\)%", line, maxsplit=1)[0] for line in text.splitlines())


def lint(sdir: Path) -> tuple[list[str], list[str], dict]:
    errors, warnings = [], []
    blocks: dict[str, dict] = {}
    for p in sorted((sdir / "lectures").glob("*.tex")):
        if not re.match(r"^(L|X)\d{2}$", p.stem):
            errors.append(f"{p.name}: lecture files are named L01.tex, L02.tex ... (X01.tex for other sources)")
        code = _strip_comments(p.read_text(encoding="utf-8"))
        for pat in FORBIDDEN:
            for m in re.finditer(pat, code):
                line = code[: m.start()].count("\n") + 1
                errors.append(
                    f"{p.name}:{line}: {m.group(0)}: font sizes and scaling are not allowed in lecture files "
                    f"(the exam sheet must stay at the minimum font size)"
                )
        stack: list[tuple[str, int]] = []
        for m in ENV_RE.finditer(code):
            line = code[: m.start()].count("\n") + 1
            if m.group(1) == "begin":
                stack.append((m.group(2), line))
            elif not stack or stack[-1][0] != m.group(2):
                what = f"\\begin{{{stack[-1][0]}}} of line {stack[-1][1]}" if stack else "anything"
                errors.append(f"{p.name}:{line}: \\end{{{m.group(2)}}} does not close {what}")
            else:
                stack.pop()
        for env, line in stack:
            errors.append(f"{p.name}:{line}: \\begin{{{env}}} is never closed")
        opened = re.findall(r"\\begin\{(sheetblock|refblock)\}", code)
        found = list(val.BLOCK_RE.finditer(code))
        if len(opened) != len(found):
            errors.append(
                f"{p.name}: {len(opened) - len(found)} block(s) whose id or title has the wrong form "
                f"(\\begin{{sheetblock}}{{L01.3}}{{Plain title}})"
            )
        for m in found:
            bid, title = m.group(2).strip(), m.group(3).strip()
            line = code[: m.start()].count("\n") + 1
            if not ID_RE.match(bid):
                errors.append(f"{p.name}:{line}: block id {bid!r} must look like L01.3")
            elif not bid.startswith(p.stem + "."):
                errors.append(f"{p.name}:{line}: block id {bid} does not belong to {p.name}")
            if bid in blocks:
                errors.append(f"{p.name}:{line}: duplicate block id {bid} (also in {blocks[bid]['file']})")
            if not title or "$" in title or "\\" in title:
                errors.append(f"{p.name}:{line}: block title of {bid} must be plain text (cards quote it)")
            blocks[bid] = {"on_sheet": m.group(1) == "sheetblock", "title": title, "file": p.name}
        if not re.search(r"\\lecture\{" + re.escape(p.stem) + r"\}", code):
            warnings.append(f"{p.name}: no \\lecture{{{p.stem}}}{{...}} header (needed for the page budget)")
    return errors, warnings, blocks


def latex_available() -> bool:
    return bool(shutil.which("pdflatex"))


def latex(sdir: Path, main: str) -> tuple[bool, str]:
    build = sdir / "build"
    build.mkdir(exist_ok=True)
    if shutil.which("latexmk"):
        cmds = [
            [
                "latexmk",
                "-pdf",
                "-interaction=nonstopmode",
                "-halt-on-error",
                "-file-line-error",
                f"-outdir={build}",
                main,
            ]
        ]
    else:  # two pdflatex runs resolve the anchors the budget measurement needs
        run = [
            "pdflatex",
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            f"-output-directory={build}",
        ]
        cmds = [[*run, main], [*run, main]]
    r = None
    for cmd in cmds:
        r = subprocess.run(cmd, cwd=sdir, capture_output=True, text=True, check=False)
        if r.returncode != 0:
            break
    log = build / (Path(main).stem + ".log")
    logtext = log.read_text(errors="replace") if log.exists() else r.stdout + r.stderr
    if r.returncode != 0:
        errs = [ln for ln in logtext.splitlines() if re.match(r"^(\./|/).*:\d+: ", ln) or ln.startswith("! ")]
        return False, "\n".join(errs[:15]) or (r.stdout + r.stderr)[-2000:]
    return True, logtext


def measure(pdf: Path, logtext: str, pages_budget: int) -> dict:
    """Column-length units: one column of the sheet = 1 unit; budget = pages_budget * 2."""
    import pymupdf

    with pymupdf.open(str(pdf)) as doc:
        names = doc.resolve_names()
        m = re.search(r"SUMMARYGEOM textheight=([\d.]+)pt", logtext)
        text_h = float(m.group(1)) * 72 / 72.27 if m else None
        top = names["sheet-top"]["to"][1] if "sheet-top" in names else None
        res = {"pages": len(doc), "units_budget": pages_budget * 2, "lectures": {}, "min_font": None}
        if text_h is None or top is None or "sheet-end" not in names:
            res["error"] = "anchors or geometry missing; cannot measure the budget"
            return res
        page_w, page_h = doc[0].rect.width, doc[0].rect.height
        # PDF destination y is measured from the bottom of the page; convert to distance below the text top
        top_from_top = page_h - top

        def below_top(y):
            return (page_h - y) - top_from_top

        end = names["sheet-end"]
        end_page = end["page"]
        end_col = 0 if end["to"][0] < page_w / 2 else 1
        h_last = max(0.0, below_top(end["to"][1])) / text_h  # balanced columns: both hold h_last on the last page

        def linear(page: int, x: float, y: float) -> float:
            col = 0 if x < page_w / 2 else 1
            frac = max(0.0, min(1.0, below_top(y) / text_h))
            if page == end_page:  # balanced last page
                return page * 2 + (frac if col == 0 else h_last + frac)
            return page * 2 + col + frac

        total = end_page * 2 + (2 * h_last if end_col == 1 else h_last)
        starts = sorted(
            ((k[4:], linear(v["page"], *v["to"])) for k, v in names.items() if k.startswith("lec-")),
            key=lambda t: t[1],
        )
        for i, (lid, s) in enumerate(starts):
            e = starts[i + 1][1] if i + 1 < len(starts) else total
            res["lectures"][lid] = max(0.0, e - s)
        res["units_used"] = total
        sizes: dict[float, int] = {}
        for page in doc:
            for b in page.get_text("dict")["blocks"]:
                for line in b.get("lines", []):
                    for sp in line["spans"]:
                        if sp["text"].strip():
                            sz = round(sp["size"], 1)
                            sizes[sz] = sizes.get(sz, 0) + len(sp["text"].strip())
    res["min_font"] = min(sizes) if sizes else None
    res["font_sizes"] = dict(sorted(sizes.items()))
    return res


def build(course: Path, strict: bool = False) -> int:
    sdir = summary_dir(course)
    if not (sdir / "sheet.tex").exists():
        print(f"no {sdir}/sheet.tex; run: summary.py init {course}", file=sys.stderr)
        return 1
    if not latex_available():
        print("summary.py build needs a LaTeX installation with pdflatex (e.g. TeX Live)", file=sys.stderr)
        return 1
    module = val.load_module(course)
    cfg = (
        yaml.safe_load((sdir / "summary.yaml").read_text(encoding="utf-8")) if (sdir / "summary.yaml").exists() else {}
    )
    cfg = cfg or {}
    pages_budget = int(cfg.get("sheet_pages", 2))
    min_pt = float(cfg.get("min_font_pt", 11))
    targets = cfg.get("targets") or {}

    errors, warnings, blocks = lint(sdir)
    head = (sdir / "sheet.tex").read_text(encoding="utf-8")
    m = re.search(r"\\documentclass\[([^\]]*)\]", head)
    size = re.search(r"(\d+)pt", m.group(1)) if m else None
    base = size.group(1) if size else "10"
    if float(base) < min_pt:
        errors.append(f"sheet.tex: base font {base}pt < {min_pt:g}pt")
    for e in errors:
        print("ERROR  ", e)
    for w in warnings:
        print("WARNING", w)
    if errors:
        print(f"{len(errors)} lint error(s); nothing compiled")
        return 1

    ok_s, log_s = latex(sdir, "sheet.tex")
    ok_r, log_r = latex(sdir, "reference.tex") if ok_s else (False, "")
    if not (ok_s and ok_r):
        print("LaTeX failed:\n" + (log_s if not ok_s else log_r))
        return 1
    mid = module["id"]
    sheet_pdf, ref_pdf = sdir / f"{mid}-exam-sheet.pdf", sdir / f"{mid}-reference.pdf"
    shutil.copy(sdir / "build" / "sheet.pdf", sheet_pdf)
    shutil.copy(sdir / "build" / "reference.pdf", ref_pdf)
    meas = measure(sdir / "build" / "sheet.pdf", log_s, pages_budget)
    import pymupdf

    with pymupdf.open(str(ref_pdf)) as doc:
        ref_pages = len(doc)

    ub = meas["units_budget"]
    used = meas.get("units_used")
    over = used is not None and used > ub + 1e-6
    n_sheet = sum(b["on_sheet"] for b in blocks.values())
    share = f"{used / ub:.0%}" if used is not None else "unknown"
    lines = [
        f"# Summary build {mid} ({datetime.now():%Y-%m-%d %H:%M})",
        "",
        f"- exam sheet: `{sheet_pdf.name}`, {meas['pages']} page(s); budget {pages_budget} pages ({ub} columns); "
        f"used **{share}** of the budget" + (", **OVER BUDGET**" if over else ""),
        f"- reference: `{ref_pdf.name}`, {ref_pages} page(s)",
        f"- blocks: {len(blocks)} ({n_sheet} on the sheet, {len(blocks) - n_sheet} reference only)",
        f"- base font of the sheet: {base} pt; smallest glyphs in the PDF: {meas.get('min_font')} pt "
        f"(TeX sets sub- and superscripts in formulas smaller, as in any {base}-pt document)",
        "",
    ]
    if meas.get("error"):
        lines += [f"Budget: {meas['error']}", ""]
    else:
        lines += ["## Budget per lecture (share of the whole sheet)", "", "| lecture | used | target | |"]
        lines.append("|---|---|---|---|")
        for lid, u in meas["lectures"].items():
            t = targets.get(lid)
            flag = "over" if t is not None and u / ub > float(t) * 1.15 else ""
            lines.append(f"| {lid} | {u / ub:.1%} | {'' if t is None else f'{float(t):.1%}'} | {flag} |")
        lines.append("")
    lines += ["## Blocks", "", "| id | on sheet | title |", "|---|---|---|"]
    for bid, b in blocks.items():
        lines.append(f"| {bid} | {'yes' if b['on_sheet'] else '-'} | {b['title']} |")
    lines.append("")
    if warnings:
        lines += ["## Warnings", "", *[f"- {w}" for w in warnings], ""]
    (sdir / "build" / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:7]))
    print(f"wrote {sheet_pdf}\nwrote {ref_pdf}\nwrote {sdir / 'build' / 'report.md'}")
    return 1 if (strict and over) else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["init", "build"])
    ap.add_argument("course_dir")
    ap.add_argument("--strict", action="store_true", help="exit 1 when the sheet is over its page budget")
    args = ap.parse_args(argv)
    if args.command == "init":
        init(Path(args.course_dir))
        return 0
    return build(Path(args.course_dir), args.strict)


if __name__ == "__main__":
    sys.exit(main())
