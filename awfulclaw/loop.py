"""Main event loop — ties iMessage, Claude, and memory together."""

from __future__ import annotations

import logging
import re
import signal
import time
from datetime import date, datetime, timezone
from pathlib import Path

from awfulclaw import claude, config, context, memory, scheduler
from awfulclaw.connector import Connector
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

_BRIEFING_PROMPT = (
    "Good morning! Please give me a concise daily briefing. Include:\n"
    "1. Any open tasks from memory/tasks/\n"
    "2. Schedules due today or this week\n"
    "3. Anything flagged or important in memory/facts/\n"
    "4. If IMAP is configured, check for new emails using <skill:imap/>\n\n"
    "Keep it brief and actionable."
)

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
        memory.write(path, content.strip())
        logger.info("Memory write: %s", path)
    return _MEMORY_WRITE_RE.sub("", text).strip()


def _dispatch_all_skills(
    reply: str,
    history: list[dict[str, str]],
    system: str,
) -> str:
    """Process all skill tags in reply using the module registry.

    Handles multiple tags by processing them one at a time, re-invoking
    Claude after each. Strips leftover malformed tags at the end.
    """
    registry = get_registry()
    for _round in range(5):  # max 5 dispatch rounds
        matched = False
        for module, skill_tag in registry.get_all_skill_tags():
            match = skill_tag.pattern.search(reply)
            if match:
                reply = skill_tag.pattern.sub("", reply, count=1).strip()
                result_text = module.dispatch(match, history, system)
                history.append({"role": "assistant", "content": reply})
                history.append({"role": "user", "content": result_text})
                reply = claude.chat(history, system=system)
                reply = _parse_and_apply_memory_writes(reply)
                matched = True
                break  # restart matching from the top
        if not matched:
            break
    # Strip any leftover malformed skill tags
    for module, skill_tag in registry.get_all_skill_tags():
        reply = skill_tag.pattern.sub("", reply).strip()
    return reply


def _session_path() -> str:
    """Return conversations/YYYY/MM/<iso-timestamp>.md with colons replaced by dashes."""
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H-%M-%S")
    return f"conversations/{now.year}/{now.month:02d}/{ts}.md"


_MEMORY_ROOT = Path("memory")


def _sigterm_handler(signum: int, frame: object) -> None:
    raise SystemExit(0)


_TURN_RE = re.compile(r"^## \S+ — (User|Assistant)\s*$", re.MULTILINE)


def _load_recent_history(max_turns: int = 20) -> list[dict[str, str]]:
    """Load the last *max_turns* turns from the most recent conversation file."""
    conv_dir = _MEMORY_ROOT / "conversations"
    try:
        files = sorted(conv_dir.rglob("*.md"), key=lambda p: p.stat().st_mtime)
        if not files:
            return []
        recent = files[-1]
        text = recent.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not read recent conversation file: %s", exc)
        return []

    try:
        parts = _TURN_RE.split(text)
        # parts: [pre-header-text, role1, content1, role2, content2, ...]
        turns: list[dict[str, str]] = []
        i = 1
        while i + 1 < len(parts):
            role = parts[i].strip()
            content = parts[i + 1].strip()
            turns.append({"role": role.lower(), "content": content})
            i += 2
        return turns[-max_turns:]
    except Exception as exc:
        logger.warning("Failed to parse recent conversation history: %s", exc)
        return []


