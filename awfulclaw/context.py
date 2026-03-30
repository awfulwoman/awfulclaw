"""Build the system prompt by loading relevant memory files."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from awfulclaw import memory, scheduler
from awfulclaw.modules import get_registry

_MAX_CHARS = 8000

_DEFAULT_SOUL = """\
You are a helpful, concise personal assistant. You communicate naturally and directly.

You have access to a persistent memory system stored as Markdown files under `memory/`.
You can write to memory using `<memory:write path="...">...</memory:write>` tags in your replies.
You have skills in `skills/`, a user profile at `USER.md`, tasks in `tasks/`,
facts in `facts/`, and conversation history in `conversations/`.

To search the web use:
  `<skill:web query="your search query"/>`
The system will inject the top results as a follow-up user message, then you reply with a summary.
Use this when the user asks about current events, facts you're unsure of, or anything that benefits
from an up-to-date web source.

To search past conversations and memory use:
  `<skill:search query="your search terms"/>`
The system will search all memory files (people, tasks, facts, conversations, skills) for matching
content and inject the results as a follow-up user message. Use this when the user asks what you
discussed before, references a past conversation, or asks about stored facts or history.

To create a recurring schedule use:
  `<skill:schedule action="create" name="..." cron="0 9 * * *">prompt</skill:schedule>`
To create a one-off reminder at a specific datetime use:
  `<skill:schedule action="create" name="..." at="2026-04-01T15:00:00Z">prompt</skill:schedule>`
Optionally add a `condition` attribute with a shell command. The command must print JSON with a
`wakeAgent` boolean key. If `wakeAgent` is false, the Claude invocation is skipped for that tick
(but the schedule still advances). Use this to avoid unnecessary LLM calls:
  `<skill:schedule action="create" name="..." cron="0 * * * *"
    condition="python check.py">prompt</skill:schedule>`
To delete a schedule use:
  `<skill:schedule action="delete" name="..."/>`

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
    """Return (filename, content) of the first people file matching the phone number."""
    for filename in memory.list_files("people"):
        content = memory.read(f"people/{filename}")
        if phone in content:
            return filename, content
    return None


def build_system_prompt(incoming_message: str, sender: str = "", channel: str = "") -> str:
    """Build the system prompt with memory context for the incoming message."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    soul = _load_soul(channel)
    user = _load_user()

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

    memory_summary_instruction = """\
## Memory Summary Instruction
When the user asks a variant of 'what do you know about me?', 'show me my tasks', \
'what\'s on my plate', 'what do you remember?', or 'summarise my memory', respond with a \
structured summary covering:
1. **Profile** — key fields from the About You / USER.md section
2. **Open Tasks** — all unchecked items (- [ ]) from memory/tasks/ files
3. **Active Skills** — names of all files in memory/skills/
4. **Upcoming Schedules** — all active schedules with their cron and next prompt
5. **Key Facts** — titles/summaries of all files in memory/facts/
Use the context already loaded in this prompt to assemble the answer — no tool calls needed.\
"""

    sections: list[str] = [
        f"Current date and time: {now}",
        soul,
        memory_summary_instruction,
        f"## About You\n{user}",
    ]

    # Location (dedicated section with formatted label)
    location_content = memory.read("facts/location.md")
    if location_content:
        lines = {
            line.split(":", 1)[0].strip(): line.split(":", 1)[1].strip()
            for line in location_content.splitlines()
            if ":" in line
        }
        lat_lon = lines.get("Last known location", "")
        updated = lines.get("Updated", "")
        if lat_lon:
            loc_label = f"User's last known location: {lat_lon}"
            if updated:
                loc_label += f" (as of {updated})"
            sections.append(loc_label)

    # All facts (excluding location.md, handled above)
    for filename in memory.list_files("facts"):
        if filename == "location.md":
            continue
        content = memory.read(f"facts/{filename}")
        if content:
            sections.append(f"## Fact: {filename}\n{content}")

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
    for filename in memory.list_files("people"):
        if filename in included_people:
            continue
        content = memory.read(f"people/{filename}")
        name_stem = filename.replace(".md", "").lower()
        if name_stem in words or any(word in content.lower() for word in words if len(word) > 3):
            sections.append(f"## Person: {filename}\n{content}")

    # Open tasks (files containing unchecked checkboxes)
    for filename in memory.list_files("tasks"):
        content = memory.read(f"tasks/{filename}")
        if "- [ ]" in content:
            sections.append(f"## Task: {filename}\n{content}")

    # Module skill documentation
    registry = get_registry()
    fragments = registry.get_system_prompt_fragments()
    if fragments:
        sections.append("## Available Skills\n\n" + "\n\n".join(fragments))

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
