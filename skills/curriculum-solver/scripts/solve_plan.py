#!/usr/bin/env python3
"""Exhaustive study-plan solver.

Reads one program file (YAML or JSON) with the semesters, the course pool, the rules of the
program regulations, a wish list and optional variants. Finds every valid plan exactly, ranks
the plans by the total weight of the wished courses they keep, shows which wished courses can
never be kept together, and prices each variant (one rule changed or removed) as the change in
the number of valid plans and in the best weight.

Examples:
  solve_plan.py program.yaml
  solve_plan.py program.yaml --top 5 --json --output result.json
  solve_plan.py program.yaml --set rules.max_exams_per_semester=4
  solve_plan.py program.yaml --drop categories.minor.max_credits --no-variants

Method: for each semester, a depth-first search with sum pruning lists every course subset
that meets the semester rules, and each subset's contribution to the plan-wide rules is
computed once. Semesters are then combined by dynamic programming over states made of the
courses still in play and the rule totals so far (capped where a higher value cannot matter),
which counts plans exactly and keeps the best plans per state. Nothing is sampled.

Only dependency beyond the standard library: PyYAML (for YAML input).
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import difflib
import itertools
import json
import re
import sys
import time
from bisect import insort
from dataclasses import dataclass, field, replace
from fractions import Fraction
from math import lcm
from pathlib import Path
from typing import Any, NamedTuple

try:
    import yaml
except ImportError:  # pragma: no cover - reported when a YAML file is loaded
    yaml = None

DEFAULT_MAX_SUBSETS = 200_000
DEFAULT_MAX_STATES = 1_000_000
DEFAULT_TOP = 3
MAX_SCALE = 1000

TIE_BREAKS = {
    "fewer_exams": "fewer exams",
    "even_load": "more even credit load",
    "fewer_courses": "fewer courses",
    "fewer_credits": "fewer credits",
}
DEFAULT_TIE_BREAK = ("fewer_exams", "even_load")

TOP_KEYS = {"program", "semesters", "categories", "courses", "rules", "wishes", "ranking", "variants"}
PROGRAM_KEYS = {"name", "credit_unit", "source", "notes"}
SEMESTER_KEYS = {"id", "term", "label", "credits", "max_exams", "min_courses", "max_courses"}
CATEGORY_KEYS = {"name", "min_credits", "max_credits", "min_courses", "max_courses", "quote"}
COURSE_KEYS = {"id", "title", "credits", "category", "offered", "exam", "tags", "notes"}
RULE_KEYS = {
    "total_credits",
    "semester_credits",
    "max_exams_per_semester",
    "limits",
    "fixed",
    "excluded",
    "at_most_one_of",
    "requires",
}
LIMIT_KEYS = {
    "name",
    "categories",
    "tags",
    "courses",
    "min_credits",
    "max_credits",
    "min_courses",
    "max_courses",
    "per_semester",
    "semesters",
    "quote",
}
FIXED_KEYS = {"course", "semester"}
REQUIRES_KEYS = {"course", "after", "same_semester"}
WISH_KEYS = {"course", "weight", "keep"}
RANKING_KEYS = {"tie_break", "top"}
VARIANT_META_KEYS = {"name", "description"}
LIST_ID_KEYS = {"semesters": "id", "courses": "id", "wishes": "course", "fixed": "course", "limits": "name"}
LIST_KEYS = {"semesters", "courses", "wishes", "fixed", "excluded", "at_most_one_of", "requires"}


class ConfigError(ValueError):
    """The program file is malformed or inconsistent."""


class SearchLimitError(RuntimeError):
    """The search space is larger than the configured limit."""


# --------------------------------------------------------------------------- loading and patching


def load_config(path: str | Path) -> dict[str, Any]:
    """Read a program file. JSON when the suffix is .json, YAML otherwise."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        if yaml is None:
            raise ConfigError("PyYAML is needed for YAML files: pip install pyyaml")
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a mapping at the top level")
    return data


def _item_id(item: Any, id_key: str) -> Any:
    if isinstance(item, dict):
        return item.get(id_key)
    return item


def apply_patch(base: Any, patch: Any, parent: str = "") -> Any:
    """Deep-merge `patch` into a copy of `base`.

    Mappings merge key by key and a null value deletes the key. A mapping applied to a list
    edits the list by item id (`id` for semesters and courses, `course` for wishes and fixed,
    `name` for limits; plain strings for lists of ids): a null value removes the item, a mapping
    updates or adds it, `true` adds a plain id. Anything else replaces the old value.
    """
    if isinstance(patch, dict) and isinstance(base, dict):
        out = copy.deepcopy(base)
        for key, value in patch.items():
            if value is None:
                out.pop(key, None)
            elif key in out:
                out[key] = apply_patch(out[key], value, str(key))
            elif key in LIST_KEYS and isinstance(value, dict):
                out[key] = apply_patch([], value, str(key))
            else:
                out[key] = copy.deepcopy(value)
        return out
    if isinstance(patch, dict) and isinstance(base, list):
        id_key = LIST_ID_KEYS.get(parent, "id")
        out = copy.deepcopy(base)
        for key, value in patch.items():
            pos = next((i for i, item in enumerate(out) if str(_item_id(item, id_key)) == str(key)), None)
            if value is None or value is False:
                if pos is not None:
                    out.pop(pos)
                continue
            if value is True:
                if pos is None:
                    out.append(key)
                continue
            if not isinstance(value, dict):
                raise ConfigError(f"patch for {parent}.{key}: expected a mapping, true or null")
            if pos is None:
                out.append({id_key: key, **copy.deepcopy(value)})
            else:
                item = out[pos] if isinstance(out[pos], dict) else {id_key: out[pos]}
                out[pos] = apply_patch(item, value, parent)
        return out
    return copy.deepcopy(patch)


def parse_set(arg: str) -> tuple[str, Any]:
    if "=" not in arg:
        raise ConfigError(f"--set expects PATH=VALUE, got '{arg}'")
    path, raw = arg.split("=", 1)
    value = yaml.safe_load(raw) if yaml is not None else json.loads(raw)
    return path.strip(), value


# --------------------------------------------------------------------------- model


@dataclass
class Semester:
    index: int
    id: str
    term: str | None
    label: str
    lo: int
    hi: int | None
    max_exams: int | None
    min_courses: int
    max_courses: int | None


@dataclass
class Course:
    bit: int
    id: str
    title: str
    credits: int
    exam: bool
    tags: frozenset[str]
    categories: tuple[str, ...]
    offered: frozenset[int]
    pinned: int | None
    excluded: bool


@dataclass
class Entry:
    """One way of taking a course: the course counted in one category."""

    index: int
    course: Course
    category: str


@dataclass
class Limit:
    key: str
    label: str
    origin: str
    members: frozenset[int]
    scope: frozenset[int] | None
    per_semester: bool
    credits: tuple[int, int | None] | None
    count: tuple[int, int | None] | None
    quote: str | None = None


@dataclass
class Requirement:
    course: int
    after: int
    same_semester: bool


@dataclass
class Model:
    name: str
    unit: str
    source: str | None
    scale: int
    weight_scale: int
    semesters: list[Semester]
    courses: list[Course]
    entries: list[Entry]
    categories: dict[str, str]
    limits: list[Limit]
    requirements: list[Requirement]
    weights: dict[int, int]
    keep: frozenset[int]
    fixed_free: frozenset[int]
    total: tuple[int, int | None]
    tie_break: tuple[str, ...]
    top: int
    notes: list[str]
    infeasible: str | None


def natural_key(text: str) -> tuple[Any, ...]:
    parts = re.split(r"(\d+)", text)
    return (tuple(int(p) if i % 2 else p.casefold() for i, p in enumerate(parts)), text)


def _check_keys(obj: Any, allowed: set[str], where: str) -> dict[str, Any]:
    if not isinstance(obj, dict):
        raise ConfigError(f"{where}: expected a mapping, got {type(obj).__name__}")
    for key in obj:
        if key not in allowed:
            hint = difflib.get_close_matches(str(key), sorted(allowed), n=1)
            extra = f" (did you mean '{hint[0]}'?)" if hint else ""
            raise ConfigError(f"{where}: unknown key '{key}'{extra}")
    return obj


def _as_list(value: Any, where: str) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (str, int)):
        return [value]
    raise ConfigError(f"{where}: expected a list")


def _fraction(value: Any, where: str, *, positive: bool = False) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConfigError(f"{where}: expected a number, got {value!r}")
    try:
        number = Fraction(str(value).strip())
    except (ValueError, ZeroDivisionError):
        raise ConfigError(f"{where}: expected a number, got {value!r}") from None
    if number < 0 or (positive and number == 0):
        raise ConfigError(f"{where}: expected a {'positive' if positive else 'non-negative'} number")
    return number


