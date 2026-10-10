"""Tests for solve_plan.py: brute-force agreement, single rules, variants, guards, the example."""

from __future__ import annotations

import importlib.util
import itertools
import json
import random
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "solve_plan.py"
EXAMPLE = ROOT / "examples" / "fictional-msc.yaml"
spec = importlib.util.spec_from_file_location("solve_plan", SCRIPT)
sp = importlib.util.module_from_spec(spec)
sys.modules["solve_plan"] = sp
spec.loader.exec_module(sp)


# --------------------------------------------------------------------------- brute force reference


def brute_force(model, k):
    """Try every assignment of every course to 'not taken' or (semester, category)."""
    n = len(model.semesters)
    options = []
    for course in model.courses:
        entries = [e for e in model.entries if e.course is course]
        opts = [None] + [(s, e.index) for s in sorted(course.offered) for e in entries]
        options.append(opts)
    must = set(model.fixed_free) | set(model.keep)
    plans = []
    wish_sets = set()
    for combo in itertools.product(*options):
        taken = {}
        for course, opt in zip(model.courses, combo, strict=True):
            if opt is not None:
                taken[course.bit] = opt
        if any(c.pinned is not None and taken.get(c.bit, (None,))[0] != c.pinned for c in model.courses):
            continue
        if any(b not in taken for b in must):
            continue
        per_sem = [[] for _ in range(n)]
        for s, e in taken.values():
            per_sem[s].append(model.entries[e])
        ok = True
        for sem, ents in zip(model.semesters, per_sem, strict=True):
            credits = sum(e.course.credits for e in ents)
            exams = sum(1 for e in ents if e.course.exam)
            if credits < sem.lo or (sem.hi is not None and credits > sem.hi):
                ok = False
            if sem.max_exams is not None and exams > sem.max_exams:
                ok = False
            if len(ents) < sem.min_courses or (sem.max_courses is not None and len(ents) > sem.max_courses):
                ok = False
        if not ok:
            continue
        total = sum(e.course.credits for ents in per_sem for e in ents)
        if total < model.total[0] or (model.total[1] is not None and total > model.total[1]):
            continue
        for limit in model.limits:
            scope = range(n) if limit.scope is None else sorted(limit.scope)
            groups = [[s] for s in scope] if limit.per_semester else [list(scope)]
            for group in groups:
                ents = [e for s in group for e in per_sem[s] if e.index in limit.members]
                for bounds, value in ((limit.credits, sum(e.course.credits for e in ents)), (limit.count, len(ents))):
                    if bounds is not None and (value < bounds[0] or (bounds[1] is not None and value > bounds[1])):
                        ok = False
        for r in model.requirements:
            if r.course in taken:
                jb = taken[r.course][0]
                ja = taken[r.after][0] if r.after in taken else None
                if ja is None or ja > jb or (ja == jb and not r.same_semester):
                    ok = False
        if not ok:
            continue
        weight = sum(model.weights.get(b, 0) for b in taken)
        wmask = sum(1 << b for b in taken if b in model.weights)
        wish_sets.add(wmask)
        ties = []
        for crit in model.tie_break:
            if crit == "fewer_exams":
                ties.append(sum(1 for ents in per_sem for e in ents if e.course.exam))
            elif crit == "even_load":
                dev = 0
                for sem, ents in zip(model.semesters, per_sem, strict=True):
                    hi = sem.hi if sem.hi is not None else sem.lo
                    dev += abs(2 * sum(e.course.credits for e in ents) - sem.lo - hi)
                ties.append(dev)
            elif crit == "fewer_courses":
                ties.append(sum(len(ents) for ents in per_sem))
            else:
                ties.append(total)
        plan = tuple(tuple(sorted(e.index for e in ents)) for ents in per_sem)
        plans.append(((-weight, *ties, plan), weight, plan))
    plans.sort()
    best = max((w for _, w, _ in plans), default=-1)
    return {
        "count": len(plans),
        "best": best,
        "n_best": sum(1 for _, w, _ in plans if w == best),
        "plans": [p for _, _, p in plans[:k]],
        "maximal": sorted(sp._maximal(wish_sets)) if (plans and model.weights) else ([0] if plans else []),
    }


