"""Main event loop — ties iMessage, Claude, and memory together."""

from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime, timezone

from croniter import croniter  # type: ignore[import-untyped]

from awfulclaw import claude, config, context, memory, scheduler
from awfulclaw.connector import Connector

logger = logging.getLogger(__name__)

_MEMORY_WRITE_RE = re.compile(
    r"<memory:write\s+path=\"([^\"]+)\">(.*?)</memory:write>",
    re.DOTALL,
)

_SKILL_IMAP_RE = re.compile(r"<skill:imap\s*/>|<skill:imap\s*></skill:imap>")

_SKILL_SCHEDULE_RE = re.compile(
    r"<skill:schedule\s+([^>]*?)(?:/>|>(.*?)</skill:schedule>)",
    re.DOTALL,
)
_ATTR_RE = re.compile(r'(\w+)="([^"]*)"')

_imap_configured = bool(
    os.getenv("IMAP_HOST") and os.getenv("IMAP_USER") and os.getenv("IMAP_PASSWORD")
)
if not _imap_configured:
    logger.warning("IMAP not configured — <skill:imap/> will be unavailable")

_IDLE_PROMPT = (
    "You are running a silent background check. Review tasks and facts in your context. "
    "If something genuinely needs proactive attention or a follow-up message to the user, "
    "send it now. "
    "IMPORTANT: If nothing needs attention, you MUST reply with exactly the text: NOTHING. "
    "Do not explain, do not say 'nothing needs attention', just reply: NOTHING."
)

_IDLE_SUPPRESS = {"nothing", "nothing.", "nothing needs attention", "nothing right now"}


def _is_idle_suppressed(text: str) -> bool:
    return text.lower().strip().rstrip(".").strip() in _IDLE_SUPPRESS or text.upper() == "NOTHING"


def _parse_and_apply_memory_writes(text: str) -> str:
    """Extract <memory:write> blocks, apply them, return cleaned text."""
    for path, content in _MEMORY_WRITE_RE.findall(text):
        memory.write(path.strip(), content.strip())
        logger.info("Memory write: %s", path.strip())
    return _MEMORY_WRITE_RE.sub("", text).strip()


def _parse_and_apply_schedule_tags(
    text: str, schedules: list[scheduler.Schedule]
) -> tuple[str, list[str]]:
    """Extract <skill:schedule> tags, apply create/delete, return (cleaned text, error notes)."""
    errors: list[str] = []

    def handle_match(m: re.Match[str]) -> str:
        attrs_str = m.group(1) or ""
        body = (m.group(2) or "").strip()
        attrs = dict(_ATTR_RE.findall(attrs_str))
        action = attrs.get("action", "")
        name = attrs.get("name", "").strip()
        cron = attrs.get("cron", "").strip()

        if action == "create":
            if not croniter.is_valid(cron):
                errors.append(f"Invalid cron expression '{cron}' for schedule '{name}'.")
                return ""
            # Overwrite existing schedule with same name (case-insensitive)
            idx = next(
                (i for i, s in enumerate(schedules) if s.name.lower() == name.lower()),
                None,
            )
            new_sched = scheduler.Schedule.create(name=name, cron=cron, prompt=body)
            if idx is not None:
                schedules[idx] = new_sched
                logger.info("Schedule updated: '%s' (%s)", name, cron)
            else:
                schedules.append(new_sched)
                logger.info("Schedule created: '%s' (%s)", name, cron)
            scheduler.save_schedules(schedules)
        elif action == "delete":
            before = len(schedules)
            schedules[:] = [s for s in schedules if s.name.lower() != name.lower()]
            if len(schedules) < before:
                scheduler.save_schedules(schedules)
                logger.info("Schedule deleted: '%s'", name)
            else:
                logger.warning("Schedule delete: '%s' not found", name)
        return ""

    cleaned = _SKILL_SCHEDULE_RE.sub(handle_match, text).strip()
    return cleaned, errors


