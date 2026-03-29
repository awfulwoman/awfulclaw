"""Build the system prompt by loading relevant memory files."""

from __future__ import annotations

from awfulclaw import memory

_MAX_CHARS = 8000

_BASE_PROMPT = """\
You are awfulclaw, a personal AI assistant that communicates via iMessage.
You help with tasks, remember important information about people and ongoing tasks,
and proactively surface anything that needs attention.

You can manage tasks by including a special block in your reply:
  <memory:write path="tasks/foo.md">...markdown content...</memory:write>
Use Markdown checkboxes for task status: `- [ ] item` (open) / `- [x] item` (done).

You can manage people profiles similarly:
  <memory:write path="people/name.md">...markdown content...</memory:write>
People files should include: name, phone/contact, relationship, notes.

Always be concise and helpful. Reply in a conversational tone suitable for iMessage.
"""


def build_system_prompt(incoming_message: str) -> str:
    """Build the system prompt with memory context for the incoming message."""
    sections: list[str] = [_BASE_PROMPT]

    # All facts
    for filename in memory.list_files("facts"):
        content = memory.read(f"facts/{filename}")
        if content:
            sections.append(f"## Fact: {filename}\n{content}")

    # People files matching words in the message
    words = set(incoming_message.lower().split())
    for filename in memory.list_files("people"):
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

    prompt = "\n\n".join(sections)

    if len(prompt) <= _MAX_CHARS:
        return prompt

    # Truncate: keep base prompt + as many sections as fit, dropping oldest facts first
    result = _BASE_PROMPT
    # Re-add non-fact sections first (people, tasks)
    non_fact = [s for s in sections[1:] if not s.startswith("## Fact:")]
    fact = [s for s in sections[1:] if s.startswith("## Fact:")]

    for section in non_fact + list(reversed(fact)):
        candidate = result + "\n\n" + section
        if len(candidate) <= _MAX_CHARS:
            result = candidate

    return result
