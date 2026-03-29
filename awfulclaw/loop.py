"""Main event loop — ties iMessage, Claude, and memory together."""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone

from awfulclaw import claude, config, context, imessage, memory

logger = logging.getLogger(__name__)

_MEMORY_WRITE_RE = re.compile(
    r"<memory:write\s+path=\"([^\"]+)\">(.*?)</memory:write>",
    re.DOTALL,
)

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


def run() -> None:
    """Run the agent loop indefinitely until Ctrl-C."""
    logger.info("awfulclaw starting up")

    poll_interval = config.get_poll_interval()
    idle_interval = config.get_idle_interval()
    phone = config.get_phone()

    conversation_history: list[dict[str, str]] = []
    last_poll = datetime.now(timezone.utc)
    last_idle = time.monotonic()

    try:
        while True:
            now = datetime.now(timezone.utc)
            messages = imessage.poll_new_messages(since=last_poll)
            last_poll = now

            for msg in messages:
                logger.info("Incoming from %s: %s", msg.sender, msg.body[:80])
                system = context.build_system_prompt(msg.body, sender=msg.sender)
                conversation_history.append({"role": "user", "content": msg.body})
                reply = claude.chat(conversation_history, system=system)
                reply = _parse_and_apply_memory_writes(reply)
                conversation_history.append({"role": "assistant", "content": reply})
                if reply:
                    imessage.send_message(phone, reply)
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
                    imessage.send_message(phone, idle_reply)
                    logger.info("Idle message sent: %s", idle_reply[:80])

            time.sleep(poll_interval)

    except KeyboardInterrupt:
        logger.info("awfulclaw exiting — goodbye")
