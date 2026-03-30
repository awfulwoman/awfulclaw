"""MCP server for memory search."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

import awfulclaw.memory as memory
from awfulclaw.db import get_db, search_facts, search_people

mcp = FastMCP("memory_search")

_MAX_RESULTS = 20


@mcp.tool()
def memory_search(query: str) -> str:
    """Search across all memory files, facts, people, and conversation history.

    Returns matching lines grouped by source. Use to recall facts, tasks,
    notes, or past conversations.
    """
    results = search_facts(query) + search_people(query) + memory.search_all(
        query, subdirs=["tasks", "skills"]
    )
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


if __name__ == "__main__":
    mcp.run()
