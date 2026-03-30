"""Main event loop — ties iMessage, Claude, and memory together."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import signal
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from awfulclaw import claude, config, context, memory, scheduler
from awfulclaw.mcp.registry import MCPRegistry
from awfulclaw.db import get_db, init_db, write_fact, write_person
from awfulclaw.gateway import Gateway
from awfulclaw.modules import get_registry

logger = logging.getLogger(__name__)

_MEMORY_WRITE_RE = re.compile(
    r"<memory:write\s+path=\"([^\"]+)\">(.*?)</memory:write>",
    re.DOTALL,
)

_LOCATION_RE = re.compile(r"^\[Location:\s*(-?\d+\.?\d*),\s*(-?\d+\.?\d*)\]$")

_HEARTBEAT_PATH = "HEARTBEAT.md"
_DEFAULT_HEARTBEAT = (
    "You are running a silent background check. Review tasks and facts in your context.\n\n"
    "If something genuinely needs proactive attention or a follow-up message to the user, "
    "send it now.\n\n"
    "IMPORTANT: If nothing needs attention, you MUST reply with exactly: NOTHING"
)

_IDLE_SUPPRESS = {"nothing", "nothing.", "nothing needs attention", "nothing right now"}

_SLASH_COMMANDS = "/tasks, /skills, /schedules, /restart"


def handle_slash_command(body: str) -> str | None:
    """Return a response string for slash commands, or None if not a slash command."""
    cmd = body.strip().lower().split()[0] if body.strip().startswith("/") else None
    if cmd is None:
        return None

    if cmd == "/tasks":
        files = sorted((Path("memory") / "tasks").glob("*.md"))
        lines: list[str] = []
        for f in files:
            open_items = [
                line
                for line in f.read_text(encoding="utf-8").splitlines()
                if line.strip().startswith("- [ ]")
            ]
            if open_items:
                lines.append(f"**{f.stem}**")
                lines.extend(open_items)
        return "\n".join(lines) if lines else "No open tasks."

    if cmd == "/skills":
        files = sorted((Path("memory") / "skills").glob("*.md"))
        if not files:
            return "No skills saved."
        parts: list[str] = []
        for f in files:
            parts.append(f"**{f.stem}**\n{f.read_text(encoding='utf-8').strip()}")
        return "\n\n".join(parts)

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


_PROTECTED_FILES = {"SOUL.md", "HEARTBEAT.md"}
_PROTECTED_DIRS = ("skills/",)


def _is_protected_path(path: str) -> bool:
    if path in _PROTECTED_FILES:
        return True
    return any(path.startswith(d) for d in _PROTECTED_DIRS)


def _parse_and_apply_memory_writes(text: str) -> str:
    """Extract <memory:write> blocks, apply them, return cleaned text."""
    for path, content in _MEMORY_WRITE_RE.findall(text):
        path = path.strip()
        if path.startswith("memory/"):
            path = path[len("memory/") :]
        if _is_protected_path(path):
            logger.warning("Blocked write to protected path: %s", path)
            continue
        # Route facts/ and people/ writes to SQLite
        if path.startswith("facts/"):
            key = path[len("facts/"):].removesuffix(".md")
            write_fact(key, content.strip())
        elif path.startswith("people/"):
            name = path[len("people/"):].removesuffix(".md")
            write_person(name, content.strip())
        else:
            memory.write(path, content.strip())
        logger.info("Memory write: %s", path)
    return _MEMORY_WRITE_RE.sub("", text).strip()


async def _dispatch_tools(
    reply: str,
    history: list[dict[str, str]],
    system: str,
    sem: asyncio.Semaphore,
    ev_loop: asyncio.AbstractEventLoop,
    mcp_config_path: Path | None = None,
) -> str:
    """Process all tool tags in reply using pluggable ToolMatcher instances.

    Handles multiple tags by processing them one at a time, re-invoking
    Claude after each. Strips leftover malformed tags at the end.
    """
    registry = get_registry()
    matchers = registry.get_all_tool_matchers()
    for _round in range(5):  # max 5 dispatch rounds
        matched = False
        for matcher in matchers:
            m = matcher.match(reply)
            if m:
                reply = matcher.execute(m, reply, history, system)
                hist_snapshot = list(history)
                async with sem:
                    reply = await ev_loop.run_in_executor(
                        None,
                        lambda: claude.chat(hist_snapshot, system=system, mcp_config_path=mcp_config_path),
                    )
                reply = _parse_and_apply_memory_writes(reply)
                matched = True
                break  # restart matching from the top
        if not matched:
            break
    # Strip any leftover malformed skill tags
    for _, skill_tag in registry.get_all_skill_tags():
        reply = skill_tag.pattern.sub("", reply).strip()
    return reply


_MEMORY_ROOT = Path("memory")


def _sigterm_handler(signum: int, frame: object) -> None:
    raise SystemExit(0)


def _load_recent_history(max_turns: int = 20) -> list[dict[str, str]]:
    """Load the last *max_turns* turns from SQLite conversations table."""
    try:
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT role, content FROM conversations
                ORDER BY id DESC LIMIT ?
                """,
                (max_turns,),
            ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
    except Exception as exc:
        logger.warning("Could not load recent conversation history: %s", exc)
        return []


