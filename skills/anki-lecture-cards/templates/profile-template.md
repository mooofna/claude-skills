---
module: ShortId               # card id prefix: letters and digits only, e.g. LinAlg; unique across your Anki collection
deck: "Full Course Name"      # the course's Anki deck; may be nested ("Uni::2026 Spring::Linear Algebra"); never change after the first import
tag_prefix: ""                # optional prefix of generated tags, e.g. 2026S gives 2026S::ShortId::L03
language: en                  # language the cards are written in (normally the course language)
# subdecks: true              # one subdeck per lecture file (default)
# two_phase: true             # exercise sheets and quizzes are carded in a second session, after the learner solved them
# held_out_exams: []          # sittings kept for a mock exam, as written in source_ref, e.g. ["Exam 2025"]
exam_practice:
  released: []                # lectures whose exam-practice cards the learner has moved into their lecture subdeck
---
# <Full course name>: course profile

The profile is what every card-writing session reads first. Keep it current: every lecture teaches something
about the *course* (notation, emphasis, what the lecturer skips), not only about the subject.

## Course facts
- Course code, lecturer, credits:
- Where the material comes from (learning platform, course website, Git repository, lecture recordings with subtitle files) and what arrives each week (slides, exercise sheet, solution, notebook, quiz):
- Material the learner has to download (password-protected or behind a login):
- Textbook, script or lecture notes the slides follow (a chapter mapping helps to spot omissions):
- Mandatory readings per lecture (where the list is published):

## Exam
- Format (written or oral, duration, date):
- Allowed material (summary sheet, open book, calculator):   (changes what must be memorised versus understood)
- Composition if known (theory questions, derivations, calculations, multiple choice, coding):
- Lecturer statements about relevance ("this will not be examined", "know this proof"):
- Old exams: where they are, which sittings, whether official solutions exist; analysis in `Anki/exam-analysis.md`.
- Terms of use of exam collections: (e.g. "collection X forbids passing exams to AI tools; the learner confirmed on YYYY-MM-DD that they may / may not be used")

## What to emphasise in cards for this course
- (e.g. derivations must be reproducible step by step / algorithms must be executable by hand / system trade-offs must be argued / commands and flags exactly)

## Two phases per lecture (only with `two_phase: true`)
- Why: (e.g. the current exercise sheet and the graded quizzes come out after the lecture)
- Per lecture: phase 1 done / phase 2 done, and which version of the exercise sheet the cards use:

## Graded quizzes (only if the course has them)
- Where the reviews are and when they open:
- How to read them (URL pattern, how answers are shown):

## Summary sheet (only if the exam allows one)
- Rule of the exam (pages, handwritten or typed, minimum font size):
- `scripts/summary.py init <course folder>` creates `Summary/`; set the page budget in `Summary/summary.yaml`.
- What goes on the sheet for this course; which core identities keep full-recall cards anyway:

## Exam practice cards
- Release rule (e.g. after the homework on the lecture has been discussed in the tutorial):
- Exams held out for a mock exam (also listed in `held_out_exams` above; never a card source until after the mock):

## Exclusions
- (e.g. content in grey boxes is background; chapter 0 recap; guest lecture; anything marked "optional")

## Notation and conventions of the lecturer
- (e.g. \(\mathbf{X} \in \mathbb{R}^{n \times d}\), rows are samples; \(\hat{\theta}\) is the estimator; log means natural log; vectors are columns)

## Interference hotspots (grow this list every week)
- (pairs and families that students confuse and that cards must contrast explicitly, e.g. MAP vs MLE vs Bayes posterior)

## Visual knowledge in this course (what earns a figure card)
- (e.g. graphical models, plots of acquisition functions, architecture diagrams, tables of variants)

## Card-style overrides
- (anything that departs from the skill's defaults, e.g. "prefer worked-example cards for chapter 4", "the learner already commands basic SQL; no cards for plain SELECT ... WHERE")

## Log
- YYYY-MM-DD L01: n cards; notes on the lecture's style and what to watch for next week