def _fetch_imap_results(last_imap_check: datetime | None) -> tuple[str, datetime]:
    """Run the IMAP skill, return (formatted result text, new last_check timestamp)."""
    now = datetime.now(timezone.utc)
    try:
        from awfulclaw.imap import fetch_unread

        emails = fetch_unread(since=last_imap_check)
        if not emails:
            result = "[No new emails]"
        else:
            lines = [f"[{len(emails)} new email(s):]"]
            for e in emails:
                lines.append(
                    f"From: {e.from_addr}\nSubject: {e.subject}\n"
                    f"Date: {e.timestamp.isoformat()}\n{e.body_preview}"
                )
            result = "\n\n".join(lines)
        logger.info("IMAP skill: fetched %d email(s)", len(emails) if emails else 0)
    except Exception as exc:
        result = f"[IMAP unavailable: {exc}]"
        logger.warning("IMAP skill error: %s", exc)
    return result, now


def run(connector: Connector) -> None:
    """Run the agent loop indefinitely until Ctrl-C."""
    logger.info("awfulclaw starting up")

    poll_interval = config.get_poll_interval()
    idle_interval = config.get_idle_interval()
    phone = connector.primary_recipient

    conversation_history: list[dict[str, str]] = []
    last_poll = datetime.now(timezone.utc)
    last_idle = time.monotonic()
    last_imap_check: datetime | None = None
    schedules = scheduler.load_schedules()

    try:
        connector.send_message(phone, "awfulclaw is online.")
    except Exception as exc:
        logger.warning("Failed to send startup notification: %s", exc)

    try:
        while True:
            now = datetime.now(timezone.utc)
            messages = connector.poll_new_messages(since=last_poll)
            last_poll = now

            for msg in messages:
                logger.info("Incoming from %s: %s", msg.sender, msg.body[:80])
                system = context.build_system_prompt(msg.body, sender=msg.sender)
                conversation_history.append({"role": "user", "content": msg.body})
                reply = claude.chat(conversation_history, system=system)
                reply = _parse_and_apply_memory_writes(reply)

                reply, sched_errors = _parse_and_apply_schedule_tags(reply, schedules)
                if sched_errors:
                    error_note = "[Schedule error: " + "; ".join(sched_errors) + "]"
                    conversation_history.append({"role": "assistant", "content": reply})
                    conversation_history.append({"role": "user", "content": error_note})
                    reply = claude.chat(conversation_history, system=system)
                    reply = _parse_and_apply_memory_writes(reply)
                    reply, _ = _parse_and_apply_schedule_tags(reply, schedules)

                if _SKILL_IMAP_RE.search(reply):
                    reply = _SKILL_IMAP_RE.sub("", reply).strip()
                    imap_text, last_imap_check = _fetch_imap_results(last_imap_check)
                    conversation_history.append({"role": "assistant", "content": reply})
                    conversation_history.append({"role": "user", "content": imap_text})
                    reply = claude.chat(conversation_history, system=system)
                    reply = _parse_and_apply_memory_writes(reply)

                conversation_history.append({"role": "assistant", "content": reply})
                if reply:
                    connector.send_message(phone, reply)
                    logger.info("Sent reply: %s", reply[:80])

            if time.monotonic() - last_idle >= idle_interval:
                last_idle = time.monotonic()
                now = datetime.now(timezone.utc)

                due = scheduler.get_due(schedules, now)
                for sched in due:
                    try:
                        sched_system = context.build_system_prompt(sched.prompt)
                        sched_reply = claude.chat(
                            [{"role": "user", "content": sched.prompt}],
                            system=sched_system,
                        )
                        sched_reply = _parse_and_apply_memory_writes(sched_reply)
                        if sched_reply:
                            connector.send_message(phone, sched_reply)
                            logger.info("Schedule '%s' sent: %s", sched.name, sched_reply[:80])
                        sched.last_run = now
                    except Exception as exc:
                        logger.error("Schedule '%s' failed: %s", sched.name, exc)
                if due:
                    scheduler.save_schedules(schedules)

                system = context.build_system_prompt("")
                idle_reply = claude.chat(
                    [{"role": "user", "content": _IDLE_PROMPT}],
                    system=system,
                )
                idle_reply = _parse_and_apply_memory_writes(idle_reply)
                if idle_reply and not _is_idle_suppressed(idle_reply):
                    connector.send_message(phone, idle_reply)
                    logger.info("Idle message sent: %s", idle_reply[:80])

            time.sleep(poll_interval)

    except KeyboardInterrupt:
        try:
            connector.send_message(phone, "awfulclaw is going offline.")
        except Exception as exc:
            logger.warning("Failed to send shutdown notification: %s", exc)
        logger.info("awfulclaw exiting — goodbye")
