# Claude skills

[![CI](https://github.com/mooofna/claude-skills/actions/workflows/ci.yml/badge.svg)](https://github.com/mooofna/claude-skills/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Skills that teach Claude a complete workflow, each with tested scripts for the parts that should not be left to judgement. They grew out of my own studies and work on medical imaging, and are written so that anyone can use them with their own notes, courses and degree rules.

| Skill | What it does |
|---|---|
| [paper-to-obsidian](skills/paper-to-obsidian) | Rough phone photos of handwritten pages become word-for-word transcriptions filed into the right notes of an Obsidian vault, with open items pulled out and a scan-quality archive PDF. Includes a document scanner (perspective, crop, lighting) that never cuts off content. |
| [anki-lecture-cards](skills/anki-lecture-cards) | Lecture slides, readings, exercise sheets and old exams become exam-oriented Anki decks, built from one YAML file per lecture with stable ids, a proof sheet, a coverage table and an optional exam formula sheet. |
| [curriculum-solver](skills/curriculum-solver) | Study-plan questions are answered by enumerating every valid plan under the program rules, then ranking by what you want to keep, with the price of each rule in plans and wished courses. |

## Install

**Claude Code.** Add this repository as a plugin marketplace, then install the skills you want:

```text
/plugin marketplace add mooofna/claude-skills
/plugin install paper-to-obsidian@heide-skills
/plugin install anki-lecture-cards@heide-skills
/plugin install curriculum-solver@heide-skills
```

**claude.ai and the Claude apps.** Download a skill's zip from the [latest release](https://github.com/mooofna/claude-skills/releases/latest) and upload it in the Skills section of the settings.

**By hand.** Copy a folder from `skills/` into `~/.claude/skills/` (all projects) or `.claude/skills/` (one project).

Each skill lists its Python packages in its own `requirements.txt`; Claude installs them when a script asks for them.

## Layout

```text
skills/<name>/
  SKILL.md           instructions Claude reads when the skill applies
  README.md          what the skill does, for people
  scripts/           the tested tools the instructions call
  references/        detail Claude reads only when needed
  tests/             pytest suite
tools/package_skills.py   checks every SKILL.md and builds the release zips
.claude-plugin/marketplace.json   the Claude Code plugin catalogue
```

## Development

```bash
for req in skills/*/requirements.txt; do pip install -r "$req"; done
pip install pytest ruff
pytest skills
ruff check . && ruff format --check .
python tools/package_skills.py        # writes dist/<skill>.zip
```

CI runs the tests on Python 3.10 to 3.13. Publishing a GitHub release builds the zips and attaches them to it.

## License

[MIT](LICENSE), Maurice Heide.
