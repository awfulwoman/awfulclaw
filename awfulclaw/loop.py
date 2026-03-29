"""Main event loop — ties iMessage, Claude, and memory together."""

from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime, timezone

from awfulclaw import claude, config, context, memory
from awfulclaw.connector import Connector

logger = logging.getLogger(__name__)

_MEMORY_WRITE_RE = re.compile(
    r"<memory:write\s+path=\"([^\"]+)\">(.*?)</memory:write>",
    re.DOTALL,
)

_SKILL_IMAP_RE = re.compile(r"<skill:imap\s*/>|<skill:imap\s*></skill:imap>")

_imap_configured = bool(
    os.getenv("IMAP_HOST") and os.getenv("IMAP_USER") and os.getenv("IMAP_PASSWORD")
)
if not _imap_configured:
    logger.warning("IMAP not configured — <skill:imap/> will be unavailable")

_IDLE_PROMPT = (
    "You are running an idle check. Review the tasks and facts in your context. "
    "If something needs proactive attention or a follow-up, send a brief message. "
    "If nothing needs attention right now, reply with an empty string."
)


def _parse_and_apply_memory_writes(text: str) -> str:
    """Extract <memory:write> blocks, apply them, return cleaned text."""
    for path, content in _MEMORY_WRITE_RE.findall(text):
        memory.write(path.strip(), content.strip())
        logger.info("Memory write: %s", path.strip())
    return _MEMORY_WRITE_RE.sub("", text).strip()


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
    phone = config.get_phone()

    conversation_history: list[dict[str, str]] = []
    last_poll = datetime.now(timezone.utc)
    last_idle = time.monotonic()
    last_imap_check: datetime | None = None

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
                system = context.build_system_prompt("")
                idle_reply = claude.chat(
                    [{"role": "user", "content": _IDLE_PROMPT}],
                    system=system,
                )
                idle_reply = _parse_and_apply_memory_writes(idle_reply)
                if idle_reply:
                    connector.send_message(phone, idle_reply)
                    logger.info("Idle message sent: %s", idle_reply[:80])

            time.sleep(poll_interval)

    except KeyboardInterrupt:
        logger.info("awfulclaw exiting — goodbye")