def random_program(seed: int) -> dict:
    rng = random.Random(seed)
    n_sem = rng.choice([2, 3])
    semesters = [{"id": f"S{i + 1}", "term": "ab"[i % 2]} for i in range(n_sem)]
    cats = ["core", "elec", "free"][: rng.choice([2, 3])]
    courses = []
    multi = 0
    for i in range(rng.randint(6, 9)):
        course = {"id": f"C{i}", "credits": rng.choice([1, 2, 2, 3, 3, 4]), "category": rng.choice(cats)}
        if multi == 0 and rng.random() < 0.2:
            course["category"] = rng.sample(cats, 2)
            multi += 1
        r = rng.random()
        if r < 0.25:
            course["offered"] = "a"
        elif r < 0.4:
            course["offered"] = "b"
        elif r < 0.5:
            course["offered"] = [rng.choice(semesters)["id"]]
        course["exam"] = rng.random() < 0.6
        if rng.random() < 0.3:
            course["tags"] = ["t"]
        courses.append(course)
    for sem in semesters:
        if rng.random() < 0.25:
            sem["credits"] = rng.randint(2, 5)
        else:
            lo = rng.randint(0, 3)
            sem["credits"] = {"min": lo, "max": lo + rng.randint(2, 5)}
    rules: dict = {}
    if rng.random() < 0.4:
        rules["max_exams_per_semester"] = rng.choice([1, 2])
    if rng.random() < 0.3:
        lo = rng.randint(3, 8)
        rules["total_credits"] = {"min": lo, "max": lo + rng.randint(0, 4)}
    categories = {}
    for cat in cats:
        spec = {"name": cat.title()}
        if rng.random() < 0.3:
            spec["min_credits"] = rng.randint(1, 3)
        if rng.random() < 0.25:
            spec["max_credits"] = spec.get("min_credits", 0) + rng.randint(1, 4)
        if rng.random() < 0.2:
            spec["min_courses"] = 1
        if rng.random() < 0.15:
            spec["max_courses"] = spec.get("min_courses", 0) + rng.randint(0, 2)
        categories[cat] = spec
    ids = [c["id"] for c in courses]
    limits = {}
    if rng.random() < 0.3:
        limits["tagged"] = {"tags": ["t"], "max_courses": rng.randint(0, 2)}
    if rng.random() < 0.25:
        limits["per semester"] = {"courses": rng.sample(ids, 3), "per_semester": True, "max_courses": 1}
    if rng.random() < 0.25:
        limits["early"] = {"categories": [cats[0]], "semesters": ["S1"], "min_credits": rng.randint(1, 3)}
    if limits:
        rules["limits"] = limits
    if rng.random() < 0.3:
        rules["at_most_one_of"] = [rng.sample(ids, 2)]
    if rng.random() < 0.4:
        a, b = rng.sample(ids, 2)
        rules["requires"] = [{"course": b, "after": a, "same_semester": rng.random() < 0.3}]
    pool = list(ids)
    rng.shuffle(pool)
    if rng.random() < 0.3:
        rules["fixed"] = [{"course": pool.pop(), "semester": rng.choice(semesters)["id"]}]
    if rng.random() < 0.2:
        rules.setdefault("fixed", []).append(pool.pop())
    if rng.random() < 0.2:
        rules["excluded"] = [pool.pop()]
    wishes = []
    for cid in rng.sample(pool, min(len(pool), rng.randint(0, 4))):
        wish = {"course": cid, "weight": rng.choice([1, 1, 2, 3])}
        if rng.random() < 0.1:
            wish["keep"] = True
        wishes.append(wish)
    ties = list(sp.TIE_BREAKS)
    rng.shuffle(ties)
    return {
        "semesters": semesters,
        "categories": categories,
        "courses": courses,
        "rules": rules,
        "wishes": wishes,
        "ranking": {"tie_break": ties[: rng.randint(0, 4)], "top": rng.randint(1, 5)},
    }


