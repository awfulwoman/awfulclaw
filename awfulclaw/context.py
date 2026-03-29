"""Build the system prompt by loading relevant memory files."""

from __future__ import annotations

from datetime import datetime, timezone

from awfulclaw import memory, scheduler
from awfulclaw import skills as skills_module

_MAX_CHARS = 8000

_DEFAULT_SOUL = """\
You are a helpful, concise personal assistant. You communicate naturally and directly.

You have access to a persistent memory system stored as Markdown files under `memory/`.
You can write to memory using `<memory:write path="...">...</memory:write>` tags in your replies.
You have skills in `memory/skills/`, a user profile at `memory/USER.md`, tasks in `memory/tasks/`,
facts in `memory/facts/`, and conversation history in `memory/conversations/`.

When you notice that fields in the user profile (## About You section) are `unknown`, ask about them
naturally over time — one question per conversation, not all at once. As you learn more about the
user, update their profile using `<memory:write path="USER.md">...</memory:write>`.

Always be honest about what you know and don't know.
"""

_DEFAULT_USER = """\
# User Profile

Name: unknown
Timezone: unknown
Preferences: unknown
Background: unknown
"""


def _load_soul() -> str:
    """Read memory/SOUL.md, creating it with defaults if absent."""
    content = memory.read("SOUL.md")
    if not content:
        memory.write("SOUL.md", _DEFAULT_SOUL)
        content = _DEFAULT_SOUL
    return content


def _load_user() -> str:
    """Read memory/USER.md, creating it with defaults if absent."""
    content = memory.read("USER.md")
    if not content:
        memory.write("USER.md", _DEFAULT_USER)
        content = _DEFAULT_USER
    return content


def _find_person_by_phone(phone: str) -> tuple[str, str] | None:
    """Return (filename, content) of the first people file matching the phone number."""
    for filename in memory.list_files("people"):
        content = memory.read(f"people/{filename}")
        if phone in content:
            return filename, content
    return None


def build_system_prompt(incoming_message: str, sender: str = "") -> str:
    """Build the system prompt with memory context for the incoming message."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    soul = _load_soul()
    user = _load_user()
    sections: list[str] = [f"Current date and time: {now}", soul, f"## About You\n{user}"]

    # All facts
    for filename in memory.list_files("facts"):
        content = memory.read(f"facts/{filename}")
        if content:
            sections.append(f"## Fact: {filename}\n{content}")

    # People: match by sender phone first, then by words in message
    included_people: set[str] = set()

    if sender:
        match = _find_person_by_phone(sender)
        if match:
            filename, content = match
            sections.append(f"## Person: {filename}\n{content}")
            included_people.add(filename)
        else:
            sections.append(
                f"## Unknown sender: {sender}\n"
                "This sender is not in your people files. "
                "Ask for their name and create a profile for them."
            )

    words = set(incoming_message.lower().split())
    for filename in memory.list_files("people"):
        if filename in included_people:
            continue
        content = memory.read(f"people/{filename}")
        name_stem = filename.replace(".md", "").lower()
        if name_stem in words or any(
            word in content.lower() for word in words if len(word) > 3
        ):
            sections.append(f"## Person: {filename}\n{content}")

    # Open tasks (files containing unchecked checkboxes)
    for filename in memory.list_files("tasks"):
        content = memory.read(f"tasks/{filename}")
        if "- [ ]" in content:
            sections.append(f"## Task: {filename}\n{content}")

    # Matched skills
    all_skills = skills_module.load_skills()
    matched = skills_module.match_skills(incoming_message, all_skills)
    if matched:
        skill_lines = ["## Active Skills"]
        for skill in matched:
            skill_lines.append(f"### {skill.name}\n{skill.instruction}")
            if skill.body:
                skill_lines.append(skill.body)
        sections.append("\n\n".join(skill_lines))

    # Active schedules
    schedules = scheduler.load_schedules()
    if schedules:
        lines = ["## Active Schedules"]
        for s in schedules:
            last = s.last_run.isoformat() if s.last_run else "never"
            lines.append(
                f"- **{s.name}** | cron: `{s.cron}` | last run: {last}\n  Prompt: {s.prompt}"
            )
        sections.append("\n".join(lines))

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
