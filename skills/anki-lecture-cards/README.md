# anki-lecture-cards

A Claude skill that turns a course's material (lecture slides, mandatory readings, exercise sheets with solutions, old exams, quiz reviews, lecture recordings with subtitles) into Anki flashcards aimed at the exam, and maintains them over a whole term.

Claude looks at every slide, writes the cards of each lecture into a YAML file in your course folder, and builds an Anki package from it. The YAML files are the source of truth, so any card can be fixed later by its id without losing review history.

What you get:

- One `.apkg` per lecture, with one subdeck per lecture under the course deck, stable note ids (re-imports update cards in place) and figures cut from the slides, with answers masked where needed.
- A proof sheet (HTML) of every lecture's cards to skim before importing, checked in a headless browser.
- A coverage table: every slide has cards or a stated reason why not.
- An exam-practice stage: hard cards from old exams wait in a held subdeck until you release them.
- Optionally, an exam summary sheet (LaTeX, two PDFs: the sheet you take into the exam and a full reference) with a page budget per lecture.
- A feedback loop for leeches through an AnkiConnect MCP server, if you connect one.

## Requirements

- Python 3.10 or newer and `pip install -r requirements.txt` (genanki, PyMuPDF, Markdown, PyYAML, Pillow).
- Optional: Playwright with Chromium (`pip install playwright && playwright install chromium`) for the render check of the proof sheet.
- Optional: a LaTeX installation with `pdflatex` for the summary sheet.

## Try it on the example course

```bash
cp -r examples/linear-algebra /tmp/linear-algebra
python scripts/slides.py prepare /tmp/linear-algebra/L03-slides.pdf
python scripts/validate.py /tmp/linear-algebra --lecture L03
python scripts/build_deck.py /tmp/linear-algebra --lecture L03
python scripts/proof_sheet.py /tmp/linear-algebra --lecture L03
python scripts/summary.py init /tmp/linear-algebra && python scripts/summary.py build /tmp/linear-algebra   # needs LaTeX
```

Then import `/tmp/linear-algebra/Anki/build/LinAlg-L03.apkg` into Anki and open `LinAlg-L03-proof.html` next to it.

## Using it with Claude

Create a folder per course, put the lecturer's files in it, and ask Claude something like "turn lecture 3 of my linear algebra course into Anki cards". On the first run Claude sets up `Anki/profile.md` (exam format, notation, what to emphasise) from the course material. After that, each session handles one lecture; corrections work by card id ("LinAlg-L03-007 is wrong: ...").

## Layout

| path | content |
|---|---|
| `SKILL.md` | the instructions Claude follows |
| `scripts/` | `slides.py` (render, figure detection, crops), `validate.py`, `build_deck.py`, `proof_sheet.py`, `summary.py` |
| `templates/` | course profile, lecture file, LaTeX template of the summary sheet |
| `references/` | full card schema, review checklist, old-exam analysis, summary sheet, Anki setup for the user |
| `examples/linear-algebra/` | a small synthetic course |
| `tests/` | pytest suite (`pytest tests`) |

The tests build the example end to end; the summary test runs only when `pdflatex` is installed and the browser check only with Playwright and Chromium.
