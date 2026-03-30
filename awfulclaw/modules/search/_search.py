"""Memory search module."""

from __future__ import annotations

import re

import awfulclaw.memory as memory
from awfulclaw.db import get_db, search_facts, search_people
from awfulclaw.modules.base import Module, SkillTag

_SKILL_SEARCH_RE = re.compile(r'<skill:search\s+query="([^"]*?)"\s*/?>')

_MAX_RESULTS = 20


class SearchModule(Module):
    @property
    def name(self) -> str:
        return "search"

    @property
    def skill_tags(self) -> list[SkillTag]:
        return [
            SkillTag(
                name="search",
                pattern=_SKILL_SEARCH_RE,
                description="Search memory files for a query string",
                usage='<skill:search query="..."/>',
            )
        ]

    @property
    def system_prompt_fragment(self) -> str:
        return """\
### Memory Search
Search across all memory files with:
```
<skill:search query="search terms"/>
```
Returns matching lines grouped by file. Use when you need to recall facts, tasks, or notes."""

    def dispatch(self, tag_match: re.Match[str], history: list[dict[str, str]], system: str) -> str:
        query = tag_match.group(1)
        results = memory.search_all(query, subdirs=["tasks", "skills"])
        results = search_facts(query) + search_people(query) + results
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

        # Also search conversation history
        try:
            with get_db() as conn:
                rows = conn.execute(
                    "SELECT role, content, timestamp FROM conversations"
                    " WHERE content LIKE ? LIMIT ?",
                    (f"%{query}%", _MAX_RESULTS - count),
                ).fetchall()
            if rows:
                lines.append("\nconversations:")
                for row in rows:
                    snippet = row["content"][:120].replace("\n", " ")
                    lines.append(f"  [{row['timestamp']} {row['role']}] {snippet}")
                    count += 1
        except Exception:
            pass

        if count == 0:
            return f"[No matches found for: {query}]"
        return "\n".join(lines)

    def is_available(self) -> bool:
        return True
