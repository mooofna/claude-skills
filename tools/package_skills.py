#!/usr/bin/env python3
"""Build one upload-ready zip per skill (for claude.ai) and check every SKILL.md.

Each zip holds a single top-level folder named after the skill, with SKILL.md
inside it. Tests, caches and other development files are left out.

Usage:
  python3 tools/package_skills.py            # check and build dist/<skill>.zip
  python3 tools/package_skills.py --check    # only check the SKILL.md files
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
EXCLUDE_DIRS = {"tests", "__pycache__", ".pytest_cache", ".ruff_cache", "build", "dist"}
EXCLUDE_FILES = {".DS_Store"}
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def frontmatter(skill_md: Path) -> dict[str, str]:
    text = skill_md.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        raise ValueError(f"{skill_md}: no YAML frontmatter")
    fields = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and not line.startswith((" ", "\t")):
            fields[key.strip()] = value.strip().strip('"')
    return fields


def check(skill_dir: Path) -> list[str]:
    problems = []
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return [f"{skill_dir.name}: SKILL.md missing"]
    try:
        fields = frontmatter(skill_md)
    except ValueError as error:
        return [str(error)]
    name, description = fields.get("name", ""), fields.get("description", "")
    if name != skill_dir.name:
        problems.append(f"{skill_dir.name}: name '{name}' differs from the folder name")
    if not NAME_RE.match(name) or len(name) > 64:
        problems.append(f"{skill_dir.name}: name must be lowercase letters, digits and hyphens, at most 64 characters")
    if "claude" in name or "anthropic" in name:
        problems.append(f"{skill_dir.name}: name must not contain 'claude' or 'anthropic'")
    if not description or len(description) > 1024:
        problems.append(f"{skill_dir.name}: description must be 1 to 1024 characters (has {len(description)})")
    return problems


def package(skill_dir: Path, dist: Path) -> Path:
    dist.mkdir(parents=True, exist_ok=True)
    target = dist / f"{skill_dir.name}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(skill_dir.rglob("*")):
            relative = path.relative_to(skill_dir)
            if path.is_dir() or path.name in EXCLUDE_FILES or EXCLUDE_DIRS.intersection(relative.parts):
                continue
            archive.write(path, Path(skill_dir.name) / relative)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="only check the SKILL.md files")
    parser.add_argument("--dist", default=str(ROOT / "dist"), help="output folder for the zips")
    args = parser.parse_args(argv)

    skill_dirs = sorted(p for p in SKILLS.iterdir() if p.is_dir())
    problems = [problem for skill_dir in skill_dirs for problem in check(skill_dir)]
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"{len(skill_dirs)} skills checked")
    if not args.check:
        for skill_dir in skill_dirs:
            print(package(skill_dir, Path(args.dist)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
