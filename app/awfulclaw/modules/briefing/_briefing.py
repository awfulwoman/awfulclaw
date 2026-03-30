"""Daily briefing module implementation."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from awfulclaw import config
from awfulclaw.modules.base import Module

logger = logging.getLogger(__name__)

_BRIEFING_PROMPT = (
    "Good morning! Please give me a concise daily briefing. Include:\n"
    "1. Any open tasks from memory/tasks/\n"
    "2. Schedules due today or this week\n"
    "3. Anything flagged or important in memory/facts/\n"
    "4. If IMAP is configured, check for new emails\n\n"
    "Keep it brief and actionable."
)


class BriefingModule(Module):
    def __init__(self) -> None:
        self._last_briefing_date: date | None = None

    @property
    def name(self) -> str:
        return "briefing"

    def is_available(self) -> bool:
        return config.get_briefing_time() is not None

    def check_and_fire(self, poll_interval: int) -> str | None:
        """Return the briefing prompt if it's time to fire, None otherwise.

        Should be called on each idle tick. The caller handles Claude
        invocation and message sending.
        """
        briefing_time = config.get_briefing_time()
        if briefing_time is None:
            return None

        now = datetime.now(timezone.utc)
        today = now.date()

        if self._last_briefing_date == today:
            return None

        delta_secs = (
            now.hour * 3600
            + now.minute * 60
            + now.second
            - briefing_time.hour * 3600
            - briefing_time.minute * 60
        )

        if 0 <= delta_secs < poll_interval:
            self._last_briefing_date = today
            return _BRIEFING_PROMPT

        return None
