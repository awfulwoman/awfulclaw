"""Main event loop — ties iMessage, Claude, and memory together."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import signal
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from awfulclaw_mcp.registry import MCPRegistry

from awfulclaw import briefings, claude, config, context, memory, scheduler
from awfulclaw.db import init_db, write_fact
from awfulclaw.gateway import Gateway

logger = logging.getLogger(__name__)

_LOCATION_RE = re.compile(r"^\[Location:\s*(-?\d+\.?\d*),\s*(-?\d+\.?\d*)\]$")

_HEARTBEAT_PATH = "HEARTBEAT.md"
_DEFAULT_HEARTBEAT = (
    "You are running a silent background check. Review tasks and facts in your context.\n\n"
    "If something genuinely needs proactive attention or a follow-up message to the user, "
    "send it now.\n\n"
    "IMPORTANT: If nothing needs attention, you MUST reply with exactly: NOTHING"
)

_IDLE_SUPPRESS = {"nothing", "nothing.", "nothing needs attention", "nothing right now"}

_SLASH_COMMANDS = "/schedules, /restart"


def handle_slash_command(body: str) -> str | None:
    """Return a response string for slash commands, or None if not a slash command."""
    cmd = body.strip().lower().split()[0] if body.strip().startswith("/") else None
    if cmd is None:
        return None

    if cmd == "/schedules":
        schedules = scheduler.load_schedules()
        if not schedules:
            return "No schedules."
        parts2: list[str] = []
        for s in schedules:
            when = s.fire_at.isoformat() if s.fire_at else s.cron
            preview = s.prompt[:60] + ("…" if len(s.prompt) > 60 else "")
            parts2.append(f"**{s.name}** ({when}): {preview}")
        return "\n".join(parts2)

    if cmd == "/restart":
        import subprocess as _sp

        _sp.Popen(["bash", str(Path("scripts/restart-service.sh").resolve())])
        return "Restarting…"

    return f"Unknown command: {cmd}\nAvailable: {_SLASH_COMMANDS}"


def _is_idle_suppressed(text: str) -> bool:
    return text.lower().strip().rstrip(".").strip() in _IDLE_SUPPRESS or text.upper() == "NOTHING"


def _load_heartbeat() -> str:
    content = memory.read(_HEARTBEAT_PATH)
    if not content:
        memory.write(_HEARTBEAT_PATH, _DEFAULT_HEARTBEAT)
        return _DEFAULT_HEARTBEAT
    return content


_MEMORY_ROOT = Path("memory")
_CONVERSATIONS_DIR = _MEMORY_ROOT / "conversations"


def _sigterm_handler(signum: int, frame: object) -> None:
    raise SystemExit(0)


def _conv_path(dt: datetime) -> Path:
    return _CONVERSATIONS_DIR / f"{dt.strftime('%Y-%m-%d')}.md"


def _parse_conv_file(path: Path) -> list[dict[str, str]]:
    """Parse a daily conversation markdown file into turn dicts."""
    turns: list[dict[str, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return turns
    # Split on section headers: ## HH:MM:SS — role
    parts = re.split(r"^## \d{2}:\d{2}:\d{2} — (\w+)\s*$", text, flags=re.MULTILINE)
    # parts[0] is pre-header text (ignored), then alternating role/content
    i = 1
    while i + 1 < len(parts):
        role = parts[i].strip().lower()
        content = parts[i + 1].strip()
        if role in ("user", "assistant") and content:
            turns.append({"role": role, "content": content})
        i += 2
    return turns


def _load_recent_history(max_turns: int = 20) -> list[dict[str, str]]:
    """Load the last *max_turns* turns from daily conversation markdown files."""
    turns: list[dict[str, str]] = []
    now = datetime.now(timezone.utc)
    for days_back in range(7):
        dt = now - timedelta(days=days_back)
        path = _conv_path(dt)
        if path.exists():
            turns = _parse_conv_file(path) + turns
            if len(turns) >= max_turns:
                break
    return turns[-max_turns:]


def _append_turn(role: str, content: str) -> None:
    """Append a single conversation turn to today's markdown file."""
    now = datetime.now(timezone.utc)
    path = _conv_path(now)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        ts = now.strftime("%H:%M:%S")
        with path.open("a", encoding="utf-8") as f:
            f.write(f"## {ts} — {role}\n\n{content}\n\n")
    except OSError as exc:
        logger.error("Failed to append conversation turn: %s", exc)


