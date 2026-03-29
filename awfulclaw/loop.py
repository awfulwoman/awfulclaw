"""Main event loop — ties iMessage, Claude, and memory together."""

from __future__ import annotations

import logging
import os
import re
import signal
import time
from datetime import date, datetime, timezone
from pathlib import Path

from croniter import croniter  # type: ignore[import-untyped]

from awfulclaw import claude, config, context, memory, scheduler
from awfulclaw.connector import Connector

logger = logging.getLogger(__name__)

_MEMORY_WRITE_RE = re.compile(
    r"<memory:write\s+path=\"([^\"]+)\">(.*?)</memory:write>",
    re.DOTALL,
)

_LOCATION_RE = re.compile(r"^\[Location:\s*(-?\d+\.?\d*),\s*(-?\d+\.?\d*)\]$")

_SKILL_IMAP_RE = re.compile(r"<skill:imap\s*/>|<skill:imap\s*></skill:imap>")

_SKILL_WEB_RE = re.compile(r'<skill:web\s+query="([^"]*?)"\s*/?>')

_SKILL_SEARCH_RE = re.compile(r'<skill:search\s+query="([^"]*?)"\s*/?>')

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
                line for line in f.read_text(encoding="utf-8").splitlines()
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
        _write_restart_reason("user_requested")
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


def _parse_and_apply_memory_writes(text: str) -> str:
    """Extract <memory:write> blocks, apply them, return cleaned text."""
    for path, content in _MEMORY_WRITE_RE.findall(text):
        path = path.strip()
        if path.startswith("memory/"):
            path = path[len("memory/"):]
        memory.write(path, content.strip())
        logger.info("Memory write: %s", path)
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
            at_str = attrs.get("at", "").strip()
            if at_str:
                try:
                    fire_at = datetime.fromisoformat(at_str)
                    if fire_at.tzinfo is None:
                        fire_at = fire_at.replace(tzinfo=timezone.utc)
                except ValueError:
                    errors.append(f"Invalid datetime '{at_str}' for schedule '{name}'.")
                    return ""
                new_sched = scheduler.Schedule.create(name=name, prompt=body, fire_at=fire_at)
            else:
                if not croniter.is_valid(cron):
                    errors.append(f"Invalid cron expression '{cron}' for schedule '{name}'.")
                    return ""
                new_sched = scheduler.Schedule.create(name=name, cron=cron, prompt=body)
            # Overwrite existing schedule with same name (case-insensitive)
            idx = next(
                (i for i, s in enumerate(schedules) if s.name.lower() == name.lower()),
                None,
            )
            if idx is not None:
                schedules[idx] = new_sched
                logger.info("Schedule updated: '%s'", name)
            else:
                schedules.append(new_sched)
                logger.info("Schedule created: '%s'", name)
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


def _fetch_search_results(query: str) -> str:
    """Search memory files for query, return formatted result text."""
    results = memory.search_all(query)
    if not results:
        return f"[No matches found for: {query}]"
    _MAX_RESULTS = 20
    lines = [f"[Memory search results for: {query}]"]
    current_file: str | None = None
    count = 0
    for path, line in results:
        if count >= _MAX_RESULTS:
            break
        if path != current_file:
            lines.append(f"\n{path}:")
            current_file = path
        lines.append(f"  {line}")
        count += 1
    return "\n".join(lines)


def _fetch_web_results(query: str) -> str:
    """Run the web search skill, return formatted result text."""
    try:
        from awfulclaw.web import search

        results = search(query)
        if not results:
            return "[Web search returned no results]"
        lines = [f"[Web search results for: {query}]"]
        for r in results:
            lines.append(f"- {r.title}\n  {r.url}\n  {r.snippet}")
        return "\n\n".join(lines)
    except Exception as exc:
        logger.warning("Web search error: %s", exc)
        return f"[Web search unavailable: {exc}]"


