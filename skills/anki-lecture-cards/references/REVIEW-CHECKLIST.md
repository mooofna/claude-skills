# Review checklist for a lecture's card file

Apply it to every card, with the slides open. The reviewer's job is to find the cards that will fail in three weeks, not to admire the ones that work. Typical outcomes: split, sharpen, merge, add a contrast card, add a figure, retire. Report a ranked list of concrete edits: card id, new wording, why, and the slide or section that supports it.

## Retrieval
- Does the front force *production* of the answer? Yes/no fronts, "true or false", and fronts that contain the answer's key term are recognition, not recall: rewrite.
- Would the question make sense months from now with no slide in front of the learner? References like "this method", "the theorem above", "in the lecture" are context leaks.
- Is there exactly one defensible answer? If two answers are right, either the front is vague or the card should be two cards.
- Can it be answered in 5 to 10 seconds (derivations and procedures excepted)? If not, the card carries more than one idea.

## Atomicity and information
- One card, one idea. A back with several independent facts is several cards (or one cloze note with several deletions if the sentence itself is worth re-reading).
- Minimum information on the back, but *never* below the rigor of the source: a formula card shows the formula with the meaning of each symbol; a condition card states the precise condition.
- Enumerations: lists of arbitrary items are weak. Closed, small models (at most five elements that form a whole) are fine as one card; everything else is split or dropped.

## Correctness and rigor
- Formula transcribed exactly (indices, transposes, norms, conditions, domains)? Compare against the slide image, not the text extraction.
- Derivation cards: every step present, rule named before it is applied, notation consistent (continuous versus discrete, estimator hats, expectation subscripts).
- Terminology is the lecturer's, not a textbook synonym, unless the card deliberately maps the two.
- The back states only what the slides or the mandatory readings support; anything else is marked as general knowledge in `extra`.

## Interference
- For every pair of similar concepts (in this lecture or against `concepts.md`): does the wording of each card make the distinguishing feature the *answer*, not incidental text? Is there a contrast card?
- Two cards whose fronts read alike but expect different answers will be confused: merge them into a contrast card or make the fronts unmistakably different.

## Exam value
- Does the card move the learner towards solving an exam problem (apply, derive, decide, compute, spot the pitfall), or is it trivia (dates, names, slide decoration)? Trivia goes.
- Are the emphasis signals in the profile reflected (procedures for methods examined as calculations, worked examples for recurring exercise types)?
- Coverage: is anything examinable missing (a list item without its card, a learning objective without a card, a recurring exam question type without a procedure or example card)?

## Figures
- Figure on the front: does the picture give the answer away (labels, captions, titles)? Mask or crop.
- Is the crop clean (no stray slide text, no cut-off axis labels)? Look at the proof-sheet screenshot.
- Does a figure card ask for *interpretation* (what does this show, why this shape, what changes if ...) rather than for a caption?

## Mechanics
- Validator warnings addressed or consciously accepted.
- Coverage table: every slide has cards or a reason, and the reasons are honest ("decoration" is not a reason for a slide with a theorem on it).
- Tags: one `type::` (plus `type::figure` for a front figure), 1 to 3 `topic::`, topics reuse the course's existing slugs (grep `concepts.md`).

## Exam practice and held-out exams
- `stage: exam` only for worked old-exam problems, traps that need the concept to be routine, and cards that use a later lecture. An exam-based card that asks a definition or condition the lecture itself teaches belongs in the first pass. Check each card in both directions.
- No card, `extra` or `source_ref` may come only from an exam the profile holds out for a mock, and no card may reveal its answer (content that also appears in older sittings, the slides or the script is fine).
- A card retired because of a held-out exam keeps its id but gets placeholder fields: the proof sheet prints retired cards in full. Check the summaries in `exam-analysis.md` (outside the held-out sitting's own sections) and the profile for answers of the held-out sitting as well.

## Summary sheet (courses with `Summary/`)
- Every formula in the new blocks checked against the slide image or the script, with its conditions (independence, joint Gaussianity, invertibility, index ranges).
- Lines marked as typical wrong answers (`\slip{...}`) state the *wrong* claim a distractor uses, never a true statement.
- Sheet selection: long, easy-to-garble, cross-lecture formulas go on the sheet; basics the cards keep in the head stay reference-only. Report what is missing that the old exams need and what wastes space.
- `sheet:` marks point at formulas printed in the sheet version of the block (not only inside `\refonly`).
