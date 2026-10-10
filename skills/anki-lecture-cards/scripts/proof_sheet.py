#!/usr/bin/env python3
"""
proof_sheet.py: render a lecture's cards as one HTML page for review, and optionally verify
the rendering in a headless browser.

usage: proof_sheet.py COURSE_DIR --lecture L03 [--check] [--shots N] [--timeout 30]

Writes COURSE_DIR/Anki/build/<Module>-<Lecture>-proof.html: every card with its figure(s),
the answer, the extra note, tags and source, typeset with MathJax (loaded from a CDN, so the
page needs a network connection to show formulas) using the same CSS as the Anki note types.
Open it in a browser and skim it before importing the .apkg.

--check   loads the page in headless Chromium (needs `pip install playwright` and
          `playwright install chromium`), waits for MathJax, and reports MathJax errors
          (mjx-merror), images that failed to load and console errors; writes
          Anki/build/<Lecture>-check.json and, with --shots N, screenshots of the first N
          cards to Anki/build/proof/<CardID>.png for a visual check.
          Exit status 1 when MathJax could not load or the page has errors.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_deck as bd
import validate as val

MATHJAX_URL = "https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-chtml.js"

PAGE_CSS = """
body { margin: 0; padding: 24px; background: #ececef; font-family: -apple-system, Helvetica, Arial, sans-serif; }
.wrap { max-width: 900px; margin: 0 auto; }
h1 { font-size: 22px; margin: 0 0 4px; }
.meta { color: #6e6e73; font-size: 14px; margin-bottom: 18px; }
.cardbox { background: #fff; border-radius: 10px; box-shadow: 0 1px 3px rgba(0,0,0,.12); margin: 0 0 18px;
           overflow: hidden; }
.head { display: flex; justify-content: space-between; align-items: baseline; padding: 8px 14px;
        background: #f5f5f7; font-size: 12px; color: #6e6e73; border-bottom: 1px solid #e5e5ea; }
.head b { color: #1c1c1e; font-family: Menlo, monospace; }
.tag { display: inline-block; background: #e5e5ea; border-radius: 4px; padding: 1px 6px; margin-left: 4px; }
.card { max-width: none; }
.badge { color: #b35c00; }
.retired { color: #c00; }
.warn { background: #fff4d6; color: #7a5200; padding: 8px 14px; font-size: 13px; border-top: 1px solid #f0dca0; }
.summary { background: #fff; border-radius: 10px; padding: 12px 16px; margin-bottom: 18px; font-size: 14px; }
"""

MATHJAX_CFG = """
window.MathJax = { tex: { inlineMath: [['\\\\(', '\\\\)']], displayMath: [['\\\\[', '\\\\]']], processEscapes: false },
                   options: { skipHtmlTags: ['script','noscript','style','textarea','pre','code'] },
                   startup: { typeset: true } };
"""

_CLOZE = re.compile(r"\{\{c(\d+)::(.*?)(?:::(.*?))?\}\}", re.S)
_CARD_ID_RE = re.compile(r"([A-Za-z0-9]+-[LX]\d{2}-\d{3})")


def _cloze_span(n: str, body: str) -> str:
    return f'<span class="cloze" title="c{n}">[{body}]</span>'


def _span_clozes_with_math(raw_text: str) -> str:
    """Deletions that *contain* math ({{c1::\\(x\\) and y}}) would be cut apart by the math split below.
    Render them first as a highlighted span; the braces are counted so that math with nested braces
    inside the deletion does not end it early. Deletions inside math are left to the caller."""
    math_spans = [(m.start(), m.end()) for m in bd._MATH_RE.finditer(raw_text)]
    out, pos = [], 0
    for m in re.finditer(r"\{\{c(\d+)::", raw_text):
        start = m.start()
        if start < pos or any(a <= start < b for a, b in math_spans):
            continue
        i, depth, end = m.end(), 0, None
        while i < len(raw_text) - 1:
            ch = raw_text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                if depth:
                    depth -= 1
                elif raw_text[i + 1] == "}":
                    end = i
                    break
            i += 1
        if end is None:
            continue
        body = raw_text[m.end() : end].split("::", 1)[0]  # drop an optional ::hint
        if not bd._MATH_RE.search(body):
            continue
        out.append(raw_text[pos:start])
        out.append(_cloze_span(m.group(1), body))
        pos = end + 2
    out.append(raw_text[pos:])
    return "".join(out)


def cloze_preview(raw_text: str) -> str:
    """Show cloze deletions highlighted with the answer visible (this sheet is for content review, not
    for rehearsal). Anki resolves clozes before MathJax runs, so inside math a deletion becomes
    \\class{cloze}{...} for MathJax and outside math an HTML span. Returns HTML."""
    raw_text = _span_clozes_with_math(raw_text)
    out, pos = [], 0
    for m in bd._MATH_RE.finditer(raw_text):
        out.append(_CLOZE.sub(lambda c: _cloze_span(c.group(1), c.group(2)), raw_text[pos : m.start()]))
        out.append(_CLOZE.sub(lambda c: r"\class{cloze}{" + c.group(2) + "}", m.group(0)))
        pos = m.end()
    out.append(_CLOZE.sub(lambda c: _cloze_span(c.group(1), c.group(2)), raw_text[pos:]))
    return bd.to_html("".join(out))


def render(module: dict, lec: dict, warnings: list[str]) -> str:
    cards = [c for c in lec["cards"] if isinstance(c, dict)]
    n_active = len([c for c in cards if c.get("status", "active") == "active"])
    title = f"{html.escape(module['id'])} {lec['lecture']}: {html.escape(str(lec.get('title', '')))}"
    deck = html.escape(bd.lecture_deck(module, lec, bd.load_locks(module)))
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        f"<title>{html.escape(module['id'])} {lec['lecture']} proof sheet</title>",
        f"<style>{PAGE_CSS}{bd.CSS}</style><script>{MATHJAX_CFG}</script>",
        f"<script id='MathJax-script' async src='{MATHJAX_URL}' onerror='window.__mathjaxFailed = true'></script>",
        "</head><body><div class='wrap'>",
        f"<h1>{title}</h1>",
        f"<div class='meta'>{n_active} active cards, deck {deck}, generated by proof_sheet.py</div>",
    ]
    if warnings:
        items = "".join(f"<li>{html.escape(w)}</li>" for w in warnings)
        parts.append(f"<div class='summary'><b>Validator warnings</b><ul>{items}</ul></div>")
    warn_by_id: dict[str, list[str]] = {}
    for w in warnings:
        m = _CARD_ID_RE.search(w)
        if m:
            warn_by_id.setdefault(m.group(1), []).append(w.split(": ", 1)[-1])
    for c in cards:
        cid = str(c.get("id"))
        tags = "".join(f"<span class='tag'>{html.escape(str(t))}</span>" for t in (c.get("tags") or []))
        figs = {"front": "", "back": ""}
        for key, default_side in (("figure", "front"), ("figure_back", "back")):
            spec = c.get(key)
            if spec:
                side = spec.get("side", default_side)
                name = f"{cid}{'' if side == 'front' else '-b'}.png"
                figs[side] = f"<div class='fig'><img src='../media/{name}' alt='{name}'></div>"
        badges = ""
        if c.get("status", "active") == "retired":
            badges += ", <span class='retired'>RETIRED</span>"
        if c.get("stage") == "exam":
            state = "held" if bd.is_held(module, lec, c) else "released"
            badges += f", <span class='badge'>EXAM PRACTICE ({state})</span>"
        parts.append(
            f"<div class='cardbox' id='{html.escape(cid)}'><div class='head'>"
            f"<span><b>{html.escape(cid)}</b>, {html.escape(str(c.get('type', 'basic')))}{badges}</span>"
            f"<span>{tags}</span></div>"
        )
        parts.append("<div class='card'>")
        if c.get("type") == "cloze":
            parts.append(f"<div class='q'>{cloze_preview(bd.fix_cloze_braces(str(c.get('text'))))}</div>")
            parts.append(figs["front"])
        else:
            parts.append(f"<div class='q'>{bd.to_html(c.get('front'))}</div>{figs['front']}<hr id=answer>")
            parts.append(f"<div class='a'>{bd.to_html(c.get('back'))}</div>")
        parts.append(figs["back"])
        extra = bd.extra_html(module, c)
        if extra:
            parts.append(f"<div class='extra'>{extra}</div>")
        parts.append(f"<div class='src'>{bd.source_html(module, lec, c)}{bd.SEP}{html.escape(cid)}</div></div>")
        for w in warn_by_id.get(cid, []):
            parts.append(f"<div class='warn'>Warning: {html.escape(w)}</div>")
        parts.append("</div>")
    parts.append("</div></body></html>")
    return "\n".join(parts)


def check(page_path: Path, out_json: Path, shots: int, shot_dir: Path, timeout_s: float = 30) -> dict:
    """Render the proof sheet in headless Chromium and collect problems (see module docstring)."""
    from playwright.sync_api import sync_playwright  # optional dependency, only for --check

    result: dict = {"page": str(page_path)}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            pg = browser.new_page(viewport={"width": 900, "height": 1200})
            console_errors: list[str] = []
            pg.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
            pg.on("pageerror", lambda e: console_errors.append(str(e)))
            pg.goto(Path(page_path).resolve().as_uri())
            try:
                pg.wait_for_function(
                    "window.__mathjaxFailed || (window.MathJax && MathJax.startup && MathJax.startup.promise)",
                    timeout=timeout_s * 1000,
                )
                if pg.evaluate("!!window.__mathjaxFailed"):
                    result["mathjax"] = f"not loaded: {MATHJAX_URL} unreachable"
                else:
                    pg.evaluate("MathJax.startup.promise")
                    pg.wait_for_timeout(300)
                    result["mathjax"] = "ok"
            except Exception as e:  # timeout
                result["mathjax"] = f"not loaded: {e}"
            result["mathjax_errors"] = pg.evaluate(
                "Array.from(document.querySelectorAll('mjx-merror')).map(e => (e.closest('.cardbox') || {}).id"
                " + ': ' + (e.getAttribute('data-mjx-error') || e.textContent))"
            )
            result["broken_images"] = pg.evaluate(
                "Array.from(document.images).filter(i => !i.complete || i.naturalWidth === 0)"
                ".map(i => i.getAttribute('src'))"
            )
            result["console_errors"] = [e for e in console_errors if MATHJAX_URL not in e][:20]
            result["cards"] = pg.evaluate("document.querySelectorAll('.cardbox').length")
            if shots:
                shot_dir.mkdir(parents=True, exist_ok=True)
                ids = pg.evaluate("Array.from(document.querySelectorAll('.cardbox')).map(e => e.id)")[:shots]
                for cid in ids:
                    pg.locator(f"[id='{cid}']").screenshot(path=str(shot_dir / f"{cid}.png"))
                result["screenshots"] = [str(shot_dir / f"{cid}.png") for cid in ids]
        finally:
            browser.close()
    out_json.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def check_ok(res: dict) -> bool:
    return res.get("mathjax") == "ok" and not res["mathjax_errors"] and not res["broken_images"]


def write_proof(course_dir: Path, lecture: str) -> Path:
    module = val.load_module(Path(course_dir))
    rep, lectures = val.check_module(Path(course_dir), lecture)
    if rep.errors:
        for e in rep.errors:
            print("ERROR  ", e)
        raise SystemExit("fix validation errors first")
    out = module["dir"] / "build" / f"{module['id']}-{lecture}-proof.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(module, lectures[0], rep.warnings), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("course_dir")
    ap.add_argument("--lecture", required=True)
    ap.add_argument("--check", action="store_true", help="render in headless Chromium and report problems")
    ap.add_argument("--shots", type=int, default=0, help="with --check: screenshots of the first N cards")
    ap.add_argument("--timeout", type=float, default=30, help="with --check: seconds to wait for MathJax")
    args = ap.parse_args(argv)
    out = write_proof(Path(args.course_dir), args.lecture)
    print("wrote", out)
    if not args.check:
        return 0
    build = out.parent
    res = check(out, build / f"{args.lecture}-check.json", args.shots, build / "proof", args.timeout)
    ok = check_ok(res)
    print(
        f"render check: {res['cards']} cards, MathJax {res['mathjax']}, {len(res['mathjax_errors'])} MathJax errors, "
        f"{len(res['broken_images'])} broken images, {len(res['console_errors'])} console errors: "
        f"{'OK' if ok else 'PROBLEMS'}"
    )
    for e in res["mathjax_errors"]:
        print("  MathJax:", e)
    for b in res["broken_images"]:
        print("  image:", b)
    if res.get("screenshots"):
        print("  screenshots:", ", ".join(res["screenshots"]))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
