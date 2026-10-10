# Program file format

One YAML file (or JSON with the same structure) describes the program, the question and the variants to price. Unknown keys are errors, with a suggestion for the likely intended key, so typos never pass silently.

```yaml
program:     # name, credit unit, source
semesters:   # chronological list
categories:  # category ids with their credit and course bounds
courses:     # the course pool
rules:       # everything else the regulations require
wishes:      # what the user wants to keep
ranking:     # tie-break order and number of plans to show
variants:    # changes to price against the baseline
```

Credits can be any non-negative numbers with up to three decimals (7.5 ECTS, 3 credit hours, 0.5 units). Course credits must be positive.

## program

| key | meaning |
| --- | --- |
| `name` | Shown as the report title. |
| `credit_unit` | Label for credits in the report, for example `ECTS`, `credit hours`, `units`. Default `credits`. |
| `source` | Where the rules and the course data come from, with version or date. Shown under the title. |
| `notes` | Free text, ignored by the solver. |

## semesters

A list in chronological order. Order matters for `requires` and for the tie-break by course ids.

| key | meaning |
| --- | --- |
| `id` | Unique id, used everywhere else (`Y1-autumn`, `2027S`, `Term 3`). A plain string item is shorthand for `{id: ...}`. |
| `term` | Optional term name (`autumn`, `spring`, `fall`, `winter`, `summer`). Courses can say `offered: autumn` to mean every semester with that term. |
| `label` | Optional display name. |
| `credits` | Credit target: a number (exact) or `{min: 27, max: 33}`. Defaults to `rules.semester_credits`. Required one way or the other. |
| `max_exams` | Exam limit for this semester; overrides `rules.max_exams_per_semester`. |
| `min_courses`, `max_courses` | Course count limits for this semester. |

## categories

A mapping from category id to its rules. Every course names one or more of these ids. If the section is missing, categories are taken from the courses and have no bounds.

| key | meaning |
| --- | --- |
| `name` | Display name. |
| `min_credits`, `max_credits` | Bounds on the credits counted in this category over the whole plan. |
| `min_courses`, `max_courses` | Bounds on the number of courses counted in this category. |
| `quote` | The decisive sentence from the regulations. Shown next to the rule in the report. |

A category with no bounds is fine; it still shows up in the per-plan totals.

## courses

| key | meaning |
| --- | --- |
| `id` | Unique course id (catalogue number or a short code). Plans are ordered by these ids when everything else ties; natural order, so `C2` comes before `C10`. |
| `title` | Display title. |
| `credits` | Positive number. |
| `category` | One category id, or a list when the student may choose where the course counts. A course counts in exactly one category per plan; with a list, plans that differ only in that choice are counted separately. |
| `offered` | Where the course runs: a term, a semester id, or a list of both. `any` or leaving it out means every semester. |
| `exam` | `true` (default) or `false`. Counted against exam limits. Set `false` for courses graded without an exam if the regulations' exam limit does not count them. |
| `tags` | Free labels for `rules.limits` (`project`, `taught-in-german`, `dept-math`). |
| `notes` | Free text, ignored by the solver. Good place for review scores or the catalogue link. |

## rules

| key | meaning |
| --- | --- |
| `total_credits` | Number (exact) or `{min, max}`. If the semester targets already force the total, the rule costs nothing; if they contradict it, the report says so before any search. |
| `semester_credits` | Default credit target for every semester. |
| `max_exams_per_semester` | Default exam limit for every semester. |
| `fixed` | Courses that are decided or already completed. `- CS101` means "in the plan, any semester it runs"; `- {course: CS101, semester: Y1-autumn}` pins it to that semester (even if the catalogue says otherwise, which is what you want for completed courses). |
| `excluded` | Course ids that must not appear. |
| `at_most_one_of` | A list of groups; from each group at most one course may be taken (overlapping content, mutually exclusive courses). |
| `requires` | Ordering: `{course: B, after: A}` means B may only be taken if A is taken in an earlier semester. `after` can be a list (all of them). `same_semester: true` also allows A in the same semester as B. |
| `limits` | Named extra rules, see below. |

### rules.limits

A mapping from a name to a rule over a selection of courses. Use it for groups of categories, tags, explicit course lists, period rules and per-semester rules.

| key | meaning |
| --- | --- |
| `categories` | Courses counted in these categories ... |
| `tags` | ... or carrying any of these tags ... |
| `courses` | ... or with these ids. The selection is the union of the three. |
| `min_credits`, `max_credits`, `min_courses`, `max_courses` | Bounds, at least one required. |
| `semesters` | Only count courses taken in these semesters (for "in the first year" rules). |
| `per_semester` | `true` applies the bounds to each semester separately instead of to the plan. |
| `quote` | Decisive wording from the regulations. |

Examples:

```yaml
rules:
  limits:
    core and electives:            # "75 credits from core and elective courses together"
      categories: [core-a, core-b, electives]
      min_credits: 75
    first-year core:               # "at least 20 core credits in the first year"
      categories: [core-a, core-b]
      semesters: [Y1-autumn, Y1-spring]
      min_credits: 20
    projects:                      # "at most two project courses"
      tags: [project]
      max_courses: 2
    one seminar per term:
      categories: [seminar]
      per_semester: true
      max_courses: 1
    statistics track:              # "at least one of these three"
      courses: [STAT301, STAT302, STAT310]
      min_courses: 1
```