async def run(gateway: Gateway) -> None:
    """Run the agent loop indefinitely until Ctrl-C."""
    signal.signal(signal.SIGTERM, _sigterm_handler)
    logger.info("awfulclaw starting up")

    init_db()

    briefing_time = config.get_briefing_time()
    if briefing_time is not None:
        briefings.ensure_daily_briefing(briefing_time)

    _MCP_CONFIG_PATH = Path("config/mcp_servers.json")
    mcp_registry = MCPRegistry()
    mcp_registry.load_from_config(_MCP_CONFIG_PATH)
    _mcp_config: list[Path | None] = [
        None if mcp_registry.is_empty() else mcp_registry.generate_config()
    ]

    poll_interval = config.get_poll_interval()
    idle_interval = config.get_idle_interval()
    phone = gateway.primary_recipient

    conversation_history: list[dict[str, str]] = _load_recent_history()
    if conversation_history:
        logger.info("Restored %d turns from previous session", len(conversation_history))
    last_idle = time.monotonic()

    _max_concurrent = int(os.getenv("AWFULCLAW_MAX_CONCURRENT", "3"))
    _sem = asyncio.Semaphore(_max_concurrent)
    _history_lock = asyncio.Lock()
    ev_loop = asyncio.get_running_loop()

    gateway.start()

    # Run startup briefing synchronously before entering the loop
    try:
        startup_prompt = briefings.get_startup_prompt()
        startup_system = context.build_system_prompt(startup_prompt)
        startup_reply = await ev_loop.run_in_executor(
            None,
            lambda: claude.chat([{"role": "user", "content": startup_prompt}], startup_system, None, None, _mcp_config[0]),
        )
        logger.info("Startup self-briefing completed")
        if startup_reply:
            _append_turn("user", startup_prompt)
            _append_turn("assistant", startup_reply)
    except Exception as exc:
        logger.warning("Startup self-briefing failed: %s", exc)

    async def _chat_async(
        messages: list[dict[str, str]],
        system: str,
        image_data: bytes | None = None,
        image_mime: str | None = None,
    ) -> str:
        """Run claude.chat in a thread executor, bounded by the concurrency semaphore."""
        msgs = list(messages)
        async with _sem:
            return await ev_loop.run_in_executor(
                None,
                lambda: claude.chat(msgs, system, image_data, image_mime, _mcp_config[0]),
            )

    async def _handle_messages(messages: list) -> None:  # type: ignore[type-arg]
        """Process a batch of user messages sequentially, in order."""
        for msg in messages:
            logger.info("Incoming from %s: %s", msg.sender, msg.body[:80])

            loc_match = _LOCATION_RE.match(msg.body)
            if loc_match:
                lat, lon = loc_match.group(1), loc_match.group(2)
                ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                write_fact("location", f"Last known location: {lat}, {lon}\nUpdated: {ts}")
                logger.info("Location saved: %s, %s", lat, lon)
                continue

            slash_reply = handle_slash_command(msg.body)
            if slash_reply is not None:
                recipient = gateway.primary_recipient_for(msg.channel)
                gateway.send(msg.channel, recipient, slash_reply)
                logger.info("Slash command '%s' handled", msg.body.split()[0])
                continue

            system = context.build_system_prompt(msg.body, sender=msg.sender)

            recipient = gateway.primary_recipient_for(msg.channel)
            gateway.send_typing(msg.channel, recipient)

            async with _history_lock:
                conversation_history.append({"role": "user", "content": msg.body})
                reply = await _chat_async(
                    conversation_history,
                    system,
                    msg.image_data,
                    msg.image_mime,
                )
                conversation_history.append({"role": "assistant", "content": reply})
                _MAX_HISTORY = 40
                if len(conversation_history) > _MAX_HISTORY:
                    conversation_history[:] = conversation_history[-_MAX_HISTORY:]

            _append_turn("user", msg.body)
            _append_turn("assistant", reply)
            if reply:
                gateway.send(msg.channel, recipient, reply)
                logger.info("Sent reply: %s", reply[:80])

    async def _run_idle_tick() -> None:
        """Run scheduled prompts and heartbeat check."""
        if mcp_registry.reload_if_changed(_MCP_CONFIG_PATH):
            _mcp_config[0] = None if mcp_registry.is_empty() else mcp_registry.generate_config()

        due_schedules = scheduler.run_due()
        for sched in due_schedules:
            try:
                sched_system = context.build_system_prompt(sched.prompt)
                sched_history: list[dict[str, str]] = [{"role": "user", "content": sched.prompt}]
                sched_reply = await _chat_async(sched_history, sched_system)
                if sched_reply and not sched.silent:
                    gateway.send(gateway.primary_channel, phone, sched_reply)
                    logger.info("Schedule reply sent: %s", sched_reply[:80])
                elif sched_reply and sched.silent:
                    logger.info("Silent schedule '%s' completed", sched.name)
            except Exception as exc:
                logger.error("Schedule prompt failed: %s", exc)

        system = context.build_system_prompt("")
        idle_reply = await _chat_async(
            [{"role": "user", "content": _load_heartbeat()}],
            system,
        )
        if idle_reply and not _is_idle_suppressed(idle_reply):
            gateway.send(gateway.primary_channel, phone, idle_reply)
            logger.info("Idle message sent: %s", idle_reply[:80])

    try:
        while True:
            messages = gateway.get_messages()

            coroutines = []
            if messages:
                coroutines.append(_handle_messages(messages))

            if time.monotonic() - last_idle >= idle_interval:
                last_idle = time.monotonic()
                coroutines.append(_run_idle_tick())

            if coroutines:
                await asyncio.gather(*coroutines)

            await asyncio.sleep(poll_interval)

    except (KeyboardInterrupt, SystemExit):
        gateway.stop()
        logger.info("awfulclaw exiting — goodbye")
