"""MCP server for writing to memory files."""

from __future__ import annotations

from awfulclaw import memory
from awfulclaw.db import write_fact, write_person
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("memory_write")

_PROTECTED_FILES = {"SOUL.md", "HEARTBEAT.md"}
_PROTECTED_DIRS = ("skills/", "conversations/")


def _is_protected(path: str) -> bool:
    if path in _PROTECTED_FILES:
        return True
    return any(path.startswith(d) for d in _PROTECTED_DIRS)


@mcp.tool()
def memory_write(path: str, content: str) -> str:
    """Write content to a memory file at memory/{path}.

    Facts (facts/*.md) and people (people/*.md) are stored in SQLite.
    Writes to SOUL.md, HEARTBEAT.md, or skills/ are blocked.
    """
    # Strip leading memory/ prefix if present
    if path.startswith("memory/"):
        path = path[len("memory/"):]

    if _is_protected(path):
        return f"Error: writes to {path!r} are not allowed"

    try:
        if path.startswith("facts/"):
            key = path[len("facts/"):].removesuffix(".md")
            write_fact(key, content.strip())
        elif path.startswith("people/"):
            name = path[len("people/"):].removesuffix(".md")
            write_person(name, content.strip())
        else:
            memory.write(path, content.strip())
    except ValueError as exc:
        return f"Error: {exc}"

    return f"Written to memory/{path}"


if __name__ == "__main__":
    mcp.run()