def _append_turn(session_id: str, role: str, content: str) -> None:
    """Insert a single conversation turn into SQLite."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO conversations"
                " (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                (session_id, role.lower(), content, ts),
            )
    except Exception as exc:
        logger.error("Failed to insert conversation turn: %s", exc)


async def run(gateway: Gateway) -> None:
    """Run the agent loop indefinitely until Ctrl-C."""
    signal.signal(signal.SIGTERM, _sigterm_handler)
    logger.info("awfulclaw starting up")

    init_db()
    registry = get_registry()

    mcp_registry = MCPRegistry()
    mcp_registry.register(
        "memory_write",
        "uv",
        ["run", "python", "-m", "awfulclaw.mcp.memory_write"],
    )
    mcp_registry.register(
        "web_search",
        "uv",
        ["run", "python", "-m", "awfulclaw.mcp.web"],
    )
    mcp_registry.register(
        "memory_search",
        "uv",
        ["run", "python", "-m", "awfulclaw.mcp.search"],
    )
    mcp_config_path = None if mcp_registry.is_empty() else mcp_registry.generate_config()

    poll_interval = config.get_poll_interval()
    idle_interval = config.get_idle_interval()
    phone = gateway.primary_recipient

    conversation_history: list[dict[str, str]] = _load_recent_history()
    if conversation_history:
        logger.info("Restored %d turns from previous session", len(conversation_history))
    last_idle = time.monotonic()
    briefing_module = registry.get("briefing")

    session_id = str(uuid.uuid4())
    _max_concurrent = int(os.getenv("AWFULCLAW_MAX_CONCURRENT", "3"))
    _sem = asyncio.Semaphore(_max_concurrent)
    _history_lock = asyncio.Lock()
    ev_loop = asyncio.get_running_loop()

    gateway.start()

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
                lambda: claude.chat(msgs, system, image_data, image_mime, mcp_config_path),
            )

    # Startup self-briefing (silent — no Telegram output)
    startup_module = registry.get("startup_briefing")
    if startup_module is not None:
        from awfulclaw.modules.startup_briefing._startup_briefing import (
            StartupBriefingModule as _SBM,
        )

        if isinstance(startup_module, _SBM):
            try:
                startup_prompt = startup_module.get_startup_prompt()
                startup_system = context.build_system_prompt(startup_prompt)
                startup_history = list(conversation_history)
                startup_history.append({"role": "user", "content": startup_prompt})
                startup_reply = await _chat_async(startup_history, startup_system)
                _parse_and_apply_memory_writes(startup_reply)
                logger.info("Startup self-briefing completed")
            except Exception as exc:
                logger.error("Startup self-briefing failed: %s", exc)

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

            async with _history_lock:
                conversation_history.append({"role": "user", "content": msg.body})
                reply = await _chat_async(
                    conversation_history,
                    system,
                    msg.image_data,
                    msg.image_mime,
                )
                reply = _parse_and_apply_memory_writes(reply)
                reply = await _dispatch_tools(
                    reply, conversation_history, system, _sem, ev_loop, mcp_config_path
                )
                conversation_history.append({"role": "assistant", "content": reply})
                _MAX_HISTORY = 40
                if len(conversation_history) > _MAX_HISTORY:
                    conversation_history[:] = conversation_history[-_MAX_HISTORY:]

            _append_turn(session_id, "user", msg.body)
            _append_turn(session_id, "assistant", reply)
            if reply:
                recipient = gateway.primary_recipient_for(msg.channel)
                gateway.send(msg.channel, recipient, reply)
                logger.info("Sent reply: %s", reply[:80])

    async def _run_idle_tick() -> None:
        """Run scheduled prompts, briefing, and heartbeat check."""
        if registry.check_for_changes():
            logger.info("Modules hot-reloaded")

        schedule_module = registry.get("schedule")
        if schedule_module is not None:
            from awfulclaw.modules.schedule._schedule import ScheduleModule as _SM

            if isinstance(schedule_module, _SM):
                due_prompts = schedule_module.run_due()
                for prompt in due_prompts:
                    try:
                        sched_system = context.build_system_prompt(prompt)
                        sched_history: list[dict[str, str]] = [
                            {"role": "user", "content": prompt}
                        ]
                        sched_reply = await _chat_async(sched_history, sched_system)
                        sched_reply = _parse_and_apply_memory_writes(sched_reply)
                        sched_reply = await _dispatch_tools(
                            sched_reply, sched_history, sched_system, _sem, ev_loop, mcp_config_path
                        )
                        if sched_reply:
                            gateway.send(gateway.primary_channel, phone, sched_reply)
                            logger.info("Schedule reply sent: %s", sched_reply[:80])
                    except Exception as exc:
                        logger.error("Schedule prompt failed: %s", exc)

        if briefing_module is not None:
            from awfulclaw.modules.briefing._briefing import BriefingModule as _BM

            if isinstance(briefing_module, _BM):
                briefing_prompt = briefing_module.check_and_fire(poll_interval)
                if briefing_prompt is not None:
                    try:
                        briefing_system = context.build_system_prompt(briefing_prompt)
                        briefing_history: list[dict[str, str]] = [
                            {"role": "user", "content": briefing_prompt}
                        ]
                        briefing_reply = await _chat_async(briefing_history, briefing_system)
                        briefing_reply = _parse_and_apply_memory_writes(briefing_reply)
                        briefing_reply = await _dispatch_tools(
                            briefing_reply, briefing_history, briefing_system, _sem, ev_loop, mcp_config_path
                        )
                        if briefing_reply:
                            gateway.send(gateway.primary_channel, phone, briefing_reply)
                            logger.info("Daily briefing sent: %s", briefing_reply[:80])
                    except Exception as exc:
                        logger.error("Daily briefing failed: %s", exc)

        system = context.build_system_prompt("")
        idle_reply = await _chat_async(
            [{"role": "user", "content": _load_heartbeat()}],
            system,
        )
        idle_reply = _parse_and_apply_memory_writes(idle_reply)
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