def _count(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ConfigError(f"{where}: expected a whole number >= 0, got {value!r}")
    return value


def _scale_for(numbers: list[Fraction], what: str) -> int:
    scale = 1
    for number in numbers:
        scale = lcm(scale, number.denominator)
    if scale > MAX_SCALE:
        raise ConfigError(f"{what} need more than three decimals; round them")
    return scale


def _credit_numbers(cfg: dict[str, Any]) -> list[Fraction]:
    """Every credit number in the file, to find a common integer scale."""
    found: list[Fraction] = []

    def grab(value: Any) -> None:
        if isinstance(value, dict):
            for key in ("min", "max"):
                grab(value.get(key))
            return
        if isinstance(value, (int, float, str)) and not isinstance(value, bool):
            with contextlib.suppress(ValueError, ZeroDivisionError):
                found.append(Fraction(str(value).strip()))

    for course in cfg.get("courses") or []:
        if isinstance(course, dict):
            grab(course.get("credits"))
    for sem in cfg.get("semesters") or []:
        if isinstance(sem, dict):
            grab(sem.get("credits"))
    rules = cfg.get("rules") if isinstance(cfg.get("rules"), dict) else {}
    grab(rules.get("semester_credits"))
    grab(rules.get("total_credits"))
    cats = cfg.get("categories") if isinstance(cfg.get("categories"), dict) else {}
    limits = rules.get("limits") or {}
    limit_specs = limits.values() if isinstance(limits, dict) else limits
    for spec in [*cats.values(), *limit_specs]:
        if isinstance(spec, dict):
            grab(spec.get("min_credits"))
            grab(spec.get("max_credits"))
    return found


def _bounds(spec: dict[str, Any], kind: str, where: str, unit: Any) -> tuple[int, int | None] | None:
    lo_raw, hi_raw = spec.get(f"min_{kind}"), spec.get(f"max_{kind}")
    if lo_raw is None and hi_raw is None:
        return None
    lo = unit(lo_raw, f"{where}.min_{kind}") if lo_raw is not None else 0
    hi = unit(hi_raw, f"{where}.max_{kind}") if hi_raw is not None else None
    if hi is not None and lo > hi:
        raise ConfigError(f"{where}: min_{kind} is larger than max_{kind}")
    if lo == 0 and hi is None:
        return None
    return lo, hi


def build_model(cfg: dict[str, Any]) -> Model:
    """Validate a program file and turn it into integer-scaled data for the solver."""
    _check_keys(cfg, TOP_KEYS, "program file")
    prog = _check_keys(cfg.get("program") or {}, PROGRAM_KEYS, "program")
    rules = _check_keys(cfg.get("rules") or {}, RULE_KEYS, "rules")
    notes: list[str] = []

    scale = _scale_for(_credit_numbers(cfg), "credit values")

    def units(value: Any, where: str, *, positive: bool = False) -> int:
        return int(_fraction(value, where, positive=positive) * scale)

    def credit_range(value: Any, where: str) -> tuple[int, int | None]:
        if isinstance(value, dict):
            _check_keys(value, {"min", "max"}, where)
            lo = units(value["min"], f"{where}.min") if value.get("min") is not None else 0
            hi = units(value["max"], f"{where}.max") if value.get("max") is not None else None
        else:
            lo = hi = units(value, where)
        if hi is not None and lo > hi:
            raise ConfigError(f"{where}: min is larger than max")
        return lo, hi

    # semesters
    sem_cfg = cfg.get("semesters")
    if not isinstance(sem_cfg, list) or not sem_cfg:
        raise ConfigError("semesters: give a non-empty list of semesters in chronological order")
    default_credits = rules.get("semester_credits")
    default_exams = rules.get("max_exams_per_semester")
    semesters: list[Semester] = []
    for i, raw in enumerate(sem_cfg):
        spec = {"id": raw} if isinstance(raw, (str, int)) else raw
        where = f"semesters[{i}]"
        _check_keys(spec, SEMESTER_KEYS, where)
        sid = str(spec.get("id") or "").strip()
        if not sid:
            raise ConfigError(f"{where}: missing id")
        if any(s.id == sid for s in semesters):
            raise ConfigError(f"{where}: duplicate semester id '{sid}'")
        credits_spec = spec.get("credits", default_credits)
        if credits_spec is None:
            raise ConfigError(f"semester {sid}: no credit target; set rules.semester_credits or semesters[].credits")
        lo, hi = credit_range(credits_spec, f"semester {sid}.credits")
        max_exams = spec.get("max_exams", default_exams)
        max_courses = spec.get("max_courses")
        semesters.append(
            Semester(
                index=i,
                id=sid,
                term=str(spec["term"]) if spec.get("term") is not None else None,
                label=str(spec.get("label") or sid),
                lo=lo,
                hi=hi,
                max_exams=_count(max_exams, f"semester {sid}.max_exams") if max_exams is not None else None,
                min_courses=_count(spec.get("min_courses", 0), f"semester {sid}.min_courses"),
                max_courses=_count(max_courses, f"semester {sid}.max_courses") if max_courses is not None else None,
            )
        )
    sem_by_id = {s.id: s.index for s in semesters}
    terms: dict[str, list[int]] = {}
    for s in semesters:
        if s.term:
            terms.setdefault(s.term, []).append(s.index)

    def semester_index(value: Any, where: str) -> int:
        key = str(value)
        if key not in sem_by_id:
            hint = difflib.get_close_matches(key, list(sem_by_id), n=1)
            raise ConfigError(f"{where}: unknown semester '{key}'" + (f" (did you mean '{hint[0]}'?)" if hint else ""))
        return sem_by_id[key]

    # categories
    cat_cfg = cfg.get("categories")
    declared = cat_cfg is not None
    if isinstance(cat_cfg, list):
        cat_cfg = {str(c.get("id") if isinstance(c, dict) else c): c for c in cat_cfg}
    cat_cfg = cat_cfg or {}
    if not isinstance(cat_cfg, dict):
        raise ConfigError("categories: expected a mapping from category id to its rules")
    categories: dict[str, str] = {}
    cat_specs: dict[str, dict[str, Any]] = {}
    for cid, spec in cat_cfg.items():
        spec = {"name": spec} if isinstance(spec, str) else dict(spec or {})
        spec.pop("id", None)
        _check_keys(spec, CATEGORY_KEYS, f"categories.{cid}")
        categories[str(cid)] = str(spec.get("name") or cid)
        cat_specs[str(cid)] = spec

    # courses
    course_cfg = cfg.get("courses")
    if not isinstance(course_cfg, list) or not course_cfg:
        raise ConfigError("courses: give a non-empty list of courses")
    raw_courses: list[dict[str, Any]] = []
    for i, spec in enumerate(course_cfg):
        where = f"courses[{i}]"
        _check_keys(spec, COURSE_KEYS, where)
        cid = str(spec.get("id") or "").strip()
        if not cid:
            raise ConfigError(f"{where}: missing id")
        where = f"course {cid}"
        if any(c["id"] == cid for c in raw_courses):
            raise ConfigError(f"{where}: duplicate course id")
        if "credits" not in spec:
            raise ConfigError(f"{where}: missing credits")
        cats = [str(c) for c in _as_list(spec.get("category"), f"{where}.category")]
        if not cats:
            raise ConfigError(f"{where}: missing category")
        for cat in cats:
            if cat not in categories:
                if declared:
                    hint = difflib.get_close_matches(cat, list(categories), n=1)
                    extra = f" (did you mean '{hint[0]}'?)" if hint else ""
                    raise ConfigError(f"{where}: unknown category '{cat}'{extra}")
                categories[cat] = cat
        offered_raw = spec.get("offered")
        if offered_raw is None or offered_raw in ("any", "all"):
            offered = set(range(len(semesters)))
        else:
            offered = set()
            for value in _as_list(offered_raw, f"{where}.offered"):
                key = str(value)
                if key in sem_by_id:
                    offered.add(sem_by_id[key])
                elif key in terms:
                    offered.update(terms[key])
                else:
                    options = list(sem_by_id) + list(terms)
                    hint = difflib.get_close_matches(key, options, n=1)
                    extra = f" (did you mean '{hint[0]}'?)" if hint else ""
                    raise ConfigError(f"{where}.offered: '{key}' is neither a semester id nor a term{extra}")
        exam = spec.get("exam", True)
        if not isinstance(exam, bool):
            raise ConfigError(f"{where}.exam: expected true or false")
        raw_courses.append(
            {
                "id": cid,
                "title": str(spec.get("title") or cid),
                "credits": units(spec["credits"], f"{where}.credits", positive=True),
                "exam": exam,
                "tags": frozenset(str(t) for t in _as_list(spec.get("tags"), f"{where}.tags")),
                "categories": tuple(dict.fromkeys(cats)),
                "offered": offered,
            }
        )
    raw_courses.sort(key=lambda c: natural_key(c["id"]))
    bit_of = {c["id"]: i for i, c in enumerate(raw_courses)}

    def course_bit(value: Any, where: str) -> int:
        key = str(value)
        if key not in bit_of:
            hint = difflib.get_close_matches(key, list(bit_of), n=1)
            raise ConfigError(f"{where}: unknown course '{key}'" + (f" (did you mean '{hint[0]}'?)" if hint else ""))
        return bit_of[key]

    # fixed and excluded
    pinned: dict[int, int] = {}
    fixed_free: set[int] = set()
    for i, item in enumerate(_as_list(rules.get("fixed"), "rules.fixed")):
        spec = {"course": item} if isinstance(item, (str, int)) else _check_keys(item, FIXED_KEYS, f"rules.fixed[{i}]")
        bit = course_bit(spec.get("course"), f"rules.fixed[{i}]")
        if spec.get("semester") is not None:
            pinned[bit] = semester_index(spec["semester"], f"rules.fixed[{i}].semester")
        else:
            fixed_free.add(bit)
    excluded = {course_bit(c, "rules.excluded") for c in _as_list(rules.get("excluded"), "rules.excluded")}
    clash = excluded & (set(pinned) | fixed_free)
    if clash:
        names = ", ".join(raw_courses[b]["id"] for b in sorted(clash))
        raise ConfigError(f"rules: {names} is both fixed and excluded")

    courses: list[Course] = []
    for bit, raw in enumerate(raw_courses):
        offered = raw["offered"]
        if bit in pinned:
            offered = {pinned[bit]}
        if bit in excluded:
            offered = set()
        elif not offered:
            notes.append(f"{raw['id']} is not offered in any planned semester")
        courses.append(
            Course(
                bit=bit,
                id=raw["id"],
                title=raw["title"],
                credits=raw["credits"],
                exam=raw["exam"],
                tags=raw["tags"],
                categories=raw["categories"],
                offered=frozenset(offered),
                pinned=pinned.get(bit),
                excluded=bit in excluded,
            )
        )
    entries: list[Entry] = []
    for course in courses:
        for cat in sorted(course.categories, key=natural_key):
            entries.append(Entry(index=len(entries), course=course, category=cat))

    # wishes
    weights_raw: dict[int, Fraction] = {}
    keep: set[int] = set()
    for i, item in enumerate(_as_list(cfg.get("wishes"), "wishes")):
        spec = {"course": item} if isinstance(item, (str, int)) else _check_keys(item, WISH_KEYS, f"wishes[{i}]")
        bit = course_bit(spec.get("course"), f"wishes[{i}]")
        if bit in weights_raw:
            raise ConfigError(f"wishes: {courses[bit].id} is listed twice")
        weights_raw[bit] = _fraction(spec.get("weight", 1), f"wishes[{i}].weight", positive=True)
        if spec.get("keep"):
            keep.add(bit)
            if courses[bit].excluded:
                raise ConfigError(f"wishes: {courses[bit].id} is marked keep but also excluded")
        if courses[bit].excluded:
            notes.append(f"wished course {courses[bit].id} is excluded by the rules")
    weight_scale = _scale_for(list(weights_raw.values()), "wish weights")
    weights = {bit: int(w * weight_scale) for bit, w in weights_raw.items()}

    # limits
    limits: list[Limit] = []
    for cid, spec in cat_specs.items():
        where = f"categories.{cid}"
        credit_bounds = _bounds(spec, "credits", where, units)
        count_bounds = _bounds(spec, "courses", where, _count)
        if credit_bounds or count_bounds:
            members = frozenset(e.index for e in entries if e.category == cid)
            minimum = (credit_bounds[0] if credit_bounds else 0) + (count_bounds[0] if count_bounds else 0)
            if not members and minimum > 0:
                notes.append(f"category {cid} has a minimum but no courses")
            limits.append(
                Limit(
                    cid,
                    categories[cid],
                    "category",
                    members,
                    None,
                    False,
                    credit_bounds,
                    count_bounds,
                    spec.get("quote"),
                )
            )
    limit_cfg = rules.get("limits") or {}
    if isinstance(limit_cfg, list):
        named = {}
        for i, spec in enumerate(limit_cfg):
            if not isinstance(spec, dict) or not spec.get("name"):
                raise ConfigError(f"rules.limits[{i}]: each limit needs a name")
            named[str(spec["name"])] = spec
        limit_cfg = named
    if not isinstance(limit_cfg, dict):
        raise ConfigError("rules.limits: expected a mapping from limit name to its rule")
    for name, spec in limit_cfg.items():
        where = f"rules.limits.{name}"
        _check_keys(spec, LIMIT_KEYS, where)
        cats = {str(c) for c in _as_list(spec.get("categories"), f"{where}.categories")}
        for cat in cats:
            if cat not in categories:
                raise ConfigError(f"{where}: unknown category '{cat}'")
        tags = {str(t) for t in _as_list(spec.get("tags"), f"{where}.tags")}
        bits = {course_bit(c, f"{where}.courses") for c in _as_list(spec.get("courses"), f"{where}.courses")}
        if not (cats or tags or bits):
            raise ConfigError(f"{where}: say which courses it covers (categories, tags or courses)")
        members = frozenset(
            e.index for e in entries if e.category in cats or e.course.tags & tags or e.course.bit in bits
        )
        scope = None
        if spec.get("semesters") is not None:
            scope = frozenset(semester_index(s, f"{where}.semesters") for s in _as_list(spec["semesters"], where))
        credit_bounds = _bounds(spec, "credits", where, units)
        count_bounds = _bounds(spec, "courses", where, _count)
        if not (credit_bounds or count_bounds):
            raise ConfigError(f"{where}: give at least one of min/max_credits, min/max_courses")
        per_sem = spec.get("per_semester", False)
        if not isinstance(per_sem, bool):
            raise ConfigError(f"{where}.per_semester: expected true or false")
        limits.append(
            Limit(
                str(name), str(name), "limit", members, scope, per_sem, credit_bounds, count_bounds, spec.get("quote")
            )
        )
    for i, group in enumerate(_as_list(rules.get("at_most_one_of"), "rules.at_most_one_of")):
        bits = [course_bit(c, f"rules.at_most_one_of[{i}]") for c in _as_list(group, f"rules.at_most_one_of[{i}]")]
        if len(set(bits)) < 2:
            raise ConfigError(f"rules.at_most_one_of[{i}]: list at least two courses")
        members = frozenset(e.index for e in entries if e.course.bit in bits)
        label = "at most one of " + ", ".join(courses[b].id for b in sorted(set(bits)))
        limits.append(Limit(f"at_most_one_of[{i}]", label, "at_most_one_of", members, None, False, None, (0, 1)))

    requirements: list[Requirement] = []
    for i, spec in enumerate(_as_list(rules.get("requires"), "rules.requires")):
        where = f"rules.requires[{i}]"
        _check_keys(spec, REQUIRES_KEYS, where)
        target = course_bit(spec.get("course"), where)
        befores = _as_list(spec.get("after"), f"{where}.after")
        if not befores:
            raise ConfigError(f"{where}: 'after' lists the courses that must come first")
        same = spec.get("same_semester", False)
        if not isinstance(same, bool):
            raise ConfigError(f"{where}.same_semester: expected true or false")
        for before in befores:
            bit = course_bit(before, f"{where}.after")
            if bit == target:
                raise ConfigError(f"{where}: a course cannot require itself")
            requirements.append(Requirement(course=target, after=bit, same_semester=same))

    # must-take courses that are not pinned to a semester
    must = (fixed_free | keep) - set(pinned)
    if must:
        members = frozenset(e.index for e in entries if e.course.bit in must)
        limits.append(
            Limit("must_take", "fixed and must-keep courses", "fixed", members, None, False, None, (len(must), None))
        )

    # total credits
    infeasible = None
    if rules.get("total_credits") is None:
        total: tuple[int, int | None] = (0, None)
    else:
        total = credit_range(rules["total_credits"], "rules.total_credits")
    lo_sum = sum(s.lo for s in semesters)
    hi_sum = None if any(s.hi is None for s in semesters) else sum(s.hi or 0 for s in semesters)
    if total[1] is not None and lo_sum > total[1]:
        infeasible = "the semester credit targets add up to more than the total allows"
    elif hi_sum is not None and hi_sum < total[0]:
        infeasible = "the semester credit targets add up to less than the total requires"
    elif total[0] > lo_sum or (total[1] is not None and (hi_sum is None or hi_sum > total[1])):
        all_entries = frozenset(e.index for e in entries)
        limits.append(Limit("total_credits", "total credits", "total", all_entries, None, False, total, None))

    for limit in limits:
        if limit.per_semester and limit.origin != "limit":
            raise ConfigError(f"{limit.key}: only rules.limits can be per_semester")

    ranking = _check_keys(cfg.get("ranking") or {}, RANKING_KEYS, "ranking")
    tie_break = tuple(str(t) for t in _as_list(ranking.get("tie_break", list(DEFAULT_TIE_BREAK)), "ranking.tie_break"))
    for item in tie_break:
        if item not in TIE_BREAKS:
            raise ConfigError(f"ranking.tie_break: unknown criterion '{item}'; use {', '.join(TIE_BREAKS)}")
    top = _count(ranking.get("top", DEFAULT_TOP), "ranking.top") or DEFAULT_TOP

    return Model(
        name=str(prog.get("name") or "Study program"),
        unit=str(prog.get("credit_unit") or "credits"),
        source=str(prog["source"]) if prog.get("source") else None,
        scale=scale,
        weight_scale=weight_scale,
        semesters=semesters,
        courses=courses,
        entries=entries,
        categories=categories,
        limits=limits,
        requirements=requirements,
        weights=weights,
        keep=frozenset(keep),
        fixed_free=frozenset(fixed_free - set(pinned)),
        total=total,
        tie_break=tie_break,
        top=top,
        notes=notes,
        infeasible=infeasible,
    )


# --------------------------------------------------------------------------- enumeration


@dataclass(frozen=True)
class Dim:
    """One plan-wide quantity the solver tracks: credits or course count over a limit's members."""

    limit: Limit
    kind: str
    lo: int
    hi: int | None
    cap: int
    hard: bool


class Row(NamedTuple):
    mask: int
    entries: tuple[int, ...]
    credits: int
    exams: int
    contrib: tuple[int, ...]
    weight: int
    wmask: int
    ties: tuple[int, ...]


def make_dims(limits: list[Limit]) -> list[Dim]:
    dims = []
    for limit in limits:
        if limit.per_semester:
            continue
        for kind, bounds in (("credits", limit.credits), ("count", limit.count)):
            if bounds is None:
                continue
            lo, hi = bounds
            if hi is None:
                dims.append(Dim(limit, kind, lo, None, lo, False))
            else:
                dims.append(Dim(limit, kind, lo, hi, hi, True))
    return dims


def _amount(entry: Entry, members: frozenset[int], kind: str) -> int:
    if entry.index not in members:
        return 0
    return entry.course.credits if kind == "credits" else 1


def enumerate_semester(model: Model, dims: list[Dim], j: int, max_subsets: int) -> list[Row]:
    """Every course subset of semester j that meets the semester's own rules."""
    sem = model.semesters[j]
    candidates = [e for e in model.entries if j in e.course.offered]
    forced = 0
    for course in model.courses:
        if course.pinned == j:
            forced |= 1 << course.bit
    by_bit: dict[int, list[Entry]] = {}
    for entry in candidates:
        by_bit.setdefault(entry.course.bit, []).append(entry)
    pre: list[Entry] = []
    rest: list[Entry] = []
    for bit, group in by_bit.items():
        if (forced >> bit) & 1 and len(group) == 1:
            pre.extend(group)
        else:
            rest.extend(group)
    rest.sort(key=lambda e: (-e.course.credits, e.index))

    checks: list[tuple[frozenset[int], str, int, int | None]] = []
    for limit in model.limits:
        if limit.per_semester and (limit.scope is None or j in limit.scope):
            for kind, bounds in (("credits", limit.credits), ("count", limit.count)):
                if bounds is not None:
                    checks.append((limit.members, kind, bounds[0], bounds[1]))
    for dim in dims:
        if dim.hard and (dim.limit.scope is None or j in dim.limit.scope):
            checks.append((dim.limit.members, dim.kind, 0, dim.hi))
    los = [c[2] for c in checks]
    his = [c[3] for c in checks]
    deltas = [[(ci, a) for ci, c in enumerate(checks) if (a := _amount(e, c[0], c[1]))] for e in rest]

    lo = sem.lo
    hi = sem.hi if sem.hi is not None else sum(e.course.credits for e in candidates)
    max_ex = sem.max_exams
    max_n = sem.max_courses
    min_n = sem.min_courses
    credits = [e.course.credits for e in rest]
    bits = [1 << e.course.bit for e in rest]
    exams = [1 if e.course.exam else 0 for e in rest]
    prefix = [0]
    for c in credits:
        prefix.append(prefix[-1] + c)

    start_vals = [0] * len(checks)
    for e in pre:
        for ci, c in enumerate(checks):
            start_vals[ci] += _amount(e, c[0], c[1])
    cr0 = sum(e.course.credits for e in pre)
    ex0 = sum(1 for e in pre if e.course.exam)
    mask0 = 0
    for e in pre:
        mask0 |= 1 << e.course.bit
    if (
        cr0 > hi
        or (max_ex is not None and ex0 > max_ex)
        or (max_n is not None and len(pre) > max_n)
        or any(h is not None and v > h for v, h in zip(start_vals, his, strict=True))
    ):
        return []

    found: list[tuple[Entry, ...]] = []
    chosen: list[Entry] = []
    n_rest = len(rest)

    def rec(i: int, cr: int, ex: int, nc: int, mask: int, vals: tuple[int, ...]) -> None:
        if (
            cr >= lo
            and nc >= min_n
            and mask & forced == forced
            and all(v >= low for v, low in zip(vals, los, strict=True))
        ):
            found.append(tuple(chosen))
            if len(found) > max_subsets:
                raise SearchLimitError(
                    f"semester {sem.id} has more than {max_subsets:,} course combinations that meet its own rules. "
                    "Narrow the course pool (exclude courses you would never take), fix courses already decided, "
                    "tighten the semester credit range, or raise --max-subsets."
                )
        if cr >= hi or (max_n is not None and nc >= max_n):
            return
        if cr < lo:
            room = n_rest - i if max_n is None else min(n_rest - i, max_n - nc)
            if cr + prefix[i + room] - prefix[i] < lo:
                return
        for t in range(i, n_rest):
            if cr + credits[t] > hi or mask & bits[t]:
                continue
            if exams[t] and max_ex is not None and ex >= max_ex:
                continue
            new_vals = vals
            if deltas[t]:
                tmp = list(vals)
                ok = True
                for ci, amount in deltas[t]:
                    tmp[ci] += amount
                    if his[ci] is not None and tmp[ci] > his[ci]:
                        ok = False
                        break
                if not ok:
                    continue
                new_vals = tuple(tmp)
            chosen.append(rest[t])
            rec(t + 1, cr + credits[t], ex + exams[t], nc + 1, mask | bits[t], new_vals)
            chosen.pop()

    rec(0, cr0, ex0, len(pre), mask0, tuple(start_vals))

    in_scope = [d.limit.scope is None or j in d.limit.scope for d in dims]
    vectors = {
        e.index: tuple(
            _amount(e, d.limit.members, d.kind) if scoped else 0 for d, scoped in zip(dims, in_scope, strict=True)
        )
        for e in candidates
    }
    caps = [d.cap for d in dims]
    hard = [d.hard for d in dims]
    zero = [0] * len(dims)
    mid2 = sem.lo + (sem.hi if sem.hi is not None else sem.lo)
    rows = []
    for combo in found:
        ents = sorted([*pre, *combo], key=lambda e: e.index)
        mask = 0
        weight = 0
        wmask = 0
        for e in ents:
            bit = e.course.bit
            mask |= 1 << bit
            w = model.weights.get(bit, 0)
            if w:
                weight += w
                wmask |= 1 << bit
        sums = [sum(col) for col in zip(*(vectors[e.index] for e in ents), strict=True)] if ents else zero
        if any(h and v > c for v, c, h in zip(sums, caps, hard, strict=True)):
            continue
        contrib = [min(v, c) for v, c in zip(sums, caps, strict=True)]
        cr = sum(e.course.credits for e in ents)
        ex = sum(1 for e in ents if e.course.exam)
        tie_values = {
            "fewer_exams": ex,
            "even_load": abs(2 * cr - mid2),
            "fewer_courses": len(ents),
            "fewer_credits": cr,
        }
        rows.append(
            Row(
                mask=mask,
                entries=tuple(e.index for e in ents),
                credits=cr,
                exams=ex,
                contrib=tuple(contrib),
                weight=weight,
                wmask=wmask,
                ties=tuple(tie_values[t] for t in model.tie_break),
            )
        )
    return rows


# --------------------------------------------------------------------------- combining semesters


@dataclass
class Result:
    count: int
    best_weight: int
    n_best: int
    plans: list[tuple[tuple[int, ...], ...]]
    maximal: list[int]
    subset_counts: list[int]
    order: list[int]
    peak_states: int
    seconds: float
    reason: str | None = None
    always_true: list[str] = field(default_factory=list)


def _push_top(top: list[tuple[int, Any]], item: tuple[int, Any], k: int) -> None:
    if len(top) >= k and item >= top[-1]:
        return
    insort(top, item)
    if len(top) > k:
        top.pop()


def _relevant_bits(sem_masks: list[int], processed: int, full: int) -> int:
    """Courses offered both in a processed and in an unprocessed semester."""
    bits = 0
    for bit, om in enumerate(sem_masks):
        if om & processed and om & full & ~processed:
            bits |= 1 << bit
    return bits


def choose_order(model: Model, tables: list[list[Row]]) -> list[int]:
    """Pick the semester processing order that keeps the courses in play small.

    The cost model counts distinct projections of each semester's subsets onto the courses
    that are still in play; it only steers speed, never the result.
    """
    n = len(model.semesters)
    full = (1 << n) - 1
    sem_masks = [sum(1 << s for s in c.offered) for c in model.courses]
    union = []
    for rows in tables:
        u = 0
        for row in rows:
            u |= row.mask
        union.append(u)
    rel_cache: dict[int, int] = {}
    proj_cache: dict[tuple[int, int], int] = {}

    def rel(p: int) -> int:
        if p not in rel_cache:
            rel_cache[p] = _relevant_bits(sem_masks, p, full)
        return rel_cache[p]

    def distinct(s: int, bits: int) -> int:
        key = (s, bits & union[s])
        if key not in proj_cache:
            proj_cache[key] = len({row.mask & key[1] for row in tables[s]})
        return proj_cache[key]

    def step_cost(processed: int, states: int, j: int) -> tuple[int, int]:
        after = processed | (1 << j)
        cost = states * distinct(j, rel(processed) | rel(after))
        new_states = 1
        for s in range(n):
            if after >> s & 1:
                new_states *= distinct(s, rel(after))
        return cost, new_states

    if n <= 6:
        best: tuple[int, tuple[int, ...]] | None = None
        for perm in itertools.permutations(range(n)):
            processed, states, total = 0, 1, 0
            for j in perm:
                cost, states = step_cost(processed, states, j)
                total += cost
                processed |= 1 << j
            if best is None or (total, perm) < best:
                best = (total, perm)
        assert best is not None
        return list(best[1])
    order: list[int] = []
    processed, states = 0, 1
    while len(order) < n:
        options = []
        for j in range(n):
            if not processed >> j & 1:
                cost, new_states = step_cost(processed, states, j)
                options.append((cost, new_states, j))
        cost, states, j = min(options)
        order.append(j)
        processed |= 1 << j
    return order


class _Packer:
    """Rule totals packed into one integer, one bit field per tracked rule.

    A field is wide enough for twice its cap plus a guard bit, so adding two packed totals
    never carries into the next field, and capping every field takes a few integer operations.
    """

    def __init__(self, caps: list[int], hard: list[bool]) -> None:
        width = max([(2 * c).bit_length() for c in caps] + [1]) + 1
        self.shift = width - 1
        self.offsets = [i * width for i in range(len(caps))]
        self.field = (1 << self.shift) - 1
        self.caps = self.pack(caps)
        soft = [i for i, h in enumerate(hard) if not h]
        self.soft_guard = sum(1 << (self.offsets[i] + self.shift) for i in soft)
        self.soft_bias = sum((self.field - caps[i]) << self.offsets[i] for i in soft)

    def pack(self, values: tuple[int, ...] | list[int]) -> int:
        out = 0
        for value, offset in zip(values, self.offsets, strict=True):
            out |= value << offset
        return out

    def get(self, packed: int, i: int) -> int:
        return (packed >> self.offsets[i]) & self.field


_NO_LIMIT = float("inf")


def _maximal(masks: set[int] | list[int]) -> list[int]:
    """The masks that are not contained in another mask of the collection."""
    out: list[int] = []
    for mask in sorted(set(masks), key=lambda m: (-m.bit_count(), m)):
        if not any(kept | mask == kept for kept in out):
            out.append(mask)
    return out


def _place(
    pl: tuple[tuple[int, int], ...],
    pattern: int,
    j: int,
    now_list: list[int],
    checks: list[tuple[int, int, bool, list[bool]]],
    tracked_after: int,
) -> tuple[tuple[int, int], ...] | None:
    """Update the semester positions of courses in ordering rules; None if a rule breaks."""
    place = dict(pl)
    for bit in now_list:
        if pattern >> bit & 1:
            place[bit] = j
    for before, course, same, pending in checks:
        jb = place.get(course)
        if jb is None:
            continue
        ja = place.get(before)
        if ja is None:
            if not pending[jb]:
                return None
        elif ja > jb or (ja == jb and not same):
            return None
    return tuple(sorted((b, s) for b, s in place.items() if tracked_after >> b & 1))


def _combine(
    model: Model,
    dims: list[Dim],
    tables: list[list[Row]],
    scores: list[list[int]],
    order: list[int],
    k: int,
    max_states: int,
) -> tuple[dict[Any, list[Any]], int]:
    """Dynamic programming over semesters in `order`.

    A state is (courses taken so far that a later semester could repeat, packed rule totals,
    semester positions of courses in open ordering rules). Its value holds the number of
    partial plans, their best wish weight and how many reach it, the k best partial plans,
    and the maximal sets of wished courses they contain. For each state, bitmaps over the
    next semester's subset groups pick out the compatible groups before any pair is touched.
    """
    n = len(model.semesters)
    full = (1 << n) - 1
    sem_masks = [sum(1 << s for s in c.offered) for c in model.courses]
    ndim = len(dims)
    caps = [d.cap for d in dims]
    hard = [d.hard for d in dims]
    pk = _Packer(caps, hard)
    shift, soft_bias, soft_guard, caps_packed = pk.shift, pk.soft_bias, pk.soft_guard, pk.caps
    max_contrib = [[max((row.contrib[d] for row in rows), default=0) for d in range(ndim)] for rows in tables]
    track = bool(model.weights)
    reqs = model.requirements
    req_rel = [sem_masks[r.after] | sem_masks[r.course] for r in reqs]

    empty_plan: tuple[tuple[int, ...], ...] = ((),) * n
    states: dict[Any, list[Any]] = {(0, 0, ()): [1, 0, 1, [(0, empty_plan)], [0], _NO_LIMIT]}
    processed = 0
    peak = 1
    for step, j in enumerate(order):
        before = processed
        processed |= 1 << j
        rel_after = _relevant_bits(sem_masks, processed, full)
        in_play = 0
        for m, _, _ in states:
            in_play |= m
        remaining = order[step + 1 :]
        needs = [d.lo - sum(max_contrib[s][i] for s in remaining) for i, d in enumerate(dims)]
        lo_dims = [(i, pk.offsets[i], needs[i]) for i in range(ndim) if needs[i] > 0]
        hi_dims = [(i, pk.offsets[i]) for i in range(ndim) if hard[i]]

        checks: list[tuple[int, int, bool, list[bool]]] = []
        now_bits = 0
        tracked_after = 0
        for r, rel in zip(reqs, req_rel, strict=True):
            if rel & processed and rel & full & ~processed:
                tracked_after |= (1 << r.after) | (1 << r.course)
            if rel & processed and rel & full & ~before:
                now_bits |= (1 << r.after) | (1 << r.course)
                open_after = [s for s in model.courses[r.after].offered if not processed >> s & 1]
                checks.append(
                    (r.after, r.course, r.same_semester, [any(s < jb for s in open_after) for jb in range(n)])
                )
        now_list = [b for b in range(len(model.courses)) if now_bits >> b & 1]

        # Group the semester's subsets by what matters for the rest of the search.
        key_bits = in_play | rel_after | now_bits
        gmap: dict[tuple[int, tuple[int, ...]], list[Any]] = {}
        for row, score in zip(tables[j], scores[j], strict=True):
            gkey = (row.mask & key_bits, row.contrib)
            g = gmap.get(gkey)
            if g is None:
                g = gmap[gkey] = [0, -1, 0, [], set()]
            g[0] += 1
            if row.weight > g[1]:
                g[1], g[2] = row.weight, 1
            elif row.weight == g[1]:
                g[2] += 1
            _push_top(g[3], (score, row.entries), k)
            if track:
                g[4].add(row.wmask)
        glist = []
        for (gm, gc), g in gmap.items():
            anti = _maximal(g[4]) if track else []
            glist.append((gm & rel_after, pk.pack(gc), g[0], g[1], g[2], g[3], g[3][0][0], anti, gm & now_bits))

        # Bitmaps over groups: which groups avoid a course, reach a rule total, fit a ceiling.
        everything = (1 << len(glist)) - 1
        has: dict[int, int] = {}
        by_val = [[0] * (c + 1) for c in caps]
        pats: dict[int, int] = {}
        for gi, (gm, gc) in enumerate(gmap):
            bit = 1 << gi
            rest = gm & in_play
            while rest:
                low = rest & -rest
                b = low.bit_length() - 1
                has[b] = has.get(b, 0) | bit
                rest ^= low
            for d in range(ndim):
                by_val[d][gc[d]] |= bit
            pat = gm & now_bits
            pats[pat] = pats.get(pat, 0) | bit
        not_has = {b: everything ^ v for b, v in has.items()}
        at_least: list[list[int]] = []
        at_most: list[list[int]] = []
        for d in range(ndim):
            acc = 0
            ge_d = [0] * (caps[d] + 1)
            for t in range(caps[d], -1, -1):
                acc |= by_val[d][t]
                ge_d[t] = acc
            at_least.append(ge_d)
            acc = 0
            le_d = [0] * (caps[d] + 1)
            for t in range(caps[d] + 1):
                acc |= by_val[d][t]
                le_d[t] = acc
            at_most.append(le_d)
        pl_cache: dict[Any, tuple[int, dict[int, Any]]] = {}

        new_states: dict[Any, list[Any]] = {}
        for (m, agg, pl), xv in states.items():
            feasible = everything
            rest = m
            while rest and feasible:
                low = rest & -rest
                nh = not_has.get(low.bit_length() - 1)
                if nh is not None:
                    feasible &= nh
                rest ^= low
            for d, off, need in lo_dims:
                t = need - ((agg >> off) & pk.field)
                if t > 0:
                    feasible = feasible & at_least[d][t] if t <= caps[d] else 0
            for d, off in hi_dims:
                room = caps[d] - ((agg >> off) & pk.field)
                if room < caps[d]:
                    feasible &= at_most[d][room]
            if not feasible:
                continue
            new_pl: dict[int, Any] = {}
            if checks:
                cached = pl_cache.get(pl)
                if cached is None:
                    ok = 0
                    for pat, pbits in pats.items():
                        res = _place(pl, pat, j, now_list, checks, tracked_after)
                        if res is not None:
                            ok |= pbits
                            new_pl[pat] = res
                    cached = pl_cache[pl] = (ok, new_pl)
                feasible &= cached[0]
                new_pl = cached[1]
                if not feasible:
                    continue
            x_count, x_best, x_nbest, x_top, x_anti = xv[:5]
            x_top0 = x_top[0][0]
            m_rel = m & rel_after
            bits = bin(feasible)
            find = bits.find
            last = len(bits) - 1
            pos = find("1", 2)
            while pos != -1:
                g_rel, g_pack, g_count, g_best, g_nbest, g_top, g_top0, g_anti, g_pat = glist[last - pos]
                pos = find("1", pos + 1)
                total = agg + g_pack
                over = (total + soft_bias) & soft_guard
                if over:
                    fm = over - (over >> shift)
                    total = (total & ~fm) | (caps_packed & fm)
                key = (m_rel | g_rel, total, new_pl[g_pat] if checks else ())
                tv = new_states.get(key)
                if tv is None:
                    if len(new_states) >= max_states:
                        raise SearchLimitError(
                            f"more than {max_states:,} partial plans after combining "
                            f"{step + 1} of {n} semesters. Fix courses already decided, exclude courses "
                            "you would never take, or raise --max-states."
                        )
                    tv = new_states[key] = [0, -1, 0, [], set(), _NO_LIMIT]
                tv[0] += x_count * g_count
                w = x_best + g_best
                if w > tv[1]:
                    tv[1] = w
                    tv[2] = x_nbest * g_nbest
                elif w == tv[1]:
                    tv[2] += x_nbest * g_nbest
                if x_top0 + g_top0 <= tv[5]:
                    # tv[5] is the score of the k-th best plan once the list is full.
                    t_top = tv[3]
                    for xs, xp in x_top:
                        for gs, gp in g_top:
                            sc = xs + gs
                            if sc > tv[5]:
                                break
                            item = (sc, (*xp[:j], gp, *xp[j + 1 :]))
                            if len(t_top) < k:
                                insort(t_top, item)
                            elif item < t_top[-1]:
                                insort(t_top, item)
                                t_top.pop()
                            else:
                                continue
                            if len(t_top) == k:
                                tv[5] = t_top[-1][0]
                if track:
                    t_anti = tv[4]
                    for a in x_anti:
                        for b in g_anti:
                            t_anti.add(a | b)
        if track:
            for value in new_states.values():
                value[4] = _maximal(value[4])
        states = new_states
        peak = max(peak, len(states))
        if not states:
            break
    return states, peak


def _reduce_dims(
    model: Model, dims: list[Dim], tables: list[list[Row]]
) -> tuple[list[Dim], list[list[Row]], list[str], str | None]:
    """Drop rules that every combination satisfies; stop early on rules none can satisfy.

    Uses the per-semester minimum and maximum contribution of each rule, which is the
    algebraic check worth doing before any search.
    """
    keep: list[int] = []
    always: list[str] = []
    for d, dim in enumerate(dims):
        low = sum(min(row.contrib[d] for row in rows) for rows in tables)
        high = sum(max(row.contrib[d] for row in rows) for rows in tables)
        scale, unit = (model.scale, model.unit) if dim.kind == "credits" else (1, "courses")
        name = dim.limit.label if dim.limit.origin != "category" else f"category {dim.limit.label}"
        if high < dim.lo:
            need = _amount_text(_num(dim.lo, scale), unit)
            return dims, tables, always, f"{name} needs {need}, but at most {_fmt(_num(high, scale))} fit"
        if dim.hard and dim.hi is not None and low > dim.hi:
            allowed = _amount_text(_num(dim.hi, scale), unit)
            return (
                dims,
                tables,
                always,
                f"{name} allows {allowed}, but at least {_fmt(_num(low, scale))} cannot be avoided",
            )
        if low >= dim.lo and (not dim.hard or (dim.hi is not None and high <= dim.hi)):
            always.append(f"{name}: {_bounds_text((dim.lo, dim.hi), scale, unit)}")
            continue
        keep.append(d)
    if len(keep) == len(dims):
        return dims, tables, always, None
    new_tables = [[row._replace(contrib=tuple(row.contrib[d] for d in keep)) for row in rows] for rows in tables]
    return [dims[d] for d in keep], new_tables, always, None


def _pack_scores(model: Model, tables: list[list[Row]]) -> list[list[int]]:
    """One integer per subset: lower is better, additive across semesters.

    Wish weight comes first (negated), then each tie-break criterion. The radix of each
    criterion exceeds the largest total it can reach, so sums never carry across fields.
    """
    n_ties = len(model.tie_break)
    bounds = [sum(max((row.ties[i] for row in rows), default=0) for rows in tables) for i in range(n_ties)]
    mults = [1] * n_ties
    radix = 1
    for i in reversed(range(n_ties)):
        mults[i] = radix
        radix *= bounds[i] + 1
    return [
        [-row.weight * radix + sum(t * m for t, m in zip(row.ties, mults, strict=True)) for row in rows]
        for rows in tables
    ]


def solve(
    model: Model,
    *,
    top: int | None = None,
    max_subsets: int = DEFAULT_MAX_SUBSETS,
    max_states: int = DEFAULT_MAX_STATES,
) -> Result:
    """Enumerate every valid plan of `model` exactly."""
    started = time.perf_counter()
    k = top or model.top
    n = len(model.semesters)
    if model.infeasible:
        return Result(0, -1, 0, [], [], [0] * n, list(range(n)), 0, time.perf_counter() - started, model.infeasible)
    dims = make_dims(model.limits)
    tables = [enumerate_semester(model, dims, j, max_subsets) for j in range(n)]
    counts = [len(rows) for rows in tables]
    empty = [model.semesters[j].id for j in range(n) if not tables[j]]
    if empty:
        reason = (
            f"no course combination meets the semester rules in {', '.join(empty)} "
            "(credit target, exam and course limits, fixed courses, per-semester limits)"
        )
        return Result(0, -1, 0, [], [], counts, list(range(n)), 0, time.perf_counter() - started, reason)
    dims, tables, always, reason = _reduce_dims(model, dims, tables)
    if reason:
        return Result(0, -1, 0, [], [], counts, list(range(n)), 0, time.perf_counter() - started, reason, always)
    scores = _pack_scores(model, tables)
    order = choose_order(model, tables)
    states, peak = _combine(model, dims, tables, scores, order, k, max_states)
    count = 0
    best = -1
    n_best = 0
    plans: list[tuple[int, Any]] = []
    wish_sets: set[int] = set()
    for value in states.values():
        count += value[0]
        if value[1] > best:
            best, n_best = value[1], value[2]
        elif value[1] == best:
            n_best += value[2]
        for item in value[3]:
            _push_top(plans, item, k)
        wish_sets.update(value[4])
    reason = None if count else "the semesters each have valid course combinations, but none fits the plan-wide rules"
    return Result(
        count=count,
        best_weight=best,
        n_best=n_best if count else 0,
        plans=[p for _, p in plans],
        maximal=_maximal(wish_sets) if (count and model.weights) else ([0] if count else []),
        subset_counts=counts,
        order=order,
        peak_states=peak,
        seconds=time.perf_counter() - started,
        reason=reason,
        always_true=always,
    )


# --------------------------------------------------------------------------- reporting


def _num(value: int, scale: int) -> int | float:
    f = Fraction(value, scale)
    return int(f) if f.denominator == 1 else float(f)


def _fmt(value: int | float) -> str:
    return f"{value:,}" if isinstance(value, int) else f"{value:g}"


def _bounds_text(bounds: tuple[int, int | None] | None, scale: int, unit: str) -> str | None:
    if bounds is None:
        return None
    lo, hi = _num(bounds[0], scale), None if bounds[1] is None else _num(bounds[1], scale)
    if hi is None:
        return f">= {_amount_text(lo, unit)}"
    if lo == hi:
        return f"exactly {_amount_text(lo, unit)}"
    if lo == 0:
        return f"<= {_amount_text(hi, unit)}"
    return f"{_fmt(lo)} to {_fmt(hi)} {unit}"


def _amount_text(value: int | float, unit: str) -> str:
    if value == 1 and unit in ("courses", "credits", "exams"):
        unit = unit[:-1]
    return f"{_fmt(value)} {unit}"


def _limit_text(model: Model, limit: Limit) -> str:
    parts = [
        _bounds_text(limit.credits, model.scale, model.unit),
        _bounds_text(limit.count, 1, "courses"),
    ]
    text = ", ".join(p for p in parts if p)
    if limit.per_semester:
        text += " in each semester"
    if limit.scope is not None:
        text += " (counted in " + ", ".join(model.semesters[s].id for s in sorted(limit.scope)) + ")"
    return text


def describe_rules(model: Model) -> list[dict[str, Any]]:
    """The rules as the solver applies them, with the quoted wording where given."""
    out: list[dict[str, Any]] = []
    total = _bounds_text(model.total, model.scale, model.unit) if model.total != (0, None) else None
    if total:
        out.append({"rule": f"total: {total}", "quote": None})
    for sem in model.semesters:
        parts = [_bounds_text((sem.lo, sem.hi), model.scale, model.unit) or "any load"]
        if sem.max_exams is not None:
            parts.append(f"at most {sem.max_exams} exams")
        if sem.min_courses:
            parts.append(f"at least {sem.min_courses} courses")
        if sem.max_courses is not None:
            parts.append(f"at most {sem.max_courses} courses")
        term = f" ({sem.term})" if sem.term else ""
        out.append({"rule": f"semester {sem.id}{term}: " + ", ".join(parts), "quote": None})
    for limit in model.limits:
        if limit.origin in ("category", "limit"):
            name = limit.label if limit.origin == "limit" else f"category {limit.label}"
            out.append({"rule": f"{name}: {_limit_text(model, limit)}", "quote": limit.quote})
        elif limit.origin == "at_most_one_of":
            out.append({"rule": limit.label, "quote": None})
    for r in model.requirements:
        when = "the same or an earlier semester" if r.same_semester else "an earlier semester"
        out.append({"rule": f"{model.courses[r.course].id} needs {model.courses[r.after].id} in {when}", "quote": None})
    pinned = [f"{c.id} in {model.semesters[c.pinned].id}" for c in model.courses if c.pinned is not None]
    free_fixed = [model.courses[b].id for b in sorted(model.fixed_free)]
    if pinned or free_fixed:
        out.append({"rule": "fixed: " + ", ".join(pinned + free_fixed), "quote": None})
    keep = [model.courses[b].id for b in sorted(model.keep) if model.courses[b].pinned is None]
    if keep:
        out.append({"rule": "must keep: " + ", ".join(keep), "quote": None})
    excluded = [c.id for c in model.courses if c.excluded]
    if excluded:
        out.append({"rule": "excluded: " + ", ".join(excluded), "quote": None})
    return out


def _wmask_weight(model: Model, mask: int) -> int:
    return sum(w for b, w in model.weights.items() if mask >> b & 1)


def plan_details(model: Model, plan: tuple[tuple[int, ...], ...], rank: int) -> dict[str, Any]:
    entries = [model.entries[e] for sem in plan for e in sem]
    taken = {e.course.bit for e in entries}
    wished = sorted(model.weights, key=lambda b: (-model.weights[b], natural_key(model.courses[b].id)))
    semesters = []
    for j, sem_entries in enumerate(plan):
        ents = [model.entries[e] for e in sem_entries]
        semesters.append(
            {
                "id": model.semesters[j].id,
                "label": model.semesters[j].label,
                "term": model.semesters[j].term,
                "credits": _num(sum(e.course.credits for e in ents), model.scale),
                "exams": sum(1 for e in ents if e.course.exam),
                "courses": [
                    {
                        "id": e.course.id,
                        "title": e.course.title,
                        "credits": _num(e.course.credits, model.scale),
                        "category": e.category,
                        "exam": e.course.exam,
                        "wish_weight": _num(model.weights[e.course.bit], model.weight_scale)
                        if e.course.bit in model.weights
                        else None,
                    }
                    for e in ents
                ],
            }
        )
    totals = []
    by_cat_limit = {lim.key: lim for lim in model.limits if lim.origin == "category"}
    for cid, name in model.categories.items():
        ents = [e for e in entries if e.category == cid]
        limit = by_cat_limit.get(cid)
        totals.append(_total_row(model, cid, f"{name}", ents, limit))
    for limit in model.limits:
        if limit.origin in ("limit", "at_most_one_of", "total") and not limit.per_semester:
            ents = [e for e in entries if e.index in limit.members]
            if limit.scope is not None:
                ents = [e for e in ents if _semester_of(plan, e.index) in limit.scope]
            totals.append(_total_row(model, limit.key, limit.label, ents, limit))
    return {
        "rank": rank,
        "weight": _num(sum(model.weights.get(b, 0) for b in taken), model.weight_scale),
        "credits": _num(sum(e.course.credits for e in entries), model.scale),
        "exams": sum(1 for e in entries if e.course.exam),
        "courses": len(entries),
        "wished_kept": [model.courses[b].id for b in wished if b in taken],
        "wished_dropped": [model.courses[b].id for b in wished if b not in taken],
        "semesters": semesters,
        "totals": totals,
    }


def _semester_of(plan: tuple[tuple[int, ...], ...], entry_index: int) -> int:
    for j, sem in enumerate(plan):
        if entry_index in sem:
            return j
    return -1


def _total_row(model: Model, key: str, label: str, ents: list[Entry], limit: Limit | None) -> dict[str, Any]:
    credits = sum(e.course.credits for e in ents)
    count = len(ents)
    ok = True
    if limit is not None:
        for bounds, value in ((limit.credits, credits), (limit.count, count)):
            if bounds is not None and (value < bounds[0] or (bounds[1] is not None and value > bounds[1])):
                ok = False
    return {
        "key": key,
        "name": label,
        "credits": _num(credits, model.scale),
        "courses": count,
        "rule": _limit_text(model, limit) if limit is not None else None,
        "ok": ok,
    }


def wish_summary(model: Model, result: Result) -> dict[str, Any]:
    wished = sorted(model.weights, key=lambda b: (-model.weights[b], natural_key(model.courses[b].id)))
    maximal = result.maximal if result.count else []
    rows = []
    for b in wished:
        sets = [m for m in maximal if m >> b & 1]
        rows.append(
            {
                "id": model.courses[b].id,
                "title": model.courses[b].title,
                "weight": _num(model.weights[b], model.weight_scale),
                "keep": b in model.keep,
                "in_some_plan": bool(sets),
                "best_weight_with": _num(max(_wmask_weight(model, m) for m in sets), model.weight_scale)
                if sets
                else None,
            }
        )
    reachable = [b for b in wished if any(m >> b & 1 for m in maximal)]
    never = []
    for a, b in itertools.combinations(sorted(reachable, key=lambda x: natural_key(model.courses[x].id)), 2):
        if not any(m >> a & 1 and m >> b & 1 for m in maximal):
            never.append([model.courses[a].id, model.courses[b].id])
    largest = sorted(
        maximal,
        key=lambda m: (
            -_wmask_weight(model, m),
            -m.bit_count(),
            [natural_key(model.courses[b].id) for b in wished if m >> b & 1],
        ),
    )
    return {
        "courses": rows,
        "never_together": never,
        "largest_sets": [
            {
                "weight": _num(_wmask_weight(model, m), model.weight_scale),
                "courses": [model.courses[b].id for b in wished if m >> b & 1],
                "dropped": [model.courses[b].id for b in wished if not m >> b & 1],
            }
            for m in largest
        ]
        if model.weights
        else [],
    }


def ranking_text(model: Model) -> str:
    parts = ["highest wish weight"] + [TIE_BREAKS[t] for t in model.tie_break]
    parts.append("course ids in semester order")
    return ", then ".join(parts)


def run_summary(model: Model, result: Result) -> dict[str, Any]:
    max_weight = sum(model.weights.values())
    return {
        "valid_plans": result.count,
        "reason": result.reason if not result.count else None,
        "search": {
            "subsets_per_semester": [
                {
                    "semester": s.id,
                    "term": s.term,
                    "credits": _bounds_text((s.lo, s.hi), model.scale, model.unit),
                    "subsets": result.subset_counts[s.index],
                }
                for s in model.semesters
            ],
            "processing_order": [model.semesters[j].id for j in result.order],
            "largest_state_count": result.peak_states,
            "runtime_seconds": round(result.seconds, 3),
        },
        "best": {
            "weight": _num(result.best_weight, model.weight_scale),
            "max_possible_weight": _num(max_weight, model.weight_scale),
            "tied_plans": result.n_best,
        }
        if result.count
        else None,
        "ranking": ranking_text(model),
        "plans": [plan_details(model, p, i + 1) for i, p in enumerate(result.plans)],
        "wishes": wish_summary(model, result),
        "notes": list(model.notes),
        "never_binding": list(result.always_true),
    }


def diagnose(model: Model, *, max_subsets: int, max_states: int) -> list[dict[str, Any]]:
    """For an infeasible plan: drop one plan-wide rule at a time and count the plans."""
    out = []
    candidates: list[tuple[str, Model]] = []
    for i, limit in enumerate(model.limits):
        if limit.per_semester:
            continue
        label = limit.label if limit.origin != "category" else f"category {limit.label}"
        candidates.append(
            (f"{label}: {_limit_text(model, limit)}", replace(model, limits=model.limits[:i] + model.limits[i + 1 :]))
        )
    for i, r in enumerate(model.requirements):
        label = f"{model.courses[r.course].id} needs {model.courses[r.after].id} first"
        candidates.append((label, replace(model, requirements=model.requirements[:i] + model.requirements[i + 1 :])))
    if any(s.max_exams is not None for s in model.semesters):
        sems = [replace(s, max_exams=None) for s in model.semesters]
        candidates.append(("exam limits per semester", replace(model, semesters=sems)))
    for label, relaxed in candidates:
        try:
            count = solve(relaxed, top=1, max_subsets=max_subsets, max_states=max_states).count
        except SearchLimitError:
            count = None
        out.append({"dropped_rule": label, "valid_plans": count})
    return out


def run_document(
    cfg: dict[str, Any],
    *,
    variants: list[dict[str, Any]] | None = None,
    top: int | None = None,
    max_subsets: int = DEFAULT_MAX_SUBSETS,
    max_states: int = DEFAULT_MAX_STATES,
) -> dict[str, Any]:
    """Solve the baseline and every variant; return one JSON-ready document."""
    base_cfg = {key: value for key, value in cfg.items() if key != "variants"}
    model = build_model(base_cfg)
    result = solve(model, top=top, max_subsets=max_subsets, max_states=max_states)
    base = run_summary(model, result)
    if not result.count and not model.infeasible:
        base["diagnosis"] = diagnose(model, max_subsets=max_subsets, max_states=max_states)
    doc: dict[str, Any] = {
        "program": {"name": model.name, "credit_unit": model.unit, "source": model.source},
        "rules": describe_rules(model),
        "baseline": base,
        "variants": [],
    }
    base_reach = {row["id"] for row in base["wishes"]["courses"] if row["in_some_plan"]}
    base_best = base["best"]["weight"] if base["best"] else None
    for variant in variants or []:
        name = str(variant.get("name") or "variant")
        patch = {key: value for key, value in variant.items() if key not in VARIANT_META_KEYS}
        entry: dict[str, Any] = {"name": name, "description": variant.get("description"), "changes": patch}
        try:
            for key in patch:
                if key not in TOP_KEYS - {"variants"}:
                    raise ConfigError(f"variant '{name}': cannot change '{key}'")
            vmodel = build_model(apply_patch(base_cfg, patch))
            vresult = solve(vmodel, top=top, max_subsets=max_subsets, max_states=max_states)
        except (ConfigError, SearchLimitError) as exc:
            entry["error"] = str(exc)
            doc["variants"].append(entry)
            continue
        summary = run_summary(vmodel, vresult)
        reach = {row["id"] for row in summary["wishes"]["courses"] if row["in_some_plan"]}
        best = summary["best"]["weight"] if summary["best"] else None
        entry.update(summary)
        entry["delta"] = {
            "valid_plans": vresult.count - result.count,
            "best_weight": None if best is None or base_best is None else best - base_best,
            "now_reachable": sorted(reach - base_reach, key=natural_key),
            "no_longer_reachable": sorted(base_reach - reach, key=natural_key),
        }
        doc["variants"].append(entry)
    return doc


def _table(rows: list[list[str]], indent: str = "  ") -> list[str]:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    out = []
    for row in rows:
        cells = [cell.ljust(widths[i]) if i < len(row) - 1 else cell for i, cell in enumerate(row)]
        out.append((indent + "  ".join(cells)).rstrip())
    return out


def render_text(doc: dict[str, Any]) -> str:
    unit = doc["program"]["credit_unit"]
    lines = [doc["program"]["name"], "=" * len(doc["program"]["name"])]
    if doc["program"].get("source"):
        lines.append(f"Source: {doc['program']['source']}")
    lines += ["", "Rules as modelled"]
    for rule in doc["rules"]:
        lines.append(f"  {rule['rule']}")
        if rule.get("quote"):
            lines.append(f'    "{rule["quote"]}"')
    base = doc["baseline"]
    lines += ["", *_render_run(base, unit, "Baseline")]
    if doc["variants"]:
        lines += ["", "Price of each variant (compared with the baseline)"]
        rows = [["variant", "valid plans", "change", "best weight", "change"]]
        best = base["best"]["weight"] if base["best"] else None
        rows.append(["baseline", _fmt(base["valid_plans"]), "", "-" if best is None else _fmt(best), ""])
        for v in doc["variants"]:
            if v.get("error"):
                rows.append([v["name"], "error", "", "", ""])
                continue
            vb = v["best"]["weight"] if v["best"] else None
            dw = v["delta"]["best_weight"]
            rows.append(
                [
                    v["name"],
                    _fmt(v["valid_plans"]),
                    f"{v['delta']['valid_plans']:+,}",
                    "-" if vb is None else _fmt(vb),
                    "" if dw is None else (f"+{_fmt(dw)}" if dw > 0 else _fmt(dw)),
                ]
            )
        lines += _table(rows)
        for v in doc["variants"]:
            lines += ["", f"Variant: {v['name']}"]
            if v.get("description"):
                lines.append(f"  {v['description']}")
            if v.get("error"):
                lines.append(f"  error: {v['error']}")
                continue
            lines.append(f"  changes: {json.dumps(v['changes'], ensure_ascii=False)}")
            d = v["delta"]
            if d["now_reachable"]:
                lines.append("  wished courses that become possible: " + ", ".join(d["now_reachable"]))
            if d["no_longer_reachable"]:
                lines.append("  wished courses that become impossible: " + ", ".join(d["no_longer_reachable"]))
            if v["plans"]:
                lines += _render_plan_compact(v["plans"][0], unit)
            elif v.get("reason"):
                lines.append(f"  no valid plan: {v['reason']}")
    return "\n".join(lines) + "\n"


def _render_run(run: dict[str, Any], unit: str, title: str) -> list[str]:
    lines = [title, "-" * len(title)]
    search = run["search"]
    rows = [["semester", "term", "load", "valid course combinations"]]
    for s in search["subsets_per_semester"]:
        rows.append([s["semester"], s["term"] or "", s["credits"] or "", _fmt(s["subsets"])])
    lines += _table(rows)
    lines.append(
        f"  combined in the order {', '.join(search['processing_order'])}; "
        f"largest intermediate state count {_fmt(search['largest_state_count'])}; "
        f"{search['runtime_seconds']:.2f} s"
    )
    lines.append("")
    lines.append(f"Valid plans: {_fmt(run['valid_plans'])}")
    if not run["valid_plans"]:
        lines.append(f"  Reason: {run['reason']}")
        for d in run.get("diagnosis", []):
            count = "too large to count" if d["valid_plans"] is None else _fmt(d["valid_plans"])
            lines.append(f"  without '{d['dropped_rule']}': {count} plans")
        for note in run["notes"]:
            lines.append(f"  note: {note}")
        return lines
    best = run["best"]
    wish_rows = run["wishes"]["courses"]
    if wish_rows:
        kept = run["plans"][0]["wished_kept"] if run["plans"] else []
        lines.append(
            f"Best wish weight: {_fmt(best['weight'])} of {_fmt(best['max_possible_weight'])} "
            f"({len(kept)} of {len(wish_rows)} wished courses)"
        )
        lines.append(f"Plans with the best weight: {_fmt(best['tied_plans'])}")
    lines.append(f"Ranking: {run['ranking']}")
    if run.get("never_binding"):
        lines.append("Rules that every semester combination already meets (settled within semesters or never binding):")
        lines += [f"  {item}" for item in run["never_binding"]]
    for note in run["notes"]:
        lines.append(f"Note: {note}")
    if wish_rows:
        lines += ["", "Wished courses"]
        rows = [["course", "title", "weight", "in some plan", "best weight with it"]]
        for w in wish_rows:
            rows.append(
                [
                    w["id"] + (" (keep)" if w["keep"] else ""),
                    w["title"],
                    _fmt(w["weight"]),
                    "yes" if w["in_some_plan"] else "no",
                    "-" if w["best_weight_with"] is None else _fmt(w["best_weight_with"]),
                ]
            )
        lines += _table(rows)
        never = run["wishes"]["never_together"]
        lines.append("  Never together: " + ("; ".join(" + ".join(p) for p in never) if never else "none"))
        largest = run["wishes"]["largest_sets"]
        lines.append(f"  Largest combinations of wished courses that fit ({len(largest)}):")
        for s in largest[:8]:
            dropped = ", ".join(s["dropped"]) or "nothing"
            lines.append(f"    weight {_fmt(s['weight'])}: {', '.join(s['courses']) or '(none)'}; drops {dropped}")
        if len(largest) > 8:
            lines.append(f"    ... {len(largest) - 8} more in the JSON output")
    for plan in run["plans"]:
        lines += ["", *_render_plan(plan, unit, f"Plan {plan['rank']}")]
    return lines


def _render_plan_compact(plan: dict[str, Any], unit: str) -> list[str]:
    kept = ", ".join(plan["wished_kept"]) or "no wished course"
    dropped = ", ".join(plan["wished_dropped"]) or "nothing"
    lines = [f"  Best plan (wish weight {_fmt(plan['weight'])}) keeps {kept}; drops {dropped}"]
    for sem in plan["semesters"]:
        ids = ", ".join(c["id"] for c in sem["courses"]) or "(none)"
        lines.append(
            f"    {sem['id']}: {ids} ({_amount_text(sem['credits'], unit)}, {_amount_text(sem['exams'], 'exams')})"
        )
    return lines


def _render_plan(plan: dict[str, Any], unit: str, title: str) -> list[str]:
    indent = "  " if title.startswith("  ") else ""
    lines = [
        f"{title}: wish weight {_fmt(plan['weight'])}, {_fmt(plan['credits'])} {unit}, "
        f"{plan['exams']} exams, {plan['courses']} courses"
    ]
    for sem in plan["semesters"]:
        about = [x for x in (sem["label"] if sem["label"] != sem["id"] else None, sem["term"]) if x]
        term = f" ({', '.join(about)})" if about else ""
        exams = _amount_text(sem["exams"], "exams")
        lines.append(f"{indent}  {sem['id']}{term}: {_amount_text(sem['credits'], unit)}, {exams}")
        rows = []
        for c in sem["courses"]:
            mark = f"wish {_fmt(c['wish_weight'])}" if c["wish_weight"] is not None else ""
            rows.append([c["id"], c["title"], _fmt(c["credits"]), c["category"], "exam" if c["exam"] else "", mark])
        if rows:
            lines += _table(rows, indent + "    ")
    if plan["wished_dropped"]:
        lines.append(f"{indent}  Wished but not in this plan: {', '.join(plan['wished_dropped'])}")
    lines.append(f"{indent}  Totals:")
    rows = []
    for t in plan["totals"]:
        rule = t["rule"] or "no rule"
        status = "" if t["ok"] else "VIOLATED"
        rows.append([t["name"], _amount_text(t["credits"], unit), _amount_text(t["courses"], "courses"), rule, status])
    lines += _table(rows, indent + "    ")
    return lines


# --------------------------------------------------------------------------- command line


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Enumerate every valid study plan, rank by wishes and price each variant.",
    )
    parser.add_argument("program", help="program file (.yaml, .yml or .json)")
    parser.add_argument("--top", type=int, help="number of best plans to show (default: ranking.top or 3)")
    parser.add_argument("--json", action="store_true", help="print JSON instead of the text report")
    parser.add_argument("--output", help="also write the report (text or JSON) to this file")
    parser.add_argument("--variant", action="append", default=[], help="run only the named variant (repeatable)")
    parser.add_argument("--no-variants", action="store_true", help="skip the variants in the file")
    parser.add_argument("--set", action="append", default=[], metavar="PATH=VALUE", help="ad-hoc variant: set a value")
    parser.add_argument("--drop", action="append", default=[], metavar="PATH", help="ad-hoc variant: remove a rule")
    parser.add_argument("--max-subsets", type=int, default=DEFAULT_MAX_SUBSETS, help="per-semester subset limit")
    parser.add_argument("--max-states", type=int, default=DEFAULT_MAX_STATES, help="partial-plan state limit")
    args = parser.parse_args(argv)

    try:
        cfg = load_config(args.program)
        file_variants = _as_list(cfg.get("variants"), "variants")
        for i, v in enumerate(file_variants):
            if not isinstance(v, dict) or not v.get("name"):
                raise ConfigError(f"variants[{i}]: each variant needs a name")
        if args.no_variants:
            file_variants = []
        elif args.variant:
            names = {v["name"] for v in file_variants}
            for wanted in args.variant:
                if wanted not in names:
                    raise ConfigError(f"--variant: no variant named '{wanted}' in the file")
            file_variants = [v for v in file_variants if v["name"] in args.variant]
        variants = list(file_variants)
        if args.set or args.drop:
            patch: dict[str, Any] = {}
            labels = []
            for item in args.set:
                path, value = parse_set(item)
                _set_path(patch, path, value)
                labels.append(f"{path}={json.dumps(value)}")
            for path in args.drop:
                _set_path(patch, path, None)
                labels.append(f"without {path}")
            variants.append({"name": "; ".join(labels), **patch})
        doc = run_document(
            cfg,
            variants=variants,
            top=args.top,
            max_subsets=args.max_subsets,
            max_states=args.max_states,
        )
    except ConfigError as exc:
        print(f"error in the program file: {exc}", file=sys.stderr)
        return 2
    except SearchLimitError as exc:
        print(f"search stopped: {exc}", file=sys.stderr)
        return 3
    text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n" if args.json else render_text(doc)
    sys.stdout.write(text)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    return 0


def _set_path(patch: dict[str, Any], path: str, value: Any) -> None:
    """Set a dotted path inside a patch; a null value means "remove this" when the patch is applied."""
    parts = [p for p in path.split(".") if p]
    if not parts:
        raise ConfigError(f"empty path in '{path}'")
    node = patch
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            child = node[part] = {}
        node = child
    node[parts[-1]] = value


if __name__ == "__main__":
    sys.exit(main())
