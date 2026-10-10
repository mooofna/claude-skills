# curriculum-solver

A Claude skill for degree and course planning. Instead of sketching two or three study plans by hand, Claude writes the program rules and the course catalogue into one YAML file and runs an exact solver that finds every valid plan.

It answers questions like:

- Do the courses I want still fit, given the credit, category and exam rules?
- Which of my wished courses can never be taken together?
- What does a rule cost me, and what would relaxing it buy?
- If I insist on course X, how much flexibility do I lose?

Hand-built variants are too optimistic for "does it work?" (they miss the combination that fails) and too pessimistic for "what does it cost?" (they miss the arrangement that keeps everything). The solver gives exact counts instead.

## Quick start

```bash
pip install -r requirements.txt
python3 scripts/solve_plan.py examples/fictional-msc.yaml
python3 scripts/solve_plan.py examples/fictional-msc.yaml --json --output result.json
python3 scripts/solve_plan.py examples/fictional-msc.yaml --set rules.max_exams_per_semester=4
```

Excerpt from the example report (a fictional 120 ECTS master's program with 35 courses):

```text
Valid plans: 634,942
Best wish weight: 11 of 15 (5 of 8 wished courses)
Plans with the best weight: 16
  Never together: ELE210 + MIN110

Price of each variant (compared with the baseline)
  variant                          valid plans  change      best weight  change
  baseline                         634,942                  11
  four exams per semester          4,458,035    +3,823,093  12           +1
  no first-year foundations rule   803,349      +168,407    11           0
```

## What it models

Semesters with credit targets (exact or a range) and exam limits; courses with credits, one or several possible categories, the terms they run in, exams and tags; category minimums and maximums for credits and course counts; extra limits over groups of categories, tags or course lists, for the whole plan, per semester or for a period; fixed, pinned and excluded courses; mutually exclusive courses; prerequisites ("A before B"); a weighted wish list with must-keep courses; and variants that change one rule at a time. Any credit system works (ECTS, credit hours, units, decimals).

The search is exhaustive and exact: per-semester subset enumeration with sum pruning, precomputed rule totals, then dynamic programming over semesters with bitset filtering. The example takes about a second.

## Files

| path | content |
| --- | --- |
| `SKILL.md` | Instructions for Claude: method, steps, how to report, what the solver cannot check |
| `scripts/solve_plan.py` | The solver (Python 3.10+, PyYAML) |
| `references/config-format.md` | Program file reference, modelling recipes, command line, JSON output |
| `references/worked-example.md` | The example from question to saved findings |
| `examples/fictional-msc.yaml` | A complete, invented program file |
| `tests/` | pytest suite, including a brute-force cross-check on random programs |

## Tests

```bash
pip install pytest pyyaml
pytest tests
```

## Limits

It checks rules, not reality: seat limits, timetable clashes, single-course admission conditions, late grade publication, course quality and whether a course really runs next year stay with the user. The skill tells Claude to check and name them.
