# Worked example

Everything here is invented: the university, the program, the courses and the student. The program file is `examples/fictional-msc.yaml`.

## The question

A student is about to start a two-year, 120 ECTS master's program and asks:

> I want Deep Learning, Natural Language Processing, Large Language Models, Computer Vision and Causal Inference, and if possible Reinforcement Learning, Medical Imaging and Law and Data. Does that fit? Would it help to sit a fourth exam per semester? Does the first-year Foundations rule get in my way?

That is three questions of the kind this skill exists for: "does it work?", "what would relaxing a restriction buy?", "what does a rule cost?". A hand-built plan would answer each with one or two arrangements and no way to know whether a better one exists.

## Rules from the regulations

Read the (invented) regulations and copy the decisive sentences into the file as `quote:` entries. The ones that matter:

- Total exactly 120 ECTS; 30 ECTS per semester; at most three exams per semester.
- Foundations: "At least 18 ECTS ... from at least two courses (Section 5.1)." Methods core: at least 12 ECTS from at least two courses. Specialisation electives: at least 24 ECTS.
- Minor: "8 to 12 ECTS from at least two courses; further minor courses are not credited (Section 5.4)." Modelled as a maximum of 12; the answer has to say that extra minor courses could still be taken outside the plan.
- Data and society: between 3 and 6 ECTS. Exactly one seminar. Project lab 10 ECTS. Thesis 30 ECTS in the last semester.
- "At least 12 ECTS of Foundations are earned in the first year (Section 6.2)." A period rule, modelled as a limit with `semesters: [Y1-autumn, Y1-spring]`.
- Overlapping courses: Statistical Inference and Bayesian Data Analysis, and Computer Vision and Medical Imaging, are each credited only once (`at_most_one_of`).
- Prerequisites: Deep Learning needs Machine Learning first; Large Language Models needs Natural Language Processing first (`requires`).

Details that would flip the result if misread: "at least" in Sections 5.1 to 5.3 (minimums, not fixed amounts), "not credited" in 5.4 (a cap on what counts), and the period in 6.2.

## The course pool

35 courses from the catalogue, each with credits, category, the term it runs in and whether it has an exam. Optimisation for Machine Learning may count either as Methods core or as an elective, so it gets `category: [methods, electives]`. Data Visualisation, Science Communication and the Project Lab run every semester (no `offered`). The thesis is pinned to the last semester under `rules.fixed`.

## Algebra before the search

- The thesis is pinned and fills the last semester exactly, so the thesis category rule can never fail and the last semester can hold nothing else.
- Spring courses can therefore only go into Y1-spring. Statistical Inference and Bayesian Data Analysis are both spring courses, so "at most one of them" is already enforced inside that single semester.
- Spring has three exam slots, and Deep Learning, Large Language Models and Computer Vision all have exams. The first-year rule needs 12 Foundations ECTS in year one, and no Foundations course has more than 8 ECTS, so year one needs two Foundations courses, each with an exam. Deep Learning and Large Language Models also pull their prerequisites (Machine Learning, Natural Language Processing, both with exams) into the first autumn. Expect the exam slots to be the bottleneck.

The solver confirms the first two points itself: the report lists both rules under "Rules that every semester combination already meets".

## Running it

```bash
python3 scripts/solve_plan.py examples/fictional-msc.yaml
```

Baseline part of the report (trimmed):

