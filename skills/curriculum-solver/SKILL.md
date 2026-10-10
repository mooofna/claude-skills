---
name: curriculum-solver
description: Answer degree and course planning questions by enumerating every valid study plan instead of hand-building two or three variants. Use when someone asks which courses still fit, whether a plan satisfies the program regulations (total credits, category minimums and maximums, exams per semester, prerequisites, courses that run only in some terms), how to spread courses over semesters, what a rule or restriction costs, or what relaxing one would gain. Works for any university, program and credit system (ECTS, credit hours, units). Builds a YAML program file from the regulations and the course catalogue, then runs an exact solver that counts all valid plans, ranks them by the courses the user wants to keep, shows which wished courses can never be combined, and prices each variant as the change in plan count and best score.
---

# Curriculum solver

Treat a study-plan question as a combinatorial problem. When the question has the shape "does X still work?", "what does restriction Y cost?", "what do I gain if Z is relaxed?" or "does the spread over semesters stay the same?", do not build two or three plans by hand and compare them. Search the whole solution space with `scripts/solve_plan.py` and answer with numbers.

## Why hand-built variants fail

Hand-built variants are wrong in a predictable direction:

- For "does it work?" they are too optimistic. You find one arrangement that works and miss the combination that fails, for example the exam limit in the only semester where a required course runs.
- For "what does it cost?" they are too pessimistic. You miss the alternative arrangement that keeps everything, so a harmless restriction looks expensive.

The solver checks every combination, so both answers become exact: how many plans exist, how much of the wish list survives, and what changes when one rule changes.

## Steps

1. **Pin down the question and what the user wants to keep.** Write the question in one sentence. Get the wish list: courses with weights, and which ones are must-keep. Decide, and say in the answer, whether the wish list measures preference (the courses the user wants) or conservativeness (the courses of the current plan, so the ranking measures how little has to change). Rank by what the user wants to keep, never by your own taste.

2. **Take the hard rules from the primary source.** Use the program regulations for the user's intake year (study regulations, degree requirements, program handbook), not memory, forum posts or an advisor's summary. Quote the decisive wording in the program file (`quote:`) and in your answer. Small words flip results, so read for:
   - "at least" versus an exact number versus "at most", and whether the total is exact or a minimum;
   - whether credits above a category maximum are refused or merely not counted;
   - whether one course can count in several categories (usually it counts in exactly one; the user may get to choose which);
   - what counts as an exam for an exam limit (written session exams only, or end-of-term exams and graded projects too);
   - rules tied to a period ("in the first year", "before the thesis") and prerequisites between courses.

   If the wording is ambiguous, say so, model the reading you think is right, and run the other reading as a variant.

3. **Build the complete course pool from the catalogue.** For every candidate course record the id, title, credits, category (or several when the user may choose), the terms or semesters it runs in, whether it has an exam, and tags you may need for rules (project, language, department). Check the planning years: courses that run every other year, new or discontinued courses, courses that move term. An incomplete pool gives an incomplete answer, so include too many courses rather than too few and exclude later with `rules.excluded`. Record the date of the catalogue data.

4. **Cancel constraints algebraically before writing them.** Do the arithmetic once. With fixed credits per semester, a rule such as "core plus electives must equal the total minus thesis, lab and seminar" often holds automatically and needs no check. A category whose only courses are fixed is already settled. The solver also lists rules that every semester combination already meets, but you need to know why in order to explain the result.

5. **Write the program file and run the solver.** Use `references/config-format.md` for every key and `examples/fictional-msc.yaml` as a template.

   ```bash
   pip install pyyaml
   python3 scripts/solve_plan.py program.yaml              # text report
   python3 scripts/solve_plan.py program.yaml --json       # machine-readable
   ```

   Fix every error it reports; messages name the key and suggest the likely intended spelling. Semesters the user has completed become fixed courses pinned to those semesters, with the credits actually earned.

