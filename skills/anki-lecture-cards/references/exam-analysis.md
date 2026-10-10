# Analysing old exams

Old exams show what the course really examines: the format, the weight of each topic, and the question types that recur. Analyse them once per course into `Anki/exam-analysis.md`, extend the analysis for each new lecture, and read it before writing a lecture's cards.

## Before you start

- **Inventory.** Which sittings exist, where they are (the course folder's `exams/`, the course website, a student collection), and whether official solutions exist. Check each PDF for answers at all: reviews of empty quiz attempts and blank answer sheets contain none.
- **Terms of use.** Exams the lecturer publishes need no check. Exams from a collection whose terms forbid passing them to AI tools are used only after the user confirms they may; record the answer in the profile.
- **Held-out sittings.** Sittings listed in the profile's `held_out_exams` are kept for a mock exam. Leave them out of the analysis entirely and do not open them.
- **Scans.** Screenshot or scanned exams have no text layer. Render them (`scripts/slides.py prepare <exam.pdf> --out <dir>` works for any PDF) and read the page images.

## Structure of `Anki/exam-analysis.md`

Use these fixed sections, so that reports from several agents can be merged section by section:

```markdown
# <Course>: old exams

## 0 Summary for card authoring
- Format and allowed aids, and how they changed over the years.
- Points per topic and per lecture for each sitting (table).
- Recurring question types, each with the card pattern it calls for (procedure, worked example, pitfall,
  contrast, "under which condition") and the lecture it belongs to.

## a Format and aids per sitting

## b Questions per sitting
- Exam 2024 Q1 (8 pts, topic code SVD): one line per question.

## c Questions per lecture
### L03 Singular Value Decomposition
- Exam 2024 Q2 (6 pts): the full question text. Official solution, or "answer own:" with the slide, exercise
  solution or reading that settles it.

## d Recurring question types
```

## The one-time analysis

- Up to about three sittings: do it yourself.
- More: split the sittings over parallel subagents, three to five sittings each. Give every agent the same instruction file (template below) with the fixed sections. Ask each to return its report as its final message rather than writing files, then save the reports yourself, merge them section by section, and write section 0 on top.

### Template for the shared instruction file

```markdown
You analyse old exams of the course <name> for flashcard authoring. Your sittings: <list with file paths>.
Do not open any other sitting. Some PDFs are scans: read the rendered page images in <dir>.

Return one report as your final message, with exactly these sections:
a) Format and aids per sitting (duration, allowed material, number of questions, points).
b) Every question per sitting, one line each: id (e.g. "Exam 2024 Q3"), points, topic code from this list:
   <topic codes, e.g. one per lecture>.
c) For every question on lectures <L01..Lnn>: the full question text and the official solution. If a sitting
   has no official solution, give the answer only when <slides, exercise solutions, readings> settle it, and
   mark it "answer own" with that source; if two answers are defensible, say so and give none.
d) Recurring question types you see in your sittings, with the questions that show them.
Quote formulas exactly; do not summarise questions in section c.
```

## Extending the analysis for a new lecture

When `exam-analysis.md` covers only earlier lectures, extend it before writing the new lecture's cards: parallel agents over the sittings (held-out sittings excluded), one shared instruction file that names the lecture's slides, readings and exercise solution as the answer sources. Merge the results into section c under the lecture's heading, and add the lecture's points per sitting and a pattern-to-card map to section 0.

## From exam items to cards

- Recurring question types become procedure cards (the method, executable by hand) and worked-example cards (a small instance with the solved result); the mistakes the solutions warn about and the distractors of multiple-choice options become pitfall cards. True/false statements become "under which condition / why / give a counterexample" cards.
- Cite the sitting in `source_ref` (`"Exam 2024 Q2"`, or `"Exam 2024 Q9 (answer own)"` without an official key) and place the card next to the slide cards it belongs to.
- Worked problems, traps that need the concept to be routine, and items that need a later lecture get `stage: exam`. An item that asks a definition or condition the lecture itself teaches stays in the first pass.
- Leave out items with two defensible answers.
