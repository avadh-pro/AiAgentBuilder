"""Skill loader.

Reads SKILL.md files from ~/.claude/skills/<slug>/ and strips the YAML
frontmatter, yielding instructions text suitable for the `instructions=`
field of an openai-agents Agent.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml


class SkillNotFoundError(RuntimeError):
    pass


def _skills_root() -> Path:
    home = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    if not home:
        raise SkillNotFoundError("cannot locate user home directory")
    return Path(home) / ".claude" / "skills"


def _candidate_files(slug: str) -> list[Path]:
    root = _skills_root() / slug
    return [root / "SKILL.md", root / "skill.md"]


def find_skill_file(slug: str) -> Path:
    for c in _candidate_files(slug):
        if c.exists():
            return c
    raise SkillNotFoundError(
        f"skill {slug!r} not found. searched: " + ", ".join(str(c) for c in _candidate_files(slug))
    )


def load_skill_instructions(slug: str) -> str:
    """Return the body of the SKILL.md file with frontmatter stripped."""
    path = find_skill_file(slug)
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        # split frontmatter from body
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return text.strip()


def load_skill_frontmatter(slug: str) -> dict:
    """Return the parsed YAML frontmatter (or {} if absent)."""
    path = find_skill_file(slug)
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    parsed = yaml.safe_load(parts[1])
    return parsed if isinstance(parsed, dict) else {}
