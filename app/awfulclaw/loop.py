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

from awfulclaw import briefings, claude, config, context, env_utils, memory, scheduler
from awfulclaw.db import init_db, write_fact
from awfulclaw.gateway import Gateway

logger = logging.getLogger(__name__)

_LOCATION_RE = re.compile(r"^\[Location:\s*(-?\d+\.?\d*),\s*(-?\d+\.?\d*)\]$")
_SECRET_REQUEST_RE = re.compile(r'<secret:request\s+key="([A-Z][A-Z0-9_]*)"\s*/?>')

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

        _RESTART_FLAG.touch()
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


def _load_last_email_check() -> datetime:
    """Return the timestamp of the last email check, initialising to now on first call."""
    try:
        return datetime.fromisoformat(_IMAP_LAST_CHECK_PATH.read_text().strip())
    except Exception:
        ts = datetime.now(timezone.utc)
        _save_last_email_check(ts)
        return ts


def _save_last_email_check(ts: datetime) -> None:
    try:
        _IMAP_LAST_CHECK_PATH.write_text(ts.isoformat())
    except OSError as exc:
        logger.warning("Failed to save IMAP last check time: %s", exc)


_EMAIL_TRIAGE_PROMPT = (
    "New email(s) have arrived:\n\n{emails}\n\n"
    "Decide whether any are important or time-sensitive enough to alert the user. "
    "If yes, send a brief notification. If nothing needs immediate attention, reply NOTHING."
)


