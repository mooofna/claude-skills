# Card files, profile and validator rules

Reference for `Anki/cards/*.yaml`, the profile front matter and what `scripts/validate.py` checks. `templates/lecture-template.yaml` shows every field by example; `examples/linear-algebra/` is a complete course that validates cleanly.

## Folder layouts the scripts accept

Pass any of these as `COURSE_DIR`:

- **Course folder** (recommended): the lecturer's files anywhere inside, card data in `Anki/` (`Anki/profile.md`, `Anki/cards/`, ...), summary in `Summary/`. Source paths in card files are relative to the course folder.
- **The `Anki/` folder itself**: treated as above; its parent is the course folder.
- **Flat folder**: `profile.md`, `cards/` and the sources in one folder. Source paths are relative to that folder.

`slides.py prepare` finds the course folder by walking up from the PDF and writes to `<course>/Anki/build/<pdf-stem>/`; pass `--out` for a PDF outside any course folder.

## Profile front matter (`Anki/profile.md`)

| key | read by | meaning |
|---|---|---|
| `module` | scripts | card id prefix, letters and digits only. Unique across the user's Anki collection (note GUIDs derive from card ids). Never change after the first import. |
| `deck` | scripts | the course deck; may be nested with `::`. Never change after the first import. |
| `tag_prefix` | scripts | optional prefix of generated tags (`2026S` gives `2026S::LinAlg::L03`); without it tags start with the module id |
| `subdecks` | scripts | default `true`: one subdeck per lecture file; `false` files every card into the course deck |
| `exam_practice.released` | scripts | lectures whose exam-practice cards the user has moved into their lecture subdeck, e.g. `[L01, L02]` |
| `held_out_exams` | scripts | sittings kept for a mock exam, as they appear in `source_ref` (case-insensitive substring match), e.g. `["Exam 2025"]` |
| `language` | Claude | language the cards are written in |
| `two_phase` | Claude | `true` when exercise sheets and quizzes are carded in a second session per lecture |

The body of the profile is free Markdown for Claude (see `templates/profile-template.md`).

## Lecture file (`Anki/cards/L03.yaml`)

| key | required | meaning |
|---|---|---|
| `module` | recommended | must equal the profile's `module` |
| `lecture` | yes | `L01` to `L99`, or `X01` and up for material that is not a lecture; must equal the file name |
| `title` | recommended | lecture title; the subdeck label is derived from it at the first build |
| `date` | no | documentation |
| `source_pdf` | when cards cite slides or use figures | the slides, relative to the course folder; slide numbers are its pages |
| `deck_title` | no | short subdeck label, only effective before the first build |
| `pages` | no | `[first, last]`: only these pages of `source_pdf` belong to this lecture (a shared script); coverage is judged for that range and the unit becomes "page" |
| `sources_extra` | no | list of other files that fed this lecture (documentation, and the marker that a file is no longer "new") |
| `skipped` | when slides have no cards | list of `{slides: [..], reason: ..}`; every slide without a card needs a reason |
| `cards` | yes | list of cards |

## Card fields

| key | meaning |
|---|---|
| `id` | `<Module>-<Lecture>-<3 digits>`, unique in the course; never reused, never renumbered |
| `type` | `basic` (default) or `cloze` |
| `front`, `back` | basic cards: question and answer (Markdown with math) |
| `text` | cloze cards: text with `{{c1::...}}` deletions (they may sit inside math); numbered 1..n without gaps |
| `extra` | optional, shown on the back: the one insight that helps encoding |
| `figure` | picture cut from a PDF page, on the front by default |
| `figure_back` | second picture, on the back by default |
| `source` | list of slide (page) numbers of `source_pdf` the card rests on |
| `source_ref` | free-text source when there is no slide: `"Exercise sheet 3, problem 2"`, `"Exam 2024 Q9 (answer own)"`, `"Textbook §3.6.2"`, `"Quiz 3.1"` |
| `tags` | one `type::` tag; 1 to 3 `topic::` tags reusing the course's slugs; `exam::core` for lecturer- or exam-flagged items |
| `contrast` | ids of cards this one is deliberately set against (both directions) |
| `stage` | `first` (default) or `exam`: exam practice, held in `<deck>::Exam practice` until its lecture is released |
| `sheet` | summary block id (or list) whose formula this card covers, e.g. `L03.2` |
| `status` | `active` (default) or `retired`: kept in the file forever, skipped by the build, listed for deletion |

Type tags: `definition`, `theorem`, `mechanism`, `derivation`, `procedure`, `contrast`, `figure`, `code`, `example`, `pitfall`, `intuition`. A card with a figure on the front adds `type::figure` to its main type.

### Figure spec

```yaml
figure: {slide: 17, candidate: f1}                       # a detected candidate (ids on contact/p017.png)
figure: {slide: 17, clip: [0.06, 0.20, 0.97, 0.55]}      # page region, normalised 0..1, origin top left
figure: {slide: 17, full: true, side: back}              # the whole page
figure: {slide: 22, candidate: f1, mask: [[0.33, 0.0, 1.0, 1.0]]}   # white boxes over the crop, normalised to the crop
figure_back: {pdf: L03-solution.pdf, slide: 2, clip: [0.1, 0.3, 0.9, 0.6]}   # from another PDF of the course
```

