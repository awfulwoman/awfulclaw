"""Briefing prompts and schedule setup."""

from __future__ import annotations

from datetime import time

BRIEFING_PROMPT = (
    "Good morning! Please give me a concise daily briefing. Include:\n"
    "1. Any open tasks from memory\n"
    "2. Schedules due today or this week\n"
    "3. Anything flagged or important in stored facts\n"
    "4. If IMAP is configured, check for new emails\n\n"
    "Keep it brief and actionable."
)

_STARTUP_TEMPLATE = (
    "You have just restarted. Before resuming normal operation, orient yourself.\n\n"
    "{previous_progress}"
    "Review the conversation history, open tasks, facts, and schedules in your system "
    "context. Then write a concise progress note summarising:\n"
    "1. What you were last working on or discussing\n"
    "2. Any pending tasks or follow-ups\n"
    "3. Current state of affairs\n\n"
    "Write this note by calling the memory_write tool with path='progress.md'. "
    "Do not output any other text — just make the tool call."
)


def get_startup_prompt() -> str:
    """Return the startup prompt, embedding any existing progress note."""
    from awfulclaw import memory

    existing = memory.read("progress.md")
    if existing:
        previous = (
            "Your previous progress note (from before this restart):\n"
            f"{existing}\n\n"
        )
    else:
        previous = ""
    return _STARTUP_TEMPLATE.format(previous_progress=previous)


def ensure_daily_briefing(briefing_time: time) -> None:
    """Create a daily_briefing cron schedule if none already exists."""
    from awfulclaw.scheduler import Schedule, load_schedules, save_schedules

    schedules = load_schedules()
    if any(s.name == "daily_briefing" for s in schedules):
        return
    cron = f"{briefing_time.minute} {briefing_time.hour} * * *"
    s = Schedule.create(name="daily_briefing", cron=cron, prompt=BRIEFING_PROMPT)
    save_schedules(schedules + [s])
