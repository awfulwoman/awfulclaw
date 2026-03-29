"""Build the system prompt by loading relevant memory files."""

from __future__ import annotations

from awfulclaw import memory, scheduler
from awfulclaw import skills as skills_module

_MAX_CHARS = 8000

_BASE_PROMPT = """\
You are awfulclaw, a personal AI assistant that communicates via iMessage.
You help with tasks, remember important information about people and ongoing tasks,
and proactively surface anything that needs attention.

You can manage tasks by including a special block in your reply:
  <memory:write path="tasks/foo.md">...markdown content...</memory:write>
Use Markdown checkboxes for task status: `- [ ] item` (open) / `- [x] item` (done).
Create a task file when the user mentions something they want to track or do.
Update the file (re-write it with checkboxes updated) when tasks are completed.

You can manage people profiles similarly:
  <memory:write path="people/name.md">...markdown content...</memory:write>
People files should include: name, phone/contact, relationship, notes.
Create a people file the first time you learn someone's name. Update it as you learn more.

You can check the user's email by including this tag anywhere in your reply:
  <skill:imap/>
Use <skill:imap/> when the user asks you to check their email, see if they have any new messages,
or retrieve email content. The tag will be intercepted, stripped from your reply, and the results
injected back as a follow-up so you can summarise them for the user.

You can manage scheduled tasks using <skill:schedule> tags:

  Create a schedule:
    <skill:schedule action="create" name="Schedule name" cron="CRON_EXPR">
    Prompt to run
    </skill:schedule>

  Delete a schedule:
    <skill:schedule action="delete" name="Schedule name"/>

Cron format is 5-field: min hour dom mon dow (standard cron). Examples:
  Daily at 9am:       0 9 * * *
  Weekdays at 9am:    0 9 * * 1-5
  Hourly:             0 * * * *
  Every Monday 8am:   0 8 * * 1

The tag is stripped before sending; Claude is informed of errors if the cron is invalid.
To see active schedules, they are listed in your context below.
To delete a schedule, use the delete action with the exact name.

## Skills

You can save persistent behavioral rules as skill files so they apply automatically
in future conversations.

Skill files live in `memory/skills/` and are created with the existing memory:write tag:
  <memory:write path="skills/name.md">---
trigger: keyword1, keyword2
instruction: The rule to follow when this skill is active.
---
Optional extra notes.
</memory:write>

- `trigger`: comma-separated keywords that activate this skill when they appear in a message
- `instruction`: the rule or behavior to follow
- Choose trigger keywords likely to appear in future messages where the skill is relevant
  (e.g. for a coffee preference, triggers might be "coffee, drink, morning")

Create a skill whenever the user uses language indicating a persistent preference or rule:
"always", "never", "remember", "should", "from now on", "every time", "make sure".

After saving a skill, confirm to the user: "Got it — I've saved that as a skill."

Always be concise and helpful. Reply in a conversational tone suitable for iMessage.
"""


def _find_person_by_phone(phone: str) -> tuple[str, str] | None:
    """Return (filename, content) of the first people file matching the phone number."""
    for filename in memory.list_files("people"):
        content = memory.read(f"people/{filename}")
        if phone in content:
            return filename, content
    return None


def build_system_prompt(incoming_message: str, sender: str = "") -> str:
    """Build the system prompt with memory context for the incoming message."""
    sections: list[str] = [_BASE_PROMPT]

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

    # Truncate: keep base prompt + as many sections as fit, dropping oldest facts first
    result = _BASE_PROMPT
    non_fact = [s for s in sections[1:] if not s.startswith("## Fact:")]
    fact = [s for s in sections[1:] if s.startswith("## Fact:")]

    for section in non_fact + list(reversed(fact)):
        candidate = result + "\n\n" + section
        if len(candidate) <= _MAX_CHARS:
            result = candidate

    return result
