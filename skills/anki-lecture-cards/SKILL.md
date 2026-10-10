---
name: anki-lecture-cards
description: Turn course material (lecture slides, mandatory readings, exercise sheets with solutions, old exams, quiz reviews, notebooks, lecture recordings with subtitles) into Anki flashcards that live as one YAML file per lecture and are built into .apkg packages with stable note ids, one subdeck per lecture and a held-back exam-practice stage, plus, where the exam allows one, a LaTeX exam summary sheet. Use whenever the user mentions Anki, flashcards or spaced-repetition cards for a course, asks to turn a lecture, slide deck or week of material into cards, prepares for an exam with cards, wants a card fixed, rewritten or retired by its id, asks about leeches or cards that keep failing, or wants an exam summary sheet, cheat sheet or formula sheet built or extended.
---

# Anki cards from lecture material

The goal is an excellent exam result, so every card has to earn its place: it trains something the exam can ask (state, derive, compute, decide, spot the pitfall), it can be answered in isolation months later, and it does not collide with its neighbours. The cards live in YAML files in the course folder and the scripts build Anki packages from them, never the other way round. Because ids are stable, any earlier card can be corrected later without losing its review history.

Talk to the user in the language they write in. Write cards in the course language (`language:` in the profile).

The scripts live in this skill's `scripts/` directory (written `scripts/` below; use its full path when you run them from elsewhere). Install their dependencies once with `pip install -r requirements.txt` from the skill directory. Every script takes the course folder as its argument.

Procedures marked *optional* apply only when the course profile asks for them (two phases per lecture, graded quizzes, summary sheet, held-out mock exam). Never carry one course's special rules over to another course.

## Where things live

The user keeps one folder per course, anywhere they like, with the lecturer's files under their original names (sub-folders such as `exams/` or `readings/` are fine) and their own notes next to them. Everything card-related lives in the course folder's `Anki/` subfolder:

| path | content |
|---|---|
| `Anki/profile.md` | course facts, exam format, notation, emphasis, exclusions, interference hotspots, log; read it first |
| `Anki/concepts.md` | generated index of every card, one line each: the cross-lecture memory; never edit it by hand |
| `Anki/exam-analysis.md` | optional: the old exams analysed ([references/exam-analysis.md](references/exam-analysis.md)) |
| `Anki/cards/L03.yaml` | the cards of lecture 3 (`X01.yaml` and up for material that is not a lecture, such as a review session) |
| `Anki/decks.json` | generated: the frozen subdeck name of each lecture file; never edit an entry after its import |
| `Anki/media/` | figure crops named by card id, plus the crop cache `.index.json` |
| `Anki/build/` | packages, reports, proof sheets, and per source PDF a folder `<pdf-stem>/` with pages, montage, contact sheets, `text.md`, `candidates.json` |
| `Summary/` | optional: the summary sheet ([references/exam-sheet.md](references/exam-sheet.md)) |

Every path inside a card file is relative to the course folder, so the folder can move (for example into an archive at the end of term). New sources are the files in the course folder that no card file references yet (`source_pdf`, `figure.pdf`, `sources_extra`), matched to the lecture the user names.