def solver_summary(result):
    return {
        "count": result.count,
        "best": result.best_weight,
        "n_best": result.n_best,
        "plans": result.plans,
        "maximal": sorted(result.maximal),
    }


SEEDS = range(80)


@pytest.mark.parametrize("seed", SEEDS)
def test_matches_brute_force(seed):
    model = sp.build_model(random_program(seed))
    expected = brute_force(model, model.top)
    assert solver_summary(sp.solve(model)) == expected


@pytest.mark.parametrize("seed", range(0, 80, 4))
def test_processing_order_does_not_change_result(seed, monkeypatch):
    model = sp.build_model(random_program(seed))
    expected = solver_summary(sp.solve(model))
    monkeypatch.setattr(sp, "choose_order", lambda m, tables: list(reversed(range(len(m.semesters)))))
    assert solver_summary(sp.solve(model)) == expected


def test_random_programs_are_mostly_feasible():
    counts = [sp.solve(sp.build_model(random_program(seed))).count for seed in SEEDS]
    assert sum(1 for c in counts if c) >= len(counts) // 2
    assert max(counts) > 1000


# --------------------------------------------------------------------------- single rules, hand-counted


def program(courses, semesters=None, rules=None, categories=None, wishes=None, ranking=None):
    cfg = {
        "semesters": semesters or [{"id": "S1", "credits": 4}],
        "courses": [{"category": "x", "exam": False, **c} for c in courses],
    }
    if categories is not None:
        cfg["categories"] = categories
    for key, value in (("rules", rules), ("wishes", wishes), ("ranking", ranking)):
        if value is not None:
            cfg[key] = value
    return cfg


def count(cfg):
    return sp.solve(sp.build_model(cfg)).count


FOUR = [
    {"id": "A", "credits": 2, "category": "x", "exam": True},
    {"id": "B", "credits": 2, "category": "x", "exam": True},
    {"id": "C", "credits": 2, "category": "y"},
    {"id": "D", "credits": 2, "category": "y"},
]


def test_plain_count():
    assert count(program(FOUR)) == 6


@pytest.mark.parametrize(
    "spec,expected",
    [
        ({"max_credits": 2}, 5),
        ({"min_credits": 4}, 1),
        ({"min_courses": 1}, 5),
        ({"max_courses": 0}, 1),
        ({"min_credits": 2, "max_credits": 2}, 4),
    ],
)
def test_category_bounds(spec, expected):
    assert count(program(FOUR, categories={"x": spec, "y": {}})) == expected


def test_category_courses_on_both_sides():
    cats = {"x": {"min_courses": 1}, "y": {"min_courses": 1}}
    assert count(program(FOUR, categories=cats)) == 4


@pytest.mark.parametrize("limit,expected", [(2, 6), (1, 5), (0, 1)])
def test_exams_per_semester(limit, expected):
    assert count(program(FOUR, rules={"max_exams_per_semester": limit})) == expected


def test_semester_override_beats_global_exam_limit():
    sems = [{"id": "S1", "credits": 4, "max_exams": 2}]
    assert count(program(FOUR, semesters=sems, rules={"max_exams_per_semester": 0})) == 6


def test_at_most_one_of():
    assert count(program(FOUR, rules={"at_most_one_of": [["A", "C"]]})) == 5


ONES = [{"id": c, "credits": 1} for c in "ABCD"]
TWO_SEMS = [{"id": "S1", "credits": 2}, {"id": "S2", "credits": 2}]


def test_requires_order():
    assert count(program(ONES, TWO_SEMS)) == 6
    rules = {"requires": [{"course": "B", "after": "A"}]}
    assert count(program(ONES, TWO_SEMS, rules)) == 2
    rules = {"requires": [{"course": "B", "after": ["A"], "same_semester": True}]}
    assert count(program(ONES, TWO_SEMS, rules)) == 4


def test_requires_missing_prerequisite_blocks_course():
    courses = [{"id": "A", "credits": 2, "offered": "S2"}, {"id": "B", "credits": 2}, {"id": "C", "credits": 2}]
    sems = [{"id": "S1", "credits": 2}, {"id": "S2", "credits": 2}]
    rules = {"requires": [{"course": "B", "after": "A"}]}
    # B needs A earlier, but A only runs in S2: B can never be taken, so only S1=C, S2=A remains.
    assert count(program(courses, sems, rules)) == 1