def _session_path() -> str:
    """Return conversations/<iso-timestamp>.md with colons replaced by dashes."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    return f"conversations/{ts}.md"


_MEMORY_ROOT = Path("memory")
_RESTART_REASON_PATH = _MEMORY_ROOT / ".restart_reason"


def _write_restart_reason(reason: str) -> None:
    try:
        _RESTART_REASON_PATH.parent.mkdir(parents=True, exist_ok=True)
        _RESTART_REASON_PATH.write_text(reason, encoding="utf-8")
    except Exception:
        pass


def _pop_restart_reason() -> str | None:
    try:
        if _RESTART_REASON_PATH.exists():
            reason = _RESTART_REASON_PATH.read_text(encoding="utf-8").strip()
            _RESTART_REASON_PATH.unlink()
            return reason or None
    except Exception:
        pass
    return None


def _sigterm_handler(signum: int, frame: object) -> None:
    _write_restart_reason("code_change")
    exc = SystemExit(0)
    exc._code_change = True  # type: ignore[attr-defined]
    raise exc


def _generate_startup_message(restart_reason: str | None) -> str:
    if restart_reason == "code_change":
        prompt = (
            "You've just restarted because code changes were made. "
            "Send a short natural message letting the user know you're back and picked up the changes. "
            "One or two sentences. Don't use the word 'awfulclaw'."
        )
    elif restart_reason == "user_requested":
        prompt = (
            "You've just restarted at the user's request. "
            "Send a short natural message confirming you're back. One sentence."
        )
    else:
        prompt = (
            "You're coming online. Send a short natural greeting to let the user know you're here. "
            "One sentence. Don't use the word 'awfulclaw'."
        )
    try:
        system = context.build_system_prompt("")
        return claude.chat([{"role": "user", "content": prompt}], system=system)
    except Exception as exc:
        logger.warning("Failed to generate startup message: %s", exc)
        if restart_reason == "code_change":
            return "I've restarted to pick up some code changes — back now!"
        if restart_reason == "user_requested":
            return "Restarted and ready!"
        return "I'm online and ready."
_TURN_RE = re.compile(r"^## \S+ — (User|Assistant)\s*$", re.MULTILINE)


def _load_recent_history(max_turns: int = 20) -> list[dict[str, str]]:
    """Load the last *max_turns* turns from the most recent conversation file."""
    conv_dir = _MEMORY_ROOT / "conversations"
    try:
        files = sorted(conv_dir.glob("*.md"), key=lambda p: p.stat().st_mtime)
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

    poll_interval = config.get_poll_interval()
    idle_interval = config.get_idle_interval()
    phone = connector.primary_recipient

    conversation_history: list[dict[str, str]] = _load_recent_history()
    if conversation_history:
        logger.info("Restored %d turns from previous session", len(conversation_history))
    last_poll = datetime.now(timezone.utc)
    last_idle = time.monotonic()
    last_imap_check: datetime | None = None
    last_briefing_date: date | None = None
    briefing_time = config.get_briefing_time()
    schedules = scheduler.load_schedules()

    session_file = _session_path()
    try:
        full = _MEMORY_ROOT / session_file
        full.parent.mkdir(parents=True, exist_ok=True)
        session_ts = session_file.removeprefix("conversations/").removesuffix(".md")
        full.write_text(f"# Session: {session_ts}\n", encoding="utf-8")
    except Exception as exc:
        logger.error("Failed to create session file: %s", exc)

    try:
        restart_reason = _pop_restart_reason()
        connector.send_message(phone, _generate_startup_message(restart_reason))
    except Exception as exc:
        logger.warning("Failed to send startup notification: %s", exc)

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

                web_match = _SKILL_WEB_RE.search(reply)
                if web_match:
                    query = web_match.group(1)
                    reply = _SKILL_WEB_RE.sub("", reply).strip()
                    web_text = _fetch_web_results(query)
                    conversation_history.append({"role": "assistant", "content": reply})
                    conversation_history.append({"role": "user", "content": web_text})
                    reply = claude.chat(conversation_history, system=system)
                    reply = _parse_and_apply_memory_writes(reply)

                search_match = _SKILL_SEARCH_RE.search(reply)
                if search_match:
                    query = search_match.group(1)
                    reply = _SKILL_SEARCH_RE.sub("", reply).strip()
                    search_text = _fetch_search_results(query)
                    conversation_history.append({"role": "assistant", "content": reply})
                    conversation_history.append({"role": "user", "content": search_text})
                    reply = claude.chat(conversation_history, system=system)
                    reply = _parse_and_apply_memory_writes(reply)

                conversation_history.append({"role": "assistant", "content": reply})
                _append_turn(session_file, "User", msg.body)
                _append_turn(session_file, "Assistant", reply)
                if reply:
                    connector.send_message(phone, reply)
                    logger.info("Sent reply: %s", reply[:80])

            if time.monotonic() - last_idle >= idle_interval:
                last_idle = time.monotonic()
                now = datetime.now(timezone.utc)

                due = scheduler.get_due(schedules, now)
                one_off_ids: set[str] = set()
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
                        if sched.fire_at is not None:
                            one_off_ids.add(sched.id)
                        else:
                            sched.last_run = now
                    except Exception as exc:
                        logger.error("Schedule '%s' failed: %s", sched.name, exc)
                if one_off_ids:
                    schedules[:] = [s for s in schedules if s.id not in one_off_ids]
                if due:
                    scheduler.save_schedules(schedules)

                if briefing_time is not None:
                    today = now.date()
                    delta_secs = (
                        now.hour * 3600 + now.minute * 60 + now.second
                        - briefing_time.hour * 3600 - briefing_time.minute * 60
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
                            if _SKILL_IMAP_RE.search(briefing_reply):
                                briefing_reply = _SKILL_IMAP_RE.sub("", briefing_reply).strip()
                                imap_text, last_imap_check = _fetch_imap_results(last_imap_check)
                                briefing_history.append(
                                    {"role": "assistant", "content": briefing_reply}
                                )
                                briefing_history.append({"role": "user", "content": imap_text})
                                briefing_reply = claude.chat(
                                    briefing_history, system=briefing_system
                                )
                                briefing_reply = _parse_and_apply_memory_writes(briefing_reply)
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

    except (KeyboardInterrupt, SystemExit) as exc:
        if isinstance(exc, SystemExit) and getattr(exc, "_code_change", False):
            msg = "I've noticed some code changes — restarting to pick them up. Back in a moment!"
        else:
            msg = "Going offline now — catch you later!"
        try:
            connector.send_message(phone, msg)
        except Exception as send_exc:
            logger.warning("Failed to send shutdown notification: %s", send_exc)
        logger.info("awfulclaw exiting — goodbye")
