"""MCP server for writing to memory files."""

from __future__ import annotations

from awfulclaw import memory
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
    """Write content to an internal memory file at memory/{path}.

    Use this for internal agent files only (e.g. USER.md, tasks/*.md).
    Facts and people profiles should be stored in Obsidian at
    awfulclaw/facts/<topic>.md and awfulclaw/people/<name>.md instead —
    use the obsidian_create / obsidian_append tools for those.
    Writes to SOUL.md, HEARTBEAT.md, or skills/ are blocked.
    """
    # Strip leading memory/ prefix if present
    if path.startswith("memory/"):
        path = path[len("memory/"):]

    if _is_protected(path):
        return f"Error: writes to {path!r} are not allowed"

    if path.startswith("facts/") or path.startswith("people/"):
        return (
            f"Error: facts and people are now stored in Obsidian. "
            f"Use obsidian_create or obsidian_append with path "
            f"awfulclaw/{path} instead."
        )

    try:
        memory.write(path, content.strip())
    except ValueError as exc:
        return f"Error: {exc}"

    return f"Written to memory/{path}"


if __name__ == "__main__":
    mcp.run()