FIVE = [{"id": c, "credits": 1} for c in "ABCDE"]


@pytest.mark.parametrize(
    "rules,expected",
    [
        ({}, 30),
        ({"fixed": ["A"]}, 24),
        ({"fixed": [{"course": "A", "semester": "S1"}]}, 12),
        ({"excluded": ["A"]}, 6),
    ],
)
def test_fixed_and_excluded(rules, expected):
    assert count(program(FIVE, TWO_SEMS, rules)) == expected


def test_must_keep_wish_acts_like_fixed():
    assert count(program(FIVE, TWO_SEMS, wishes=[{"course": "A", "keep": True}])) == 24


def test_course_with_two_categories_counts_once_and_both_ways():
    courses = [{"id": "A", "credits": 1, "category": "x"}, {"id": "E", "credits": 1, "category": ["x", "y"]}]
    sems = [{"id": "S1", "credits": 2}]
    assert count(program(courses, sems)) == 2
    assert count(program(courses, sems, categories={"x": {}, "y": {"min_courses": 1}})) == 1
    assert count(program(courses, [{"id": "S1", "credits": {"min": 1, "max": 3}}], rules={"fixed": ["E"]})) == 4


def test_scoped_and_per_semester_limits():
    courses = [
        {"id": "A", "credits": 1, "category": "x"},
        {"id": "B", "credits": 1, "category": "x"},
        {"id": "C", "credits": 1, "category": "y"},
        {"id": "D", "credits": 1, "category": "y"},
    ]
    early = {"limits": {"early": {"categories": ["x"], "semesters": ["S1"], "min_credits": 2}}}
    assert count(program(courses, TWO_SEMS, early)) == 1
    spread = {"limits": {"spread": {"categories": ["x"], "per_semester": True, "max_courses": 1}}}
    assert count(program(courses, TWO_SEMS, spread)) == 4


def test_tag_limit():
    courses = [{"id": "A", "credits": 2, "tags": ["lab"]}, {"id": "B", "credits": 2}, {"id": "C", "credits": 2}]
    rules = {"limits": {"labs": {"tags": ["lab"], "max_courses": 0}}}
    assert count(program(courses, rules=rules)) == 1


def test_decimal_credits():
    courses = [{"id": "A", "credits": 7.5}, {"id": "B", "credits": 7.5}, {"id": "C", "credits": 15}]
    cfg = program(courses, [{"id": "S1", "credits": 15}], rules={"total_credits": 15})
    model = sp.build_model(cfg)
    assert model.scale == 2
    assert sp.solve(model).count == 2


def test_total_credits_with_semester_ranges():
    sems = [{"id": "S1", "credits": {"min": 1, "max": 3}}, {"id": "S2", "credits": {"min": 1, "max": 3}}]
    courses = [{"id": c, "credits": 1} for c in "ABCD"]
    model = sp.build_model(program(courses, sems, rules={"total_credits": 4}))
    assert sp.solve(model).count == brute_force(model, 3)["count"] == 14


def test_static_infeasibility_is_explained():
    cfg = program(ONES, TWO_SEMS, rules={"total_credits": 5})
    result = sp.solve(sp.build_model(cfg))
    assert result.count == 0
    assert "add up to less" in result.reason


def test_rule_that_never_binds_is_reported():
    cfg = program(FOUR, categories={"x": {"max_credits": 10}, "y": {}})
    result = sp.solve(sp.build_model(cfg))
    assert result.count == 6
    assert result.always_true == ["category x: <= 10 credits"]


# --------------------------------------------------------------------------- ranking and wishes


THREE = [
    {"id": "A", "credits": 1},
    {"id": "B", "credits": 1},
    {"id": "C", "credits": 1, "exam": True},
]
ONE_SEM = [{"id": "S1", "credits": 2}]


def plan_ids(model, plan):
    return [[model.entries[e].course.id for e in sem] for sem in plan]


