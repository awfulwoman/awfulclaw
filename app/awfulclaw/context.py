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


def build_system_prompt(incoming_message: str, sender: str = "", channel: str = "") -> str:
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

    sections: list[str] = [
        f"Current date and time: {now}",
        soul,
        memory_instructions,
        f"## About You\n{user}",
    ]

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

    # Truncate: keep soul + as many sections as fit, dropping oldest facts first
    result = soul
    non_fact = [s for s in sections[1:] if not s.startswith("## Fact:")]
    fact = [s for s in sections[1:] if s.startswith("## Fact:")]

    for section in non_fact + list(reversed(fact)):
        candidate = result + "\n\n" + section
        if len(candidate) <= _MAX_CHARS:
            result = candidate

    return result