6. **Price restrictions as variants.** Each variant changes one thing: a rule, a limit, a must-keep course, a course moving term, a looser semester load. The solver reports for each the change in the number of valid plans and in the best wish weight, and which wished courses become possible or impossible. Put recurring questions in the `variants:` section; for a one-off question use `--set PATH=VALUE` and `--drop PATH`.

7. **Report numbers first, then plans in plain words.** Lead with: the number of valid plans; the best wish weight and how many wished courses it keeps; which wished courses drop out; which pairs can never be kept together; the price of each variant. Then describe the best two or three plans in sentences (what goes in which semester, what each one gives up), not as a pasted table. If several plans tie, say how many and how the solver broke the tie.

8. **Check what the solver cannot see** (list below) for the plans you recommend, and name the open points in the answer.

9. **Save the findings where the user keeps records** (their notes, a planning document, the repository they work in), not only in the chat. Keep rejected variants instead of deleting them: record the question, the rules and quotes used, the full search (plan counts, best weight, the variant table), the catalogue date and the reason for rejecting. The same question then does not get reopened three weeks later.

## Reading the report

- **Valid course combinations per semester**: subsets that meet that semester's own rules (credit target, exam cap, course caps, pinned courses, per-semester limits). A zero here is the first thing to explain.
- **Valid plans**: the exact number of complete plans. A plan is a set of courses per semester; when a course may count in several categories, plans that differ only in that choice are counted separately.
- **Best wish weight** and **plans with the best weight**: the optimum and how many plans reach it. Ties are ranked by the `ranking.tie_break` criteria, then by course ids in semester order, so the order is deterministic.
- **Rules that every semester combination already meets**: never binding, or settled inside single semesters. Mention them when the user believed they mattered.
- **Wished courses**: whether each appears in any plan and the best weight achievable with it. **Never together** lists wished pairs that no plan contains. **Largest combinations** lists the maximal sets of wished courses that fit together, with what each drops: this is the menu to discuss with the user.
- **Totals** per plan: credits and course counts per category and per limit next to the rule, so the user can verify the plan by hand.
- **Price of each variant**: plan count and best weight against the baseline.

When nothing fits, the report names the reason and, for plan-wide rules, how many plans exist with each single rule dropped. That list shows which rule is binding.

## How the search works, and what to do when it stops

Crossing every course subset of every semester takes minutes to hours even for a modest program. The solver avoids that:

- Per semester, a depth-first search lists every course subset that meets the semester rules. Courses are sorted by credits so the search stops as soon as even the largest remaining courses cannot reach the credit target, or the target is exceeded.
- Each subset's contribution to the plan-wide rules (credits and course count per category or limit, exams) is computed once.
- Only then are semesters combined, by dynamic programming over states made of the courses a later semester could repeat, the rule totals (capped where a higher value no longer matters) and the semester positions of courses in ordering rules. Bitmaps over the next semester's subsets select the compatible ones before any pair is touched. Counting is exact and nothing is sampled.

The example (35 courses, four semesters, about 635,000 valid plans) takes about one second. If the solver stops with a limit message, the per-semester subset counts show where the space is large. Then pin the courses of semesters already completed, exclude courses the user would never take, tighten the semester credit range, or raise `--max-subsets` or `--max-states`.

## What the solver cannot check

It checks rules, not reality. Check these one by one for the recommended plans and state them in the answer:

- seat limits, waiting lists, application or lottery procedures;
- timetable clashes between lectures, exercise sessions and exam dates;
- prerequisites and admission conditions of single courses, unless you modelled them with `requires`;
- gates whose results arrive too late, for example grades published after the next registration deadline, or a project that needs a confirmed supervisor first;
- course quality, workload and difficulty (reviews, exam statistics);
- whether a course actually runs in the planned year when the catalogue for that year is not yet published;
- administrative steps such as approvals, learning agreements or exceptions.

## Files

- `scripts/solve_plan.py`: the solver (Python 3.10 or newer, PyYAML).
- `references/config-format.md`: every key of the program file, modelling recipes, command line and JSON output.
- `references/worked-example.md`: the fictional example from question to saved findings.
- `examples/fictional-msc.yaml`: a complete program file to copy from.
