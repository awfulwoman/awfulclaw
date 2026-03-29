"""Skills — load and match SKILL.md files from memory/skills/."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_SKILLS_DIR = Path("memory/skills")


@dataclass
class Skill:
    name: str
    triggers: list[str]
    instruction: str
    body: str


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str] | None:
    """Parse YAML-style frontmatter from a markdown file. Returns (fields, body) or None."""
    if not text.startswith("---"):
        return None
    end = text.find("---", 3)
    if end == -1:
        return None
    front = text[3:end].strip()
    body = text[end + 3:].strip()
    fields: dict[str, str] = {}
    for line in front.splitlines():
        m = re.match(r"^(\w+)\s*:\s*(.*)$", line)
        if m:
            fields[m.group(1)] = m.group(2).strip()
    return fields, body


def load_skills() -> list[Skill]:
    """Load all skill files from memory/skills/."""
    if not _SKILLS_DIR.exists():
        return []
    skills: list[Skill] = []
    for path in sorted(_SKILLS_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        parsed = _parse_frontmatter(text)
        if parsed is None:
            continue
        fields, body = parsed
        if "trigger" not in fields or "instruction" not in fields:
            continue
        triggers = [t.strip() for t in fields["trigger"].split(",") if t.strip()]
        if not triggers:
            continue
        skills.append(Skill(
            name=path.stem,
            triggers=triggers,
            instruction=fields["instruction"],
            body=body,
        ))
    return skills


def match_skills(message: str, skills: list[Skill]) -> list[Skill]:
    """Return skills where at least one trigger keyword appears as a whole word in message."""
    matched: list[Skill] = []
    for skill in skills:
        for trigger in skill.triggers:
            pattern = r"\b" + re.escape(trigger) + r"\b"
            if re.search(pattern, message, re.IGNORECASE):
                matched.append(skill)
                break
    return matched