```text
  semester   term    load             valid course combinations
  Y1-autumn  autumn  exactly 30 ECTS  2,766
  Y1-spring  spring  exactly 30 ECTS  1,802
  Y2-autumn  autumn  exactly 30 ECTS  2,766
  Y2-spring  spring  exactly 30 ECTS  1
  combined in the order Y2-spring, Y1-autumn, Y2-autumn, Y1-spring; largest intermediate state count 13,171; 1.33 s

Valid plans: 634,942
Best wish weight: 11 of 15 (5 of 8 wished courses)
Plans with the best weight: 16

Wished courses
  course  title                        weight  in some plan  best weight with it
  ELE110  Natural Language Processing  3       yes           11
  MTH210  Deep Learning                3       yes           11
  ELE210  Computer Vision              2       yes           10
  ELE260  Large Language Models        2       yes           11
  MTH120  Causal Inference             2       yes           11
  ELE220  Reinforcement Learning       1       yes           10
  MIN110  Medical Imaging              1       yes           11
  SOC210  Law and Data                 1       yes           10
  Never together: ELE210 + MIN110
  Largest combinations of wished courses that fit (11):
    weight 11: ELE110, MTH210, ELE260, MTH120, MIN110; drops ELE210, ELE220, SOC210
    weight 10: ELE110, ELE260, MTH120, ELE220, MIN110, SOC210; drops MTH210, ELE210
    weight 10: ELE110, ELE210, ELE260, MTH120, SOC210; drops MTH210, ELE220, MIN110
    ...
```

Price of the variants in the file:

```text
  variant                          valid plans  change      best weight  change
  baseline                         634,942                  11
  four exams per semester          4,458,035    +3,823,093  12           +1
  no first-year foundations rule   803,349      +168,407    11           0
  minor up to 15 ECTS              733,937      +98,995     11           0
  must keep Large Language Models  27,271       -607,671    11           0
```

The baseline alone takes about one second. The whole file, baseline plus four variants, takes about ten seconds; the four-exam variant is the largest search, with about 4.5 million valid plans.

## Turning the numbers into an answer

Numbers first, then the plans in words:

> The program allows 634,942 valid plans. The best keeps five of your eight wished courses (weight 11 of 15): Natural Language Processing, Deep Learning, Large Language Models, Causal Inference and Medical Imaging. Sixteen plans reach that, and they differ only in interchangeable choices: Probability and Statistics or Linear Algebra, Algorithms for Large Data or Statistical Inference, Ethics of AI or Technology and Society, Data Visualisation or Probabilistic Programming.
>
> Computer Vision and Medical Imaging can never both count (Section 7.1). Every wished course fits into some plan, but Computer Vision, Reinforcement Learning and Law and Data each cost one point: with any of them the best is 10. The reason is the exam limit: the only free spring semester has three exam slots, Deep Learning and Large Language Models take two, and their prerequisites plus the first-year Foundations courses fill the first autumn.
>
> A fourth exam per semester would raise the best to 12 by adding Law and Data. The first-year Foundations rule costs you nothing in wishes: dropping it gives more plans but the same best weight. Raising the minor cap would not help either. Insisting on Large Language Models leaves 27,271 plans, still with the best weight 11, so keeping it is free.
>
> Best plan: in the first autumn Natural Language Processing, Probability and Statistics, Machine Learning, the statistics seminar and Ethics of AI; in spring Deep Learning, Large Language Models, Algorithms for Large Data, Data Visualisation and Cloud Computing; in the second autumn Database Systems, Medical Imaging, Genomics, Causal Inference and the Project Lab; then the thesis.

Then the open points from the list of what the solver cannot check, for the recommended plan:

- Timetable: Deep Learning and Large Language Models in the same spring semester; check for lecture and exam-date clashes.
- Seats: the Project Lab and the seminar may have limited places or an application.
- Next year's catalogue: confirm that Medical Imaging and Causal Inference run again in the second autumn.
- Workload: three exams plus two project courses in spring.

## Saving the findings

Write a note where the student keeps records, for example "Study plan, solver run of 2026-10-10":

- the question in one sentence;
- the rules with their quotes and the catalogue date;
- the counts: 634,942 plans, best weight 11, the wished-course table and the never-together pair;
- the variant table;
- the recommended plan and the open checks;
- rejected variants with their reason, for example "fourth exam per semester: buys Law and Data (+1) but the regulations do not allow it; kept for reference". Do not delete rejected variants: when the same question comes back, the full search is already there.
