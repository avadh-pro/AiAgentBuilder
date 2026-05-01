"""Skill integrity verification — FR-005 / AC-005-1.

Computes SHA-256 of every existing skill that predates this project and asserts
that the implementation has not modified any of them. Run as a CLI:

    python -m carousel_agent.skill_integrity
    python -m carousel_agent.skill_integrity --baseline baseline.json
    python -m carousel_agent.skill_integrity --update-baseline
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

# Skills that existed BEFORE this project. The carousel pipeline must not modify them.
PRE_EXISTING_SKILLS: tuple[str, ...] = (
    "amarolabs-news",
    "carousel-style",
    "neuro-scriptwriter",
    "design-preferences",
    "caption-overlay",
    "transcript-router",
    "remotion-creator",
    "hook-square-split",
    "kling-motion-control",
    "kling-multi-shot",
    "kling-prompt-master",
    "video-frames",
)

# Skills CREATED by this project; they are EXPECTED to exist but not in the baseline.
NEW_SKILLS: tuple[str, ...] = (
    "amarolabs-news-carousel",
    "neuro-carousel-writer",
    "amara-news-carousel",
)


def _skills_root() -> Path:
    home = os.environ.get("USERPROFILE") or os.environ.get("HOME") or ""
    return Path(home) / ".claude" / "skills"


def _hash_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def compute_hashes(slugs: tuple[str, ...]) -> dict[str, dict[str, str]]:
    """Return {slug: {filename: sha256}} for every file in each skill dir."""
    root = _skills_root()
    out: dict[str, dict[str, str]] = {}
    for slug in slugs:
        d = root / slug
        if not d.exists():
            out[slug] = {"__missing__": "skill directory not found"}
            continue
        out[slug] = {p.name: _hash_file(p) for p in sorted(d.iterdir()) if p.is_file()}
    return out


def verify(baseline_path: Path) -> tuple[bool, list[str]]:
    """Return (ok, problems). ok=True iff every pre-existing-skill file matches."""
    if not baseline_path.exists():
        return False, [f"baseline file missing: {baseline_path}"]
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    current = compute_hashes(PRE_EXISTING_SKILLS)
    problems: list[str] = []
    for slug in PRE_EXISTING_SKILLS:
        baseline_slug = baseline.get(slug, {})
        current_slug = current.get(slug, {})
        if "__missing__" in current_slug and "__missing__" not in baseline_slug:
            problems.append(f"{slug}: skill directory disappeared")
            continue
        for fname, h in baseline_slug.items():
            if fname == "__missing__":
                continue
            if current_slug.get(fname) != h:
                problems.append(f"{slug}/{fname}: hash changed")
        for fname in current_slug:
            if fname not in baseline_slug and fname != "__missing__":
                problems.append(f"{slug}/{fname}: new file added (not in baseline)")
    return (not problems), problems


def main() -> int:
    args = sys.argv[1:]
    baseline_arg = None
    update = False
    for i, a in enumerate(args):
        if a == "--baseline" and i + 1 < len(args):
            baseline_arg = Path(args[i + 1])
        elif a == "--update-baseline":
            update = True

    default_baseline = (
        Path(__file__).resolve().parents[1] / "skill_integrity_baseline.json"
    )
    baseline = baseline_arg or default_baseline

    if update:
        snapshot = compute_hashes(PRE_EXISTING_SKILLS)
        baseline.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")
        print(f"baseline written: {baseline}")
        return 0

    ok, problems = verify(baseline)
    if ok:
        print(f"OK — all {len(PRE_EXISTING_SKILLS)} pre-existing skills unmodified.")
        return 0
    print("FAIL — skill integrity violations:")
    for p in problems:
        print(f"  {p}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