def _append_turn(session_file: str, role: str, content: str) -> None:
    """Append a single conversation turn to the session file."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = f"\n## {ts} — {role}\n{content}\n"
    try:
        full = _MEMORY_ROOT / session_file
        with full.open("a", encoding="utf-8") as f:
            f.write(entry)
    except Exception as exc:
        logger.error("Failed to append conversation turn: %s", exc)


def run(connector: Connector) -> None:
    """Run the agent loop indefinitely until Ctrl-C."""
    signal.signal(signal.SIGTERM, _sigterm_handler)
    logger.info("awfulclaw starting up")

    registry = get_registry()

    poll_interval = config.get_poll_interval()
    idle_interval = config.get_idle_interval()
    phone = connector.primary_recipient

    conversation_history: list[dict[str, str]] = _load_recent_history()
    if conversation_history:
        logger.info("Restored %d turns from previous session", len(conversation_history))
    last_poll = datetime.now(timezone.utc)
    last_idle = time.monotonic()
    last_briefing_date: date | None = None
    briefing_time = config.get_briefing_time()

    session_file = _session_path()
    try:
        full = _MEMORY_ROOT / session_file
        full.parent.mkdir(parents=True, exist_ok=True)
        session_ts = session_file.removeprefix("conversations/").removesuffix(".md")
        full.write_text(f"# Session: {session_ts}\n", encoding="utf-8")
    except Exception as exc:
        logger.error("Failed to create session file: %s", exc)

    try:
        while True:
            now = datetime.now(timezone.utc)
            messages = connector.poll_new_messages(since=last_poll)
            last_poll = now

            for msg in messages:
                logger.info("Incoming from %s: %s", msg.sender, msg.body[:80])

                loc_match = _LOCATION_RE.match(msg.body)
                if loc_match:
                    lat, lon = loc_match.group(1), loc_match.group(2)
                    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    memory.write(
                        "facts/location.md",
                        f"Last known location: {lat}, {lon}\nUpdated: {ts}",
                    )
                    logger.info("Location saved: %s, %s", lat, lon)
                    continue

                slash_reply = handle_slash_command(msg.body)
                if slash_reply is not None:
                    connector.send_message(phone, slash_reply)
                    logger.info("Slash command '%s' handled", msg.body.split()[0])
                    continue

                system = context.build_system_prompt(msg.body, sender=msg.sender)

                conversation_history.append({"role": "user", "content": msg.body})
                reply = claude.chat(
                    conversation_history,
                    system=system,
                    image_data=msg.image_data,
                    image_mime=msg.image_mime,
                )
                reply = _parse_and_apply_memory_writes(reply)
                reply = _dispatch_all_skills(reply, conversation_history, system)

                conversation_history.append({"role": "assistant", "content": reply})
                _MAX_HISTORY = 40
                if len(conversation_history) > _MAX_HISTORY:
                    conversation_history[:] = conversation_history[-_MAX_HISTORY:]
                _append_turn(session_file, "User", msg.body)
                _append_turn(session_file, "Assistant", reply)
                if reply:
                    connector.send_message(phone, reply)
                    logger.info("Sent reply: %s", reply[:80])

            if time.monotonic() - last_idle >= idle_interval:
                last_idle = time.monotonic()
                now = datetime.now(timezone.utc)

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
                                sched_reply = claude.chat(sched_history, system=sched_system)
                                sched_reply = _parse_and_apply_memory_writes(sched_reply)
                                sched_reply = _dispatch_all_skills(
                                    sched_reply, sched_history, sched_system
                                )
                                if sched_reply:
                                    connector.send_message(phone, sched_reply)
                                    logger.info("Schedule reply sent: %s", sched_reply[:80])
                            except Exception as exc:
                                logger.error("Schedule prompt failed: %s", exc)

                if briefing_time is not None:
                    today = now.date()
                    delta_secs = (
                        now.hour * 3600
                        + now.minute * 60
                        + now.second
                        - briefing_time.hour * 3600
                        - briefing_time.minute * 60
                    )
                    if 0 <= delta_secs < poll_interval and last_briefing_date != today:
                        last_briefing_date = today
                        try:
                            briefing_system = context.build_system_prompt(_BRIEFING_PROMPT)
                            briefing_history: list[dict[str, str]] = [
                                {"role": "user", "content": _BRIEFING_PROMPT}
                            ]
                            briefing_reply = claude.chat(briefing_history, system=briefing_system)
                            briefing_reply = _parse_and_apply_memory_writes(briefing_reply)
                            briefing_reply = _dispatch_all_skills(
                                briefing_reply, briefing_history, briefing_system
                            )
                            if briefing_reply:
                                connector.send_message(phone, briefing_reply)
                                logger.info("Daily briefing sent: %s", briefing_reply[:80])
                        except Exception as exc:
                            logger.error("Daily briefing failed: %s", exc)

                system = context.build_system_prompt("")
                idle_reply = claude.chat(
                    [{"role": "user", "content": _load_heartbeat()}],
                    system=system,
                )
                idle_reply = _parse_and_apply_memory_writes(idle_reply)
                if idle_reply and not _is_idle_suppressed(idle_reply):
                    connector.send_message(phone, idle_reply)
                    logger.info("Idle message sent: %s", idle_reply[:80])

            time.sleep(poll_interval)

    except (KeyboardInterrupt, SystemExit):
        logger.info("awfulclaw exiting — goodbye")
