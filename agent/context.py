from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from agent.config import Settings
from agent.store import Store

_CONTEXT_BUDGET = 32000  # chars for system prompt sections
_HISTORY_RESERVE = 8000  # chars reserved for conversation history


class ContextAssembler:
    def __init__(self, store: Store, settings: Settings) -> None:
        self._store = store
        self._settings = settings

    async def build(
        self,
        message: str,
        sender: Optional[str],
        channel: str,
        connector: str = "",
    ) -> str:
        cfg = self._settings.profile_path

        # Always-included sections
        personality = await _read_config(cfg / "PERSONALITY.md")
        protocols = await _read_config(cfg / "PROTOCOLS.md")
        user_profile = await _read_config(cfg / "USER.md")
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        skill_names = await _list_skills(self._settings)

        # Personality log — non-expired approved/escalated entries
        log_entries = await self._store.list_personality_log()

        # Budget-allocated sections
        budget = _CONTEXT_BUDGET - _HISTORY_RESERVE

        # Always include schedules (small)
        schedules = await self._store.list_schedules()

        # Semantic search for facts and people
        facts = await self._store.search_facts(message, limit=10)
        people = await self._store.search_people(
            f"{sender} {message}" if sender else message, limit=5
        )

        # Build sections
        sections: list[str] = []
        sections.append(f"# Identity\n{personality}")
        sections.append(f"# Protocols\n{protocols}")
        sections.append(f"# User Profile\n{user_profile}")
        channel_info = f"channel: {channel}"
        if connector:
            channel_info += f", connector: {connector}"
        sections.append(f"# Current Time\n{now}\n{channel_info}")

        if skill_names:
            sections.append(f"# Available Skills\n" + "\n".join(f"- {s}" for s in skill_names))

        if log_entries:
            entries_text = "\n".join(f"- {e}" for e in log_entries)
            sections.append(f"# Personality Notes\n{entries_text}")

        if schedules:
            sched_lines = [f"- {s.name}: {s.cron or s.fire_at}" for s in schedules]
            sections.append("# Schedules\n" + "\n".join(sched_lines))

        # Fill remaining budget with facts and people
        remaining = budget - sum(len(s) for s in sections)

        if facts and remaining > 0:
            fact_lines: list[str] = []
            for f in facts:
                line = f"- {f.key}: {f.value}"
                if remaining - len(line) < 0:
                    break
                fact_lines.append(line)
                remaining -= len(line)
            if fact_lines:
                sections.append("# Facts\n" + "\n".join(fact_lines))

        if people and remaining > 0:
            people_lines: list[str] = []
            for p in people:
                line = f"- {p.name}: {p.content}"
                if remaining - len(line) < 0:
                    break
                people_lines.append(line)
                remaining -= len(line)
            if people_lines:
                sections.append("# People\n" + "\n".join(people_lines))

        return "\n\n".join(sections)


async def _read_config(path: Path) -> str:
    """Read a config file, stripping YAML frontmatter if present."""
    try:
        text = await asyncio.to_thread(path.read_text, encoding="utf-8")
    except FileNotFoundError:
        return ""
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        end = next((i for i, l in enumerate(lines[1:], 1) if l.strip() == "---"), None)
        if end is not None:
            return "\n".join(lines[end + 1 :]).strip()
    return text.strip()


async def _list_skills(settings: Settings) -> list[str]:
    skills_dir = Path("config/skills")
    try:
        names = await asyncio.to_thread(
            lambda: sorted(p.stem for p in skills_dir.glob("*.md"))
        )
        return names
    except (FileNotFoundError, OSError):
        return []
