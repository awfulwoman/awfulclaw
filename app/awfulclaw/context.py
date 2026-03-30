"""Build the system prompt by loading relevant memory files."""

from __future__ import annotations

import re
import re as _re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from awfulclaw import memory, scheduler
from awfulclaw.db import list_facts, list_people, read_fact, read_person

_SKILLS_DIR = Path("config/skills")

_MAX_CHARS = 8000

_DEFAULT_SOUL = """\
You are a helpful, concise personal assistant. You communicate naturally and directly.
"""

_DEFAULT_USER = """\
# User Profile

Name: unknown
Timezone: unknown
Preferences: unknown
Background: unknown
"""


def _load_soul(channel: str = "") -> str:
    """Read memory/SOUL.md (or SOUL_<channel>.md if it exists), creating defaults if absent."""
    if channel:
        channel_soul = memory.read(f"SOUL_{channel}.md")
        if channel_soul:
            return channel_soul
    content = memory.read("SOUL.md")
    if not content:
        memory.write("SOUL.md", _DEFAULT_SOUL)
        content = _DEFAULT_SOUL
    return content


def _extract_personality_section(content: str) -> str:
    """Extract the ## Personality section from a person file, or return empty string."""
    match = re.search(r"## Personality\s*\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


def _load_user() -> str:
    """Read memory/USER.md, creating it with defaults if absent."""
    content = memory.read("USER.md")
    if not content:
        memory.write("USER.md", _DEFAULT_USER)
        content = _DEFAULT_USER
    return content


def _find_person_by_phone(phone: str) -> tuple[str, str] | None:
    """Return (name, content) of the first person record matching the phone number."""
    for name in list_people():
        content = read_person(name)
        if phone in content:
            return f"{name}.md", content
    return None


def _local_now(user_content: str) -> str:
    """Return current datetime string in the user's timezone if known, else UTC."""
    m = _re.search(r"(?i)^Timezone:\s*(.+)$", user_content, _re.MULTILINE)
    if m:
        tz_name = m.group(1).strip().split()[0]  # take first word, ignore "(Germany)" etc.
        if tz_name.lower() not in ("unknown", ""):
            try:
                tz = ZoneInfo(tz_name)
                return datetime.now(tz).strftime(f"%Y-%m-%d %H:%M {tz_name}")
            except (ZoneInfoNotFoundError, KeyError):
                pass
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def build_system_prompt(
    incoming_message: str,
    sender: str = "",
    channel: str = "",
    skipped_mcp_servers: dict[str, list[str]] | None = None,
) -> str:
    """Build the system prompt with memory context for the incoming message."""
    user = _load_user()
    now = _local_now(user)
    soul = _load_soul(channel)

    # Resolve sender person file early so personality overlay can be applied to soul
    included_people: set[str] = set()
    sender_person: tuple[str, str] | None = None
    if sender:
        sender_person = _find_person_by_phone(sender)
        if sender_person:
            included_people.add(sender_person[0])
            personality = _extract_personality_section(sender_person[1])
            if personality:
                soul = soul + "\n\n## Personality overlay for this sender\n" + personality

    memory_instructions = """\
When you notice fields in the user profile (## About You section) are `unknown`, ask about them \
naturally over time — one question per conversation, not all at once. Update the profile as you \
learn more.

When the user asks a variant of 'what do you know about me?', 'what\'s on my plate', \
'what do you remember?', or 'summarise my memory', respond with a structured summary covering:
1. **Profile** — key fields from the About You / USER.md section
2. **Upcoming Schedules** — all active schedules with their cron and next prompt
3. **Key Facts** — all facts stored in the database
Use the context already loaded in this prompt to assemble the answer — no tool calls needed.\
"""

    capabilities = """\
## App Capabilities

You have MCP tools available beyond basic conversation. \
Use them proactively when the user's request maps to one:

- **Memory** — read/write facts, people profiles, and task files via `memory_write` / \
`memory_search`
- **Schedules** — create, update, or delete recurring or one-off scheduled prompts via \
`schedule_create` / `schedule_delete` / `schedule_list`
- **MCP servers** — install, register, or remove MCP servers (including from GitHub URLs) via \
`mcp_server_add_from_github` / `mcp_server_add` / `mcp_server_remove` / `mcp_server_list`
- **Environment variables** — list configured env var names via `env_keys`; set a new env var \
via `env_set` (if you already have the value); or ask the user to provide a secret (see below)
- **Email** — read unread emails via `imap_fetch` (if configured)
- **Web search** — search the web if needed

When the user says something like "install this MCP server <url>", use `mcp_server_add_from_github`. \
When they ask to be reminded of something, use `schedule_create`. \
When they share a fact about themselves, use `memory_write` to persist it.

## Requesting secrets from the user

When a task requires an API key, token, or other credential that you do not already have:
1. Call `env_keys` first to check whether the key is already configured.
2. If it is not set, tell the user what key is needed and why, then include the tag \
`<secret:request key="KEY_NAME"/>` at the end of your reply (replacing KEY_NAME with the \
actual env var name, e.g. `OPENAI_API_KEY`). Use uppercase letters, digits, and underscores only.
3. The app will intercept the user's next message as the secret value, write it directly to \
`.env`, and confirm to you with `[Secret received and stored to .env as KEY_NAME]`. The value \
is never shown in conversation history.
4. Inform the user that a restart is required for the new key to take effect (or trigger one \
via `/restart` if appropriate).

Always use `<secret:request>` rather than asking the user to paste keys in plain text — it \
keeps secrets out of the conversation log. Never ask the user to provide a credential without \
using this mechanism.\
"""

    _identity = (
        "IMPORTANT: You are the awfulclaw Telegram bot — a personal assistant agent "
        "running in the awfulclaw agent loop. You are NOT Claude Code, a CLI tool, an "
        "IDE extension, or any kind of developer tool. Your only interface with the user "
        "is Telegram. Never say 'this Claude Code session', 'this session', or 'this "
        "interface'. Your tools are MCP servers listed below."
    )

    sections: list[str] = [
        _identity,
        f"Current date and time: {now}",
        soul,
        capabilities,
        memory_instructions,
        f"## About You\n{user}",
    ]

    if skipped_mcp_servers:
        lines = ["## Unavailable MCP Servers (missing configuration)"]
        for name, missing in skipped_mcp_servers.items():
            lines.append(f"- **{name}** — needs env vars: {', '.join(missing)}")
        lines.append(
            "These servers are not loaded and their tools are unavailable. "
            "If the user asks about them, explain what's missing and offer to "
            "collect the required values using <secret:request>."
        )
        sections.append("\n".join(lines))

    # Location (dedicated section with formatted label)
    location_content = read_fact("location")
    if location_content:
        loc_lines = {
            line.split(":", 1)[0].strip(): line.split(":", 1)[1].strip()
            for line in location_content.splitlines()
            if ":" in line
        }
        lat_lon = loc_lines.get("Last known location", "")
        updated = loc_lines.get("Updated", "")
        if lat_lon:
            loc_label = f"User's last known location: {lat_lon}"
            if updated:
                loc_label += f" (as of {updated})"
            sections.append(loc_label)

    # All facts (excluding location, handled above)
    for key in list_facts():
        if key == "location":
            continue
        content = read_fact(key)
        if content:
            sections.append(f"## Fact: {key}.md\n{content}")

    # People: sender match first, then by words in message
    if sender:
        if sender_person:
            filename, content = sender_person
            sections.append(f"## Person: {filename}\n{content}")
        else:
            sections.append(
                f"## Unknown sender: {sender}\n"
                "This sender is not in your people files. "
                "Ask for their name and create a profile for them."
            )

    words = set(incoming_message.lower().split())
    for name in list_people():
        filename = f"{name}.md"
        if filename in included_people:
            continue
        content = read_person(name)
        if name in words or any(word in content.lower() for word in words if len(word) > 3):
            sections.append(f"## Person: {filename}\n{content}")

    # Open tasks (files containing unchecked checkboxes)
    for filename in memory.list_files("tasks"):
        content = memory.read(f"tasks/{filename}")
        if "- [ ]" in content:
            sections.append(f"## Task: {filename}\n{content}")

    # Active schedules
    schedules = scheduler.load_schedules()
    if schedules:
        lines = ["## Active Schedules"]
        for s in schedules:
            if s.fire_at is not None:
                timing = f"fire_at: `{s.fire_at.isoformat()}`"
            else:
                last = s.last_run.isoformat() if s.last_run else "never"
                timing = f"cron: `{s.cron}` | last run: {last}"
            lines.append(f"- **{s.name}** | {timing}\n  Prompt: {s.prompt}")
        sections.append("\n".join(lines))

    # Available skills
    if _SKILLS_DIR.exists():
        skill_names = sorted(f.stem for f in _SKILLS_DIR.glob("*.md"))
        if skill_names:
            sections.append(
                "## Available Skills\n"
                + ", ".join(skill_names)
                + "\nUse the skill_read MCP tool to load a skill's instructions."
            )

    prompt = "\n\n".join(sections)

    if len(prompt) <= _MAX_CHARS:
        return prompt

    # Truncate: keep soul + capabilities + as many sections as fit, dropping oldest facts first
    result = soul + "\n\n" + capabilities
    non_fact = [s for s in sections[2:] if not s.startswith("## Fact:")]
    fact = [s for s in sections[2:] if s.startswith("## Fact:")]

    for section in non_fact + list(reversed(fact)):
        candidate = result + "\n\n" + section
        if len(candidate) <= _MAX_CHARS:
            result = candidate

    return result