Work where you can render pages and look at images; looking at every slide is part of the job. If the course folder sits on another machine than the one where you run the scripts, copy over what a build needs and afterwards copy back every file that changed ([references/card-schema.md](references/card-schema.md#files-a-session-reads-and-writes) lists both). Never leave the course folder with half a build.

### Setting up a new course

1. Create `Anki/profile.md` from `templates/profile-template.md`. Choose a short `module` id (letters and digits, unique across the user's Anki collection, because note GUIDs derive from card ids) and the `deck` name. Both are permanent once cards are imported.
2. Fill the profile before writing any card: from the course website or learning platform, the course catalogue entry, the organisational slides of the first lecture and, above all, old exams. Exam format and allowed material decide what has to be memorised and what only understood. Material behind a password is the user's download; never enter credentials yourself.
3. If old exams exist, analyse them once ([references/exam-analysis.md](references/exam-analysis.md)).
4. If the exam allows a summary or formula sheet and LaTeX is installed, run `python scripts/summary.py init <course>`.
5. Point the user to [references/anki-setup.md](references/anki-setup.md) for the one-time Anki settings.

`examples/linear-algebra/` is a small complete course (profile, one lecture file, slides, a summary block) to copy patterns from.

## Session protocol (one lecture)

1. **Read the course.** `Anki/profile.md`, all of `Anki/concepts.md`, `Anki/exam-analysis.md` if present, and for courses with `Summary/` also `Summary/build/report.md` (budget per lecture) and the earlier `Summary/lectures/*.tex`. If the profile is still a blank template, fill it first (see above). If the exam analysis covers only earlier lectures, extend it for this lecture before writing cards.

2. **Prepare the sources.** `python scripts/slides.py prepare <course>/<slides>.pdf` renders the pages, detects figure candidates and writes contact sheets and `text.md` into `<course>/Anki/build/<pdf-stem>/`. Do the same for exercise and solution PDFs. Convert other formats first: PPTX with `soffice --headless --convert-to pdf`, notebooks with `jupyter nbconvert --to markdown` or by reading the JSON cells (print a notebook to PDF when one of its plots should become a figure). Every lecture has its exercise sheet among its sources, or the profile says why not.
   If the exercise sheets live in a Git repository, clone it fresh and read the solutions there. Such repositories often keep last year's sheet until the current one is posted: record in the profile which version each lecture's cards use, and at the start of every session check for sheets changed since the last one (`git log --since=<date>`). For a figure behind a link you cannot fetch, view it with a browser tool if you have one, recompute what it shows, or ask the user.

3. **Look at every slide.** `python scripts/slides.py montage <course>/Anki/build/<pdf-stem>` tiles four pages per sheet into `montage/`. Read every sheet, and open single pages from `pages/` where a sheet is too small (dense tables, code, formulas). For long decks with many animation builds, a first pass with `--per 9 --cols 3 --width 600` is enough for the text slides; open diagrams individually. Formulas, plots and diagrams live in the pictures; `text.md` is for grep and exact quoting, not for understanding. Check handwritten annotations against the typeset slides and the script, because they can contain slips. If only an unannotated deck is out yet (slides written on live), take the missing content from the recording and check it against the annotated deck once that appears.
   Keep a scratch list while reading: per slide the card ideas or the reason to skip; the lecturer's statements about the exam; interference pairs, within the lecture and against `concepts.md` (`grep -i <term> <course>/Anki/cards/*.yaml` shows the earlier wording); figures worth a card (the contact sheets `contact/pNNN.png` show candidate ids and a 0.1 grid).
   - **Recordings.** If lectures are recorded with subtitle files (WebVTT or SRT), the subtitles are the best source for what the lecturer stresses, writes on blank slides or explains beyond the slides. Find the caption file's link on the video page (a browser tool helps; such links often work without a login), download it and read the whole transcript. Where recordings are long and old exams exist, the exams usually say more about emphasis; then read captions only where a slide's weight stays unclear.
   - **Readings.** If the course assigns mandatory readings per lecture (textbook chapters, papers, script sections), read them in full before writing the lecture's cards: they are exam material in their own right, and exams ask "according to the paper". Take the list from the course page and the PDFs from the course folder; ask the user for missing ones. Extract the text with page markers, keep section numbers, and cite them in `source_ref` (`"Textbook §3.6.2"`, `"Author et al. 2011, §8"`). Depth follows the old exams and the chapter's learning objectives: what they test gets a card, a detail that only sharpens a slide card goes into that card's `extra`, numbers become insight or `extra`. Where slides and reading disagree, the card follows the current slides and names the reading's version in `extra`; where a reading simplifies something the exams use in its original form, card the original and say so.
     Learning objectives at the end of a chapter are a **coverage floor**: at the end of the lecture's first session, check every objective against the cards and card any that has none, even where the leave-out rule below would skip its slide. Objectives only add. They are a self-assessment list, not the syllabus, so an objective that sounds narrower never shortens or removes a card that slides, readings or exams support.
   - **Graded quizzes** (optional). If the course has graded online quizzes whose reviews show the right answers after closing, read the reviews of every quiz closed since the last session, in the user's browser through a browser tool where the user is logged in. Never enter credentials, never start or submit an attempt. A statement an existing card already answers becomes a trap line in that card's `extra`; a new angle becomes a card in the lecture it belongs to. Cite `source_ref: "Quiz 3.1"`.
   - **Summary blocks** (optional, courses with `Summary/`). Before the cards, write `Summary/lectures/L03.tex` following [references/exam-sheet.md](references/exam-sheet.md).

4. **Write `Anki/cards/L03.yaml`** following the principles, forms and schema below. Ids run `<Module>-L03-001` upward. For long lectures write in chunks of about 15 slides, then do one integration pass over the whole file. Cards from old exams cite the sitting in `source_ref` and sit next to the slide cards they belong to.
   Mark `stage: exam` on cards that are too hard for the first pass: worked problems from old exams, traps that need the concept to be routine, and cards that use a later lecture. An exam-based card that asks a definition or condition the lecture itself teaches stays in the first pass. Mark `sheet: L03.n` on a card whose formula is printed in that sheet block. Core identities named in the profile keep full-recall cards even when they are on the sheet (there is no time to look them up in the exam); other long formulas on the sheet get cards on structure, conditions and use, not symbol by symbol.

5. **Validate, build, render.**
   - `python scripts/validate.py <course> --lecture L03`: fix every error and weigh every warning. A near-duplicate warning within a deliberate series is fine; one between two unrelated cards is a real interference problem.
   - `python scripts/build_deck.py <course> --lecture L03`: writes the `.apkg`, `concepts.md`, `decks.json` and `build/L03-report.md`.
   - `python scripts/proof_sheet.py <course> --lecture L03 --check --shots 60`: writes the proof html, checks MathJax and images in headless Chromium and screenshots the cards into `build/proof/`. Look at the screenshots of derivations, tables and figure cards (tile several into one image to look at them cheaply). Long display formulas overflow the card width: split them with `aligned`. A Markdown list needs a blank line before it. Without Playwright, run it without `--check` and tell the user the render check was skipped.
   - `python scripts/summary.py build <course>` (courses with `Summary/`): lints the blocks, compiles `<Module>-exam-sheet.pdf` and `<Module>-reference.pdf` and writes `Summary/build/report.md` with each lecture's share of the sheet. Render the sheet to PNG and look at it; if the lecture is far over its target, move material to the reference or compress it with `\sheetonly`.
   - Read the coverage table in the report: every slide has cards or an honest reason.
   - After a change to a script, the note types or the HTML conversion, also read the `.apkg` back (a zip holding a SQLite collection; `tests/test_anki_pipeline.py` shows how) and check note fields and deck names.

6. **Independent review.** When the session produced more than about 30 cards, hand the review to a subagent with [references/REVIEW-CHECKLIST.md](references/REVIEW-CHECKLIST.md), the profile, the YAML file(s), `concepts.md`, the page images and screenshots, the readings as text with page markers, and `exam-analysis.md`. Ask for a ranked list of concrete edits (id, new wording, why, citing the slide), plus missing content and cards to drop. For courses with `Summary/` the same reviewer checks every formula of the new blocks, the `stage` classification in both directions, the `sheet` marks, and that nothing comes from a held-out exam. Apply what you agree with, rebuild and re-run the proof check. For small batches apply the checklist yourself, card by card, with the slides open.

7. **Deliver.** Give the user the `.apkg`, the proof html and (courses with `Summary/`) both summary PDFs, and make sure every changed file is in the course folder. Tell them in a few sentences: how many cards, how many wait as exam practice, what to look at in the proof sheet, how much of the sheet the lecture uses, that the first import of a lecture creates its subdeck with default options, that re-imports need *Update notes: Always*, and which retired ids to delete. Name every lecture whose exam-practice cards are due for release under the profile's rule, with the browser search from the report; once the user has moved them, add the lecture to `exam_practice.released` in the profile. Do not paste the cards into the chat.

8. **Update `Anki/profile.md`** with what the lecture taught about the course: notation, emphasis, exclusions, new interference hotspots, and one log line (date, lecture, card count, what to watch next time).

## Two phases per lecture (optional: `two_phase: true`)

For courses whose current exercise sheet and graded quizzes appear only after the lecture, card each lecture in two sessions, so that the sheet enters once, in its current version, and after the user has worked on it.

- **Phase 1**, right after the lecture: steps 1 to 8 with the slides, readings and old exams, and no cards from the exercise sheet, not even from last year's version, so the sheet the user is about to solve stays unspoiled (last year's solution may only settle an exam item's answer). Deliver the proof sheet and say that the package is *not to be imported yet*: reviews of a lecture start after its phase 2.
- **Phase 2**, after the user has solved the sheet and the quizzes: the current sheet with its official solution as the primary source, since the user's own notes are usually incomplete. Ask what tripped them up or read their attempt; their mistakes become pitfall cards. Fold in the quizzes whose reviews have opened since the last phase 2. Sheet and quiz items follow the trap rule: already covered, nothing or a trap line in `extra`; a new angle, a new card; a worked computation, `stage: exam`. Then steps 5 to 8. The user imports the lecture once, plus *Update notes: Always* for every earlier lecture whose cards changed.
- The profile records per lecture which phase is done and which sheet version the cards use, and its release rule for exam-practice cards accounts for the later start.

## Old exams and held-out mocks

- Analyse a course's old exams once and extend the analysis lecture by lecture ([references/exam-analysis.md](references/exam-analysis.md)). With many sittings, split the work over parallel subagents.
- Without an official solution, an exam item becomes a card only if the slides, the exercise solutions or a course reading settle the answer; cite it as `source_ref: "Exam 2024 Q9 (answer own)"`, and leave out items with two defensible answers.
- Exams the lecturer publishes need no check. Exams from a collection whose terms forbid passing them to AI tools are used only after the user confirms they may; record the answer in the profile.
- An exam listed in the profile's `held_out_exams` is kept for a mock exam. No card, `extra`, `source_ref` or sheet line may come only from it or reveal its answers (content that also appears in other sittings, the slides or the script is fine). The validator rejects active cards whose `source_ref` names it. A card retired because of a held-out exam keeps its id but gets placeholder fields, because the proof sheet prints retired cards in full.

## Decks and exam practice

- One deck per course (`deck:` in the profile) with one subdeck per lecture file, `<deck>::L03 <short title>`. The short title is the lecture `title` up to the first dash or colon (at most 40 characters) unless the file sets `deck_title:`. The first build freezes the name in `Anki/decks.json`. Anki keys decks by name, so never change an imported name, neither in `decks.json` nor in the profile's `deck:`.
- Re-imports update note fields but never move existing cards to another deck and never delete notes. As long as the user has reviewed nothing in a course, deleting the course deck and importing all its lecture packages fresh is the clean way to re-file cards and to drop retired notes. Otherwise the user moves cards in Anki's browser (search `CardID:<id>` or the lecture tag, then *Change Deck*).
- Every deck an import creates gets Anki's **Default** options preset; a package cannot carry one. So the user's study settings belong in the Default preset ([references/anki-setup.md](references/anki-setup.md)).
- Interleaving comes from studying the course deck, not from filing: Anki mixes the due reviews of all subdecks and gathers new cards lecture by lecture. A single lecture deck is for catching up on that lecture.
- **Exam practice.** Cards with `stage: exam` go into `<deck>::Exam practice` (frozen in `decks.json` under `exam-practice`) and carry the tag `<base>::exam-practice`. The user gives that subdeck a preset with 0 new cards per day once, right after the import that creates it; studying the course deck then skips its new cards. Releasing a lecture means the user moves its cards into the lecture subdeck (the build report prints the browser search); lectures listed in `exam_practice.released` get later exam cards filed into their own subdeck directly. Whatever is still held is released at the start of exam preparation.
- Every note carries the tag `<base>::L03`, where `<base>` is `<tag_prefix>::<module>`, or just `<module>` without a prefix; cards on the exam sheet also get `<base>::sheet`.

## What makes a card good

*Retrieval.* A card is a question whose answer must be produced from memory. Ask for the mechanism ("why does X happen", "how does Y achieve Z"), the exact statement, the computation, the decision; not for a name to be recognised. Yes/no fronts, fronts containing the key term of the answer, and "which of the following" are recognition tests; rewrite them. When the exam itself is true/false or multiple choice, turn its statements into "under which condition / why / give a counterexample" cards.

*Atomicity with judgement.* One idea per card, minimum information on the back, answerable in 5 to 10 seconds. But do not fragment a mechanism whose parts only make sense together (how a TLB and the page table cooperate, how a Kalman update combines prior and measurement): that is a **synthesis card**, and its back may be longer. Derivations and procedures are exempt from the time limit by nature.

*Rigor is not optional.* Simplify phrasing, never logic. A theorem card states the hypotheses; a formula card gives the formula with what each symbol means (and units where physical); a property card gives the precise condition (BIBO stability is \(\sum_n |h[n]| < \infty\), not "bounded input gives bounded output"; "uncorrelated implies independent" needs *jointly* Gaussian variables). Derivations show every step and name the rule before applying it. Keep the lecturer's notation and distinguish domains (continuous \(x(t)\) versus discrete \(x[n]\); estimator versus parameter).

*Coverage over sampling.* If a slide lists variants, types, properties, requirements or formulas, every item gets its own card, never just one as an example. If a slide presents a dichotomy, write a contrast card ("what distinguishes A from B") and make the distinguishing feature the answer.

*Interference is the main enemy.* Concepts that look alike (n- versus p-channel, deadlock versus livelock, UCB versus Thompson sampling, \(\Sigma_{AB}\) versus \(\Sigma_{A|B}\)) get wording that makes the difference explicit, and usually a contrast card in addition. Check against `concepts.md`, not only within the lecture, and add `contrast:` links. Two fronts that read alike but want different answers will be confused; this includes two worked examples that ask the same question of different data.

*Closed sets versus enumerations.* Arbitrary lists ("name six applications") are not cards. A small closed model whose elements form a whole (the three states of short-term scheduling, the CIA triad, the four Coffman conditions) is one card asking for the complete set, because the set *is* the concept; if the set has more than five elements, cloze the elements individually. Synonym lists become term-to-concept cards ("what does a document store call a row?"), not lists to reproduce.

*Charts and history become insight.* Never ask to reproduce numbers, dates or orderings; ask for the comparative insight or the surprising fact the chart is there to show. Reference numbers belong in `extra`, unless the lecturer demands them by heart.

*Technical precision where the exam wants it.* Commands, flags, paths, return values, register names, query syntax, code output: ask for the exact thing ("what does `fork()` return in the child") and never accept a vague description as an answer. "What does this code print" cards test control flow. Elementary syntax the learner already commands is not a card (the profile says what that is).

*Exam orientation.* Slides are not the only source. Mandatory readings are exam material in their own right, and exercise sheets and old exams show the question types that recur. Turn them into **procedure cards** (the steps of a method, executable by hand), **worked-example cards** (a small instance on the front, the solved result on the back, the method visible in the answer) and **pitfall cards** (the mistake the solution warns about, and the distractor patterns of multiple-choice options). Weight coverage by what the exam asks, as recorded in the profile, and tag lecturer- or exam-flagged items `exam::core`.

*Only what the sources support.* The back of a card states what the lecture or its mandatory reading states; a reviewer will check the slide or the cited section. General knowledge that helps may go into `extra`, marked as such.

*Completeness over count.* Card everything examinable. Never prune or cap a lecture for its card count, and when in doubt whether something is examinable, card it. If the profile sets a different preference (a card budget, topics to leave to the summary sheet), follow it.

*Leave out* administrative slides, self-explanatory statements, things trivially memorised in the moment, decoration, citations, anecdotes and dates, and anything the profile excludes, unless a learning objective names it (see *Readings*). Mnemonics only when they clearly help.

*Self-test before finishing.* Would the question make sense in isolation months from now? Is there exactly one right answer? Would the learner, having answered it, be better at the exam?

## Card forms

| form | use it for | notes |
|---|---|---|
| **basic** | mechanisms, definitions with conditions, contrasts, pitfalls, procedures, worked examples, code output | the backbone, at least 70 % of the cards |
| **cloze** | a formula or theorem statement where the surrounding text is worth re-reading and one element is the retrieval; ordered steps (one deletion per step); a classification whose labels are the confusable part | never for arbitrary sentences; each deletion must be a distinct retrieval |
| **figure on the front** | interpretation (what does this plot show, why this shape, which regime), reading values off a diagram, "compute X on this small graph", "which rule does this table violate" | crop tight; mask captions, labels, arrows and handwriting that leak the answer; tag `type::figure` |
| **figure on the back** | the picture as the *answer* (architecture, block diagram, layout) or as memory support after a text answer | cheap, use often |
| **derivation** (basic, `type::derivation`) | proofs and calculations the exam can ask to reproduce | complete steps, rule named before the result; `\[\begin{aligned}...\end{aligned}\]` |
| **procedure / example** (basic, `type::procedure`, `type::example`) | methods examined as calculations; exercise and exam problem types | small instance, method visible in the answer |

For labelled diagrams, use a figure with masks over the labels (there is no image-occlusion note type). Keep `extra` for the one insight that helps encoding (intuition, common error, link to an earlier card), not for a second answer.

## Schema essentials

The full schema, all validator rules and the profile keys are in [references/card-schema.md](references/card-schema.md); `templates/lecture-template.yaml` shows every field by example.

```yaml
module: LinAlg            # = module: in the profile
lecture: L03              # file name L03.yaml; X01 for material that is not a lecture
title: Singular Value Decomposition
source_pdf: L03-slides.pdf                   # relative to the course folder; slide numbers are its pages
deck_title: SVD                              # optional, before the first build only
skipped: [{slides: [1, 2], reason: title, outline}]   # every slide without a card needs a reason
cards:
  - id: LinAlg-L03-001                       # never reused, never renumbered
    type: basic                              # basic: front + back; cloze: text with {{c1::...}}
    front: |
      ...
    back: |
      ...                                    # Markdown, \( \) inline and \[ \] display math
    extra: |
      ...                                    # optional, back only
    figure: {slide: 17, candidate: f1}       # or clip: [x0, y0, x1, y1], or full: true; side, mask, pdf optional
    figure_back: {slide: 17, clip: [0.1, 0.2, 0.9, 0.8]}
    source: [17, 18]                         # slide numbers, and/or source_ref: "Exam 2024 Q3"
    tags: [type::mechanism, topic::svd]      # one type:: tag, 1 to 3 topic:: tags (reuse slugs), exam::core
    contrast: [LinAlg-L02-014]
    stage: exam                              # optional: held in "<deck>::Exam practice" until released
    sheet: L03.2                             # optional: the formula is in summary block L03.2
    status: retired                          # retired cards stay in the file forever; the build skips them
```

Writing rules: math in `\( \)` and `\[ \]` (`$...$` is accepted and converted); `\begin{aligned}` inside `\[ \]`, never `align` or `equation`; tables as Markdown tables (no `|` inside a cell, not even in math: write `\mid`); code in backticks or fenced blocks; no raw `<img>` (use `figure`). YAML block scalars (`|`) keep backslashes literal, so write LaTeX as usual. Clip and mask coordinates are normalised 0 to 1 (clip on the page, mask on the crop, which carries a small padding); read them off the grid on the contact sheet and check the proof screenshot.

Ids: once a lecture has been imported into Anki, a card is never deleted, only retired (`status: retired`); before the first import a card may still be dropped (leave a comment naming the dropped ids). Slides cited in any card's `source:` need no skip entry; every other slide does.

## Cross-lecture protocol

Before writing, read `concepts.md` completely and grep `Anki/cards/*.yaml` for every central term of the new lecture. While writing, reuse topic slugs. If the new lecture refines, generalises or contradicts an earlier card, **edit the earlier card in its own file** (same id) instead of adding a near-duplicate; the rebuild updates it in Anki, where it stays in its lecture's subdeck. Add `contrast:` links in both directions when you write a contrast card. After building, treat a near-duplicate warning (it compares against the whole course) as a decision to make, not noise. Build per lecture, and rebuild the earlier lecture whose card you edited; build the whole course (`--all`) only after a styling change or when the user wants a full re-import.

## Feedback loop

Cards that keep failing are almost always badly built cards or unresolved interference, not a failure of memory. When the user asks which cards run badly, or every few weeks:

- With an AnkiConnect MCP server connected (its tools search notes and cards), find notes in the course deck with `tag:leech` or `prop:lapses>=3`, read their `CardID` fields and review statistics. Without one, ask the user to run the browser search `tag:leech deck:"<deck>"` and paste the ids.
- For each card: rewrite it in its YAML file under the same id (sharpen the front, split it, add the missing contrast card), or retire it.
- Rebuild, deliver, and ask for a re-import with *Update notes: Always*. Retired notes can be deleted through the MCP (search `CardID:<id>`); confirm with the user before deleting anything.

## Corrections

When the user reports a wrong or awkward card they will usually give its id, which is printed at the bottom of every card. Edit exactly that card, keep the id, rebuild the lecture, run the proof check and deliver. If the fix reveals a systematic problem (a notation convention, a kind of question that does not work for this course), record it in the profile so the next lecture does not repeat it.

## What not to do

- Do not write cards from the text dump alone, and do not skip slides you have not looked at.
- Do not ask the user to choose among card drafts in the chat; decide, build, and let them react to the proof sheet.
- Do not add administrative, decorative or trivially obvious content to inflate coverage; the coverage table exists so that omissions are visible and deliberate.
- Do not renumber, reuse or delete ids; do not edit `concepts.md` or `decks.json` by hand; do not change the profile's `deck:` or `module:` after the first import (Anki would create a second deck).
- Do not enter passwords or credentials anywhere; password-protected course material is the user's download.
- Do not leave a build with validator errors or a failed proof check in the course folder.
- Do not use an exam the profile holds out for a mock as a source for cards or the sheet, and do not use an exam collection whose terms forbid AI use without the user's confirmation.
- Do not renumber or reuse summary block ids, and do not use font-size or scaling commands in `Summary/lectures/*.tex`.
