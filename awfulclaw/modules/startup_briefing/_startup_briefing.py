"""Startup self-briefing module implementation."""

from __future__ import annotations

import re

from awfulclaw import memory
from awfulclaw.modules.base import Module, SkillTag

_PROGRESS_PATH = "progress.md"

_STARTUP_PROMPT = (
    "You have just restarted. Before resuming normal operation, orient yourself.\n\n"
    "{previous_progress}"
    "Review the conversation history, open tasks, facts, and schedules in your system "
    "context. Then write a concise progress note summarising:\n"
    "1. What you were last working on or discussing\n"
    "2. Any pending tasks or follow-ups\n"
    "3. Current state of affairs\n\n"
    "Write this note using:\n"
    '<memory:write path="progress.md">your note here</memory:write>\n\n'
    "IMPORTANT: Do NOT send a message to the user. This is a silent internal review. "
    "Your entire reply must consist of only the <memory:write> tag."
)


class StartupBriefingModule(Module):
    @property
    def name(self) -> str:
        return "startup_briefing"

    @property
    def skill_tags(self) -> list[SkillTag]:
        return []

    @property
    def system_prompt_fragment(self) -> str:
        return (
            "### Startup Self-Briefing\n"
            "On each restart a silent self-briefing runs automatically. "
            "A progress note is maintained at memory/progress.md."
        )

    def dispatch(
        self, tag_match: re.Match[str], history: list[dict[str, str]], system: str
    ) -> str:
        return ""

    def is_available(self) -> bool:
        return True

    def get_startup_prompt(self) -> str:
        """Return the startup briefing prompt, including any existing progress note."""
        existing = memory.read(_PROGRESS_PATH)
        if existing:
            previous = (
                "Your previous progress note (from before this restart):\n"
                f"{existing}\n\n"
            )
        else:
            previous = ""
        return _STARTUP_PROMPT.format(previous_progress=previous)