def test_ranking_by_weight():
    model = sp.build_model(program(THREE, ONE_SEM, wishes=[{"course": "A", "weight": 2}, "C"]))
    result = sp.solve(model)
    assert result.best_weight == 3
    assert result.n_best == 1
    assert [plan_ids(model, p) for p in result.plans] == [[["A", "C"]], [["A", "B"]], [["B", "C"]]]


def test_ties_broken_by_fewer_exams_then_course_ids():
    model = sp.build_model(program(THREE, ONE_SEM, wishes=["A", "B", "C"]))
    result = sp.solve(model)
    assert result.n_best == 3
    assert [plan_ids(model, p) for p in result.plans] == [[["A", "B"]], [["A", "C"]], [["B", "C"]]]
    text = sp.ranking_text(model)
    assert text.startswith("highest wish weight, then fewer exams")


def test_never_together_and_largest_sets():
    cfg = program(THREE, ONE_SEM, rules={"at_most_one_of": [["A", "C"]]}, wishes=["A", "C", "B"])
    model = sp.build_model(cfg)
    summary = sp.wish_summary(model, sp.solve(model))
    assert summary["never_together"] == [["A", "C"]]
    assert {tuple(s["courses"]) for s in summary["largest_sets"]} == {("A", "B"), ("B", "C")}


def test_unreachable_wish_is_reported():
    cfg = program(THREE, ONE_SEM, rules={"excluded": ["C"]}, wishes=["C", "A"])
    model = sp.build_model(cfg)
    rows = {r["id"]: r for r in sp.wish_summary(model, sp.solve(model))["courses"]}
    assert rows["C"]["in_some_plan"] is False
    assert rows["A"]["best_weight_with"] == 1


# --------------------------------------------------------------------------- variants and patches


def test_apply_patch_semantics():
    base = {
        "rules": {"max_exams_per_semester": 3, "excluded": ["X"], "limits": {"a": {"min_credits": 2}}},
        "wishes": ["A", {"course": "B", "weight": 2}],
        "courses": [{"id": "A", "credits": 1}],
    }
    patch = {
        "rules": {"max_exams_per_semester": 4, "excluded": {"Y": True, "X": None}, "limits": {"a": None}},
        "wishes": {"A": {"keep": True}, "B": None, "C": {"weight": 3}},
        "courses": {"A": {"credits": 2}},
    }
    out = sp.apply_patch(base, patch)
    assert out["rules"] == {"max_exams_per_semester": 4, "excluded": ["Y"], "limits": {}}
    assert out["wishes"] == [{"course": "A", "keep": True}, {"course": "C", "weight": 3}]
    assert out["courses"] == [{"id": "A", "credits": 2}]
    assert base["rules"]["max_exams_per_semester"] == 3


def test_patch_adds_to_a_list_the_file_does_not_have_yet():
    out = sp.apply_patch({"rules": {}}, {"rules": {"excluded": {"A": True}}, "wishes": {"B": {"keep": True}}})
    assert out == {"rules": {"excluded": ["A"]}, "wishes": [{"course": "B", "keep": True}]}


def test_corequisites_recipe():
    rules = {
        "requires": [
            {"course": "B", "after": "A", "same_semester": True},
            {"course": "A", "after": "B", "same_semester": True},
        ]
    }
    assert count(program(ONES, TWO_SEMS, rules)) == 2


def test_variant_price_is_reported():
    cfg = program(FOUR, rules={"max_exams_per_semester": 1}, wishes=["A", "B"])
    variants = [
        {"name": "two exams", "rules": {"max_exams_per_semester": 2}},
        {"name": "keep A", "wishes": {"A": {"keep": True}}},
        {"name": "broken", "rules": {"max_exams_per_semstr": 2}},
    ]
    doc = sp.run_document(cfg, variants=variants)
    assert doc["baseline"]["valid_plans"] == 5
    assert doc["baseline"]["best"]["weight"] == 1
    two, keep, broken = doc["variants"]
    assert two["valid_plans"] == 6
    assert two["delta"] == {"valid_plans": 1, "best_weight": 1, "now_reachable": [], "no_longer_reachable": []}
    assert keep["valid_plans"] == 2
    assert keep["delta"]["valid_plans"] == -3
    assert "did you mean 'max_exams_per_semester'" in broken["error"]


