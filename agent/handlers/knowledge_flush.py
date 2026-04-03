"""Knowledge flush handler — daily export of facts and people to Obsidian vault."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.bus import ScheduleEvent
    from agent.store import Store

DAILY_FLUSH_SCHEDULE_NAME = "daily-flush"
DAILY_FLUSH_CRON = "0 2 * * *"  # 2am daily
DAILY_FLUSH_PROMPT = "daily knowledge flush"


class KnowledgeFlushHandler:
    def __init__(self, store: "Store", vault_path: Path) -> None:
        self._store = store
        self._vault_path = vault_path

    async def ensure_default_schedule(self) -> None:
        """Create the daily-flush schedule if it doesn't already exist."""
        schedules = await self._store.list_schedules()
        names = {s.name for s in schedules}
        if DAILY_FLUSH_SCHEDULE_NAME not in names:
            from agent.store import Schedule

            schedule = Schedule(
                id=str(uuid.uuid4()),
                name=DAILY_FLUSH_SCHEDULE_NAME,
                cron=DAILY_FLUSH_CRON,
                fire_at=None,
                prompt=DAILY_FLUSH_PROMPT,
                silent=True,
                tz="",
                created_at=datetime.now(timezone.utc).isoformat(),
                last_run=None,
            )
            await self._store.upsert_schedule(schedule)

    async def handle(self, event: "ScheduleEvent") -> None:
        """Flush facts and people if this is a daily-flush schedule event."""
        if event.schedule.name != DAILY_FLUSH_SCHEDULE_NAME:
            return
        await self.flush()

    async def flush(self) -> None:
        """Write facts and people markdown files to the Obsidian vault."""
        facts = await self._store.list_facts()
        people = await self._store.list_people()

        self._vault_path.mkdir(parents=True, exist_ok=True)

        facts_lines = ["# Facts\n"]
        for fact in facts:
            facts_lines.append(f"## {fact.key}\n\n{fact.value}\n\n_Updated: {fact.updated_at}_\n")
        self._atomic_write(self._vault_path / "facts.md", "\n".join(facts_lines))

        people_lines = ["# People\n"]
        for person in people:
            people_lines.append(f"## {person.name}\n")
            if person.phone:
                people_lines.append(f"**Phone:** {person.phone}\n")
            people_lines.append(f"{person.content}\n\n_Updated: {person.updated_at}_\n")
        self._atomic_write(self._vault_path / "people.md", "\n".join(people_lines))

    def _atomic_write(self, path: Path, content: str) -> None:
        """Write content to path atomically: temp file in same dir, then os.rename()."""
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        try:
            tmp_path.write_text(content, encoding="utf-8")
            os.rename(tmp_path, path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