Exactly one of `candidate`, `clip`, `full`. `side` is `front` or `back` (`figure` defaults to the front, `figure_back` to the back; the two must end up on different sides). `pad` (default 0.012 of the page size) widens a crop; masks at the very edge of a crop therefore start a few percent in. For a figure from another PDF, run `slides.py prepare` on that PDF too if you use candidates. Crops are cached in `Anki/media/` and re-cut only when the spec changes.

## Writing rules

- Math in `\( \)` and `\[ \]`; `$...$` and `$$...$$` are accepted and converted (a literal dollar is `\$`). Use `\begin{aligned}` inside `\[ \]`, never `align` or `equation`.
- Markdown tables for tables; no `|` inside a cell, not even in math (write `\mid`). A list needs a blank line before it.
- Code in backticks or fenced blocks. No raw `<img>`: use `figure`.
- YAML block scalars (`|`) keep backslashes literal, so LaTeX is written as usual. Quote single-line values that contain `: ` or start with a special character.
- A cloze deletion that ends in a brace (`{{c1::\frac{1}{2}}}`) is ambiguous for Anki; the builder inserts a space, but writing `{{c1::\frac{1}{2} }}` yourself keeps the YAML readable.
- Some tool interfaces turn a backslash followed by `u` and four hex digits into the Unicode character. When card text needs that literal sequence (a JSON or Python escape), write it with Python's `chr(92)` and check the YAML afterwards.

## What the validator checks

Errors stop the build; warnings are judgement calls.

Errors:
- profile: `module` missing or not letters and digits, `deck` missing (the scripts exit), `exam_practice.released` not a list of lecture ids, `held_out_exams` not a list
- lecture: invalid `lecture` or file name mismatch, `module` differs from the profile, `source_pdf` not found, malformed `pages`
- skipped: entry without `slides` list, entry without `reason`, skipped slide out of range
- card: malformed or duplicate id (checked across the whole course), wrong module or lecture in the id, unknown `type`, `status` or `stage`; basic card without front or back, or with `text`; cloze card without text or without a deletion, or with front/back; unbalanced math delimiters; odd number of `$`; raw `<img>`; bad tag characters; `source` entries that are not slide numbers or lie outside the PDF
- figure: not a mapping, slide out of range, not exactly one of candidate/clip/full, candidate not on that slide, malformed clip or mask, unknown side, `pdf` not found, both figures on the same side, a figure without `pdf:` in a lecture without `source_pdf`
- sheet: malformed block id, no `Summary/lectures/`, block not found
- held-out exam: an active card's `source_ref` names a sitting in `held_out_exams`

Warnings: no title; no `candidates.json` yet; slides without cards and without a reason; slides both skipped and cited; unknown card or figure keys; no `type::` tag or an unusual one; front over 320 characters; back over 800 characters without a derivation/procedure/example tag; long `extra`; yes/no fronts; fronts that refer to "this slide" or "the following" without a figure; answers that are lists of six or more items; full slide on the front; figure on the front without `type::figure`; `}}}` in a cloze; cloze numbering gaps or more than four deletions; `align`/`equation` environments; a card pointing at a reference-only block; a retired card citing a held-out exam; unknown `contrast` ids; near-duplicate fronts across the course (fronts that differ only in numbers are a deliberate series and are not reported).

## Generated names

- Note types: `Lecture Basic` (fields CardID, Front, Back, Extra, Figure, FigureBack, Source) and `Lecture Cloze` (CardID, Text, Extra, Figure, FigureBack, Source), with fixed model ids shared by all courses. A styling change reaches Anki on the next import with *Update note types* on.
- Note GUID: derived from the card id, so a re-import updates the note in place.
- Decks: `<deck>::<Lxx> <short title>` per lecture file and `<deck>::Exam practice`, frozen in `decks.json` at the first build.
- Tags: `<base>::<Lxx>` on every note, `<base>::exam-practice` on `stage: exam` cards, `<base>::sheet` on cards whose block is on the exam sheet, plus the card's own tags. `<base>` is `<tag_prefix>::<module>` or `<module>`.
- Media: `Anki/media/<card id>.png` (front) and `<card id>-b.png` (back); names never collide across courses as long as module ids differ.
- Every card ends with a source line (module, lecture, slides, `source_ref`, lecture title, card id), so the user can report problems by id.

## Files a session reads and writes

When the course folder lives on another machine, bring these into the working copy (same relative layout):

- the skill's `scripts/`, `templates/` and `requirements.txt`
- `Anki/profile.md`, `Anki/concepts.md`, `Anki/exam-analysis.md` (if present), all of `Anki/cards/*.yaml`, `Anki/decks.json`, `Anki/media/.index.json` and `Anki/media/*.png`
- the new source files and the lecture's readings, plus the source PDFs and `Anki/build/<pdf-stem>/candidates.json` of every earlier lecture you will rebuild (the validator needs them)
- for courses with a summary: `Summary/lectures/*.tex`, `preamble.tex`, `sheet.tex`, `reference.tex`, `title.tex`, `summary.yaml`

Copy back everything that changed: cards, media PNGs and `.index.json`, `concepts.md`, `decks.json`, `profile.md`, `exam-analysis.md`, `build/*.apkg`, the report, the proof html, `build/<pdf-stem>/candidates.json`, and for courses with a summary the changed `Summary/lectures/*.tex`, both PDFs and `Summary/build/report.md`. Afterwards compare file sizes on both sides.