def test_cli_set_and_drop(tmp_path, capsys):
    cfg = program(FOUR, categories={"x": {"max_credits": 2}, "y": {}}, rules={"max_exams_per_semester": 1})
    path = tmp_path / "p.json"
    path.write_text(json.dumps(cfg))
    code = sp.main(
        [str(path), "--json", "--set", "rules.max_exams_per_semester=2", "--drop", "categories.x.max_credits"]
    )
    assert code == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["baseline"]["valid_plans"] == 5
    (variant,) = doc["variants"]
    assert variant["valid_plans"] == 6
    assert variant["delta"]["valid_plans"] == 1
    assert variant["changes"] == {"rules": {"max_exams_per_semester": 2}, "categories": {"x": {"max_credits": None}}}


def test_diagnosis_when_nothing_fits():
    cfg = program(FOUR, categories={"x": {"min_credits": 4}, "y": {"min_credits": 2}})
    doc = sp.run_document(cfg)
    assert doc["baseline"]["valid_plans"] == 0
    found = {d["dropped_rule"]: d["valid_plans"] for d in doc["baseline"]["diagnosis"]}
    assert found["category x: >= 4 credits"] == 5
    assert found["category y: >= 2 credits"] == 1


# --------------------------------------------------------------------------- errors and guards


def test_config_errors_name_the_problem(tmp_path, capsys):
    cfg = program(FOUR)
    cfg["courses"][0]["credit"] = 2
    with pytest.raises(sp.ConfigError, match="did you mean 'credits'"):
        sp.build_model(cfg)
    with pytest.raises(sp.ConfigError, match="unknown course 'Z'"):
        sp.build_model(program(FOUR, rules={"fixed": ["Z"]}))
    with pytest.raises(sp.ConfigError, match="neither a semester id nor a term"):
        sp.build_model(program([{"id": "A", "credits": 1, "offered": "autum"}]))
    path = tmp_path / "bad.yaml"
    path.write_text("semesters: [S1]\ncourses: []\n")
    assert sp.main([str(path)]) == 2
    assert "error in the program file" in capsys.readouterr().err


def test_subset_guard_stops_with_message(tmp_path, capsys):
    model = sp.build_model(sp.load_config(EXAMPLE))
    with pytest.raises(sp.SearchLimitError, match="semester Y1-autumn has more than 100 course combinations"):
        sp.solve(model, max_subsets=100)
    assert sp.main([str(EXAMPLE), "--max-subsets", "100"]) == 3
    assert "--max-subsets" in capsys.readouterr().err


def test_state_guard_stops_with_message():
    model = sp.build_model(sp.load_config(EXAMPLE))
    with pytest.raises(sp.SearchLimitError, match="partial plans"):
        sp.solve(model, max_states=50)


# --------------------------------------------------------------------------- the example


def test_example_baseline_is_fast_and_stable():
    cfg = sp.load_config(EXAMPLE)
    cfg.pop("variants")
    model = sp.build_model(cfg)
    started = time.perf_counter()
    result = sp.solve(model)
    elapsed = time.perf_counter() - started
    assert elapsed < 20, f"example took {elapsed:.1f} s"
    assert result.subset_counts == [2766, 1802, 2766, 1]
    assert result.count == 634_942
    assert result.best_weight == 11
    assert result.n_best == 16
    summary = sp.wish_summary(model, result)
    assert summary["never_together"] == [["ELE210", "MIN110"]]
    best = sp.plan_details(model, result.plans[0], 1)
    assert best["wished_dropped"] == ["ELE210", "ELE220", "SOC210"]
    assert all(t["ok"] for t in best["totals"])


def test_example_report_renders(capsys):
    assert sp.main([str(EXAMPLE), "--variant", "minor up to 15 ECTS", "--top", "1"]) == 0
    out = capsys.readouterr().out
    assert "Valid plans: 634,942" in out
    assert "Never together: ELE210 + MIN110" in out
    assert "minor up to 15 ECTS" in out
    assert "Plan 2" not in out