_MEMORY_ROOT = Path("memory")
_CONVERSATIONS_DIR = _MEMORY_ROOT / "conversations"
_RESTART_FLAG = _MEMORY_ROOT / ".restart_requested"
_IMAP_LAST_CHECK_PATH = _MEMORY_ROOT / ".imap_last_check"


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

    owntracks_url = config.get_owntracks_url()
    owntracks_user = config.get_owntracks_user()
    owntracks_device = config.get_owntracks_device()
    if owntracks_url:
        from awfulclaw.location import check_and_update_location, check_and_update_timezone

        check_and_update_timezone(owntracks_url, owntracks_user, owntracks_device)
        check_and_update_location(owntracks_url, owntracks_user, owntracks_device)

    briefing_time = config.get_briefing_time()
    if briefing_time is not None:
        briefings.ensure_daily_briefing(briefing_time)

    _MCP_CONFIG_PATH = Path("config/mcp_servers.json")
    mcp_registry = MCPRegistry()
    mcp_registry.load_from_config(_MCP_CONFIG_PATH)
    _mcp_config: list[Path | None] = [
        None if mcp_registry.is_empty() else mcp_registry.generate_config()
    ]
    _skipped_mcp: list[dict[str, list[str]]] = [mcp_registry.skipped_servers()]

    poll_interval = config.get_poll_interval()
    idle_interval = config.get_idle_interval()
    idle_nudge_cooldown = config.get_idle_nudge_cooldown()
    email_check_interval = config.get_email_check_interval()
    phone = gateway.primary_recipient

    conversation_history: list[dict[str, str]] = _load_recent_history()
    if conversation_history:
        logger.info("Restored %d turns from previous session", len(conversation_history))
    last_idle = time.monotonic()
    last_idle_nudge: float = 0.0
    last_email_check: float = 0.0

    _max_concurrent = int(os.getenv("AWFULCLAW_MAX_CONCURRENT", "3"))
    _sem = asyncio.Semaphore(_max_concurrent)
    _history_lock = asyncio.Lock()
    _pending_secret_key: list[str | None] = [None]
    ev_loop = asyncio.get_running_loop()

    gateway.start()

    # Notify user if this startup was triggered by a /restart command.
    if _RESTART_FLAG.exists():
        _RESTART_FLAG.unlink()
        gateway.send(gateway.primary_channel, phone, "Restarted successfully.")
        logger.info("Sent restart notification")

    # Run startup briefing synchronously before entering the loop
    try:
        startup_prompt = briefings.get_startup_prompt()
        startup_system = context.build_system_prompt(startup_prompt, skipped_mcp_servers=_skipped_mcp[0])
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

    async def _chat_with_typing(
        channel: str,
        recipient: str,
        messages: list[dict[str, str]],
        system: str,
        image_data: bytes | None = None,
        image_mime: str | None = None,
    ) -> str:
        """Run _chat_async while sending periodic typing indicators every 4s."""
        async def _keep_typing() -> None:
            while True:
                gateway.send_typing(channel, recipient)
                await asyncio.sleep(4)

        typing_task = asyncio.create_task(_keep_typing())
        try:
            return await _chat_async(messages, system, image_data, image_mime)
        finally:
            typing_task.cancel()

    async def _handle_messages(messages: list) -> None:  # type: ignore[type-arg]
        """Process a batch of user messages sequentially, in order."""
        _MAX_HISTORY = 40

        for msg in messages:
            recipient = gateway.primary_recipient_for(msg.channel)

            # Secret interception: if agent asked for a secret last turn, this
            # message is the value. Write it directly to .env and never log it.
            if _pending_secret_key[0] is not None:
                key = _pending_secret_key[0]
                _pending_secret_key[0] = None
                logger.info("Storing secret for key %s (value redacted)", key)
                try:
                    env_utils.set_env_var(key, msg.body.strip())
                    confirmation = f"[Secret received and stored to .env as {key}. Restart required to take effect.]"
                except ValueError as exc:
                    confirmation = f"[Secret storage failed for {key}: {exc}]"
                system = context.build_system_prompt(confirmation, sender=msg.sender, skipped_mcp_servers=_skipped_mcp[0])
                async with _history_lock:
                    conversation_history.append({"role": "user", "content": confirmation})
                    reply = await _chat_with_typing(msg.channel, recipient, conversation_history, system)
                    conversation_history.append({"role": "assistant", "content": reply})
                    if len(conversation_history) > _MAX_HISTORY:
                        conversation_history[:] = conversation_history[-_MAX_HISTORY:]
                _append_turn("user", f"[REDACTED — secret stored as {key}]")
                _append_turn("assistant", reply)
                if reply:
                    gateway.send(msg.channel, recipient, reply)
                    logger.info("Sent reply after secret storage: %s", reply[:80])
                continue

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
                gateway.send(msg.channel, recipient, slash_reply)
                logger.info("Slash command '%s' handled", msg.body.split()[0])
                continue

            system = context.build_system_prompt(msg.body, sender=msg.sender, skipped_mcp_servers=_skipped_mcp[0])

            async with _history_lock:
                conversation_history.append({"role": "user", "content": msg.body})
                reply = await _chat_with_typing(
                    msg.channel,
                    recipient,
                    conversation_history,
                    system,
                    msg.image_data,
                    msg.image_mime,
                )
                conversation_history.append({"role": "assistant", "content": reply})
                if len(conversation_history) > _MAX_HISTORY:
                    conversation_history[:] = conversation_history[-_MAX_HISTORY:]

            # Check if the reply requests a secret from the user.
            secret_match = _SECRET_REQUEST_RE.search(reply)
            if secret_match:
                _pending_secret_key[0] = secret_match.group(1)
                reply = _SECRET_REQUEST_RE.sub("", reply).strip()
                logger.info("Secret requested for key %s", _pending_secret_key[0])

            _append_turn("user", msg.body)
            _append_turn("assistant", reply)
            if reply:
                gateway.send(msg.channel, recipient, reply)
                logger.info("Sent reply: %s", reply[:80])

    async def _run_idle_tick() -> None:
        """Run scheduled prompts and heartbeat check."""
        nonlocal last_idle_nudge
        if owntracks_url:
            from awfulclaw.location import check_and_update_location, check_and_update_timezone

            check_and_update_timezone(owntracks_url, owntracks_user, owntracks_device)
            check_and_update_location(owntracks_url, owntracks_user, owntracks_device)

        if mcp_registry.reload_if_changed(_MCP_CONFIG_PATH):
            _mcp_config[0] = None if mcp_registry.is_empty() else mcp_registry.generate_config()
            _skipped_mcp[0] = mcp_registry.skipped_servers()

        due_schedules = scheduler.run_due()
        for sched in due_schedules:
            try:
                sched_system = context.build_system_prompt(sched.prompt, skipped_mcp_servers=_skipped_mcp[0])
                sched_history: list[dict[str, str]] = [{"role": "user", "content": sched.prompt}]
                sched_reply = await _chat_async(sched_history, sched_system)
                if sched_reply and not sched.silent:
                    gateway.send(gateway.primary_channel, phone, sched_reply)
                    logger.info("Schedule reply sent: %s", sched_reply[:80])
                elif sched_reply and sched.silent:
                    logger.info("Silent schedule '%s' completed", sched.name)
            except Exception as exc:
                logger.error("Schedule prompt failed: %s", exc)

        nudge_due = time.monotonic() - last_idle_nudge >= idle_nudge_cooldown
        if nudge_due:
            system = context.build_system_prompt("", skipped_mcp_servers=_skipped_mcp[0])
            idle_reply = await _chat_async(
                [{"role": "user", "content": _load_heartbeat()}],
                system,
            )
            if idle_reply and not _is_idle_suppressed(idle_reply):
                gateway.send(gateway.primary_channel, phone, idle_reply)
                last_idle_nudge = time.monotonic()
                logger.info("Idle message sent: %s", idle_reply[:80])
            elif idle_reply:
                last_idle_nudge = time.monotonic()
                logger.debug("Idle check: nothing to send")

    async def _check_new_emails() -> None:
        """Fetch unread emails newer than last check and alert if any are important."""
        nonlocal last_email_check
        last_email_check = time.monotonic()
        try:
            from awfulclaw_mcp.imap import fetch_emails

            last_check_ts = _load_last_email_check()
            new_last_check_ts = datetime.now(timezone.utc)
            emails = fetch_emails(unread_only=True)
            new_emails = [e for e in emails if e.timestamp > last_check_ts]
            _save_last_email_check(new_last_check_ts)
            if not new_emails:
                return
            lines = [
                f"From: {e.from_addr}\nSubject: {e.subject}\n"
                f"Date: {e.timestamp.isoformat()}\n{e.body_preview}"
                for e in new_emails
            ]
            prompt = _EMAIL_TRIAGE_PROMPT.format(emails="\n\n".join(lines))
            system = context.build_system_prompt(prompt, skipped_mcp_servers=_skipped_mcp[0])
            reply = await _chat_async([{"role": "user", "content": prompt}], system)
            if reply and not _is_idle_suppressed(reply):
                gateway.send(gateway.primary_channel, phone, reply)
                logger.info("Email alert sent: %s", reply[:80])
        except Exception as exc:
            logger.warning("Email check failed: %s", exc)

    try:
        while True:
            messages = gateway.get_messages()

            coroutines = []
            if messages:
                coroutines.append(_handle_messages(messages))

            if time.monotonic() - last_idle >= idle_interval:
                last_idle = time.monotonic()
                coroutines.append(_run_idle_tick())

            email_due = time.monotonic() - last_email_check >= email_check_interval
            if os.getenv("IMAP_HOST") and email_due:
                coroutines.append(_check_new_emails())

            if coroutines:
                await asyncio.gather(*coroutines)

            await asyncio.sleep(poll_interval)

    except (KeyboardInterrupt, SystemExit):
        gateway.stop()
        logger.info("awfulclaw exiting — goodbye")