## wishes

A list of courses the user wants to keep. Plans are ranked by the sum of the weights of the wished courses they contain.

| key | meaning |
| --- | --- |
| `course` | Course id. A plain string item is shorthand with weight 1. |
| `weight` | Positive number, default 1. |
| `keep` | `true` makes the course mandatory. Use a variant with `keep: true` to price a single course: the drop in plan count and best weight is what keeping it costs. |

To measure how little a plan changes rather than how much the user likes it, list the courses of the current plan as wishes with weight 1 and say so in the answer.

## ranking

| key | meaning |
| --- | --- |
| `tie_break` | Order of criteria after the wish weight. Any of `fewer_exams`, `even_load` (semester loads close to the middle of each semester's credit range), `fewer_courses`, `fewer_credits`. Default `[fewer_exams, even_load]`. Course ids in semester order always decide last. |
| `top` | Number of best plans to show. Default 3. |

## variants

A list of changes to price against the baseline. Each variant has a `name`, an optional `description`, and any of `program`, `semesters`, `categories`, `courses`, `rules`, `wishes`, `ranking` as a patch. Every variant is applied to the baseline on its own; variants do not stack. To price a combination, write it as one variant.

Patch rules:

- Mappings merge key by key; `null` deletes a key (`max_credits: null` removes that bound, `limits: {projects: null}` removes the whole limit).
- A mapping applied to a list edits the list by id: `id` for `semesters` and `courses`, `course` for `wishes` and `fixed`, `name` for list-form limits, the value itself for lists of ids such as `excluded`. `null` removes the item, a mapping updates it or adds it, `true` adds a plain id.
- Anything else replaces the old value.

```yaml
variants:
  - name: four exams per semester
    rules: {max_exams_per_semester: 4}
  - name: without the first-year rule
    rules: {limits: {first-year core: null}}
  - name: keep Deep Learning
    wishes: {DL: {keep: true}}
  - name: Deep Learning moves to autumn
    courses: {DL: {offered: autumn}}
  - name: exclude Databases as well
    rules: {excluded: {DB: true}}
  - name: flexible load
    rules: {semester_credits: {min: 27, max: 33}}
```

## Modelling recipes

- **Completed semesters**: pin the courses taken (`fixed` with `semester`) and set that semester's `credits` to the credits earned. Use the categories they were actually booked in.
- **Thesis or internship semester**: a course pinned to its semester with that semester's credit target equal to its credits.
- **Corequisites (same semester, both or neither)**: two `requires` entries pointing at each other, both with `same_semester: true`.
- **Credits beyond a cap are not counted**: if the regulations allow taking more but only count up to the cap, model the cap as `max_credits` and say in the answer that extra courses could be taken outside the plan.
- **Several exam types**: tag the courses (`session-exam`) and add a `per_semester` limit over the tag with `max_courses`, keeping `exam: false` for the types the regulation does not count.
- **Course taught every other year**: list only the semesters where it runs in `offered`.
- **Semester abroad or part-time semester**: give that semester its own credit range and `offered` lists for the courses available there.
- **Both readings of an ambiguous rule**: model one reading in the baseline and the other as a variant; report both counts.

## Command line

```text
python3 scripts/solve_plan.py PROGRAM [options]

--top N             number of best plans (default ranking.top or 3)
--json              print JSON instead of the text report
--output FILE       also write the report to FILE
--variant NAME      run only this variant from the file (repeatable)
--no-variants       skip the variants in the file
--set PATH=VALUE    ad-hoc variant: set a value, e.g. rules.max_exams_per_semester=4
--drop PATH         ad-hoc variant: remove a key or item, e.g. categories.minor.max_credits
--max-subsets N     stop if one semester has more than N valid subsets (default 200000)
--max-states N      stop if more than N partial-plan states arise (default 1000000)
```

All `--set` and `--drop` flags together form one extra variant. Paths are dotted; list items are addressed by id (`wishes.DL.keep=true`). Values are parsed as YAML, so `4`, `true`, `null` and `{min: 27, max: 33}` work.

Exit codes: 0 report written (also when no plan is valid), 2 error in the program file, 3 search stopped at a limit.

## JSON output

`--json` prints one document:

- `program`, `rules` (the rules as the solver applied them, with quotes);
- `baseline`:
  - `valid_plans`, `reason` (when there are none), `diagnosis` (plan counts with each plan-wide rule dropped, when there are none);
  - `search`: subsets per semester, processing order, largest state count, runtime;
  - `best`: `weight`, `max_possible_weight`, `tied_plans`;
  - `ranking` (the tie-break order in words);
  - `plans`: rank, weight, credits, exams, wished courses kept and dropped, `semesters` with their courses, `totals` per category and limit with the rule and an `ok` flag;
  - `wishes`: per course (`in_some_plan`, `best_weight_with`), `never_together` pairs, `largest_sets` (maximal combinations of wished courses that fit, with what they drop);
  - `never_binding`: rules every semester combination already meets;
  - `notes`;
- `variants`: the same fields for each variant plus `changes` (the patch), `delta` (`valid_plans`, `best_weight`, `now_reachable`, `no_longer_reachable`) or `error`.
