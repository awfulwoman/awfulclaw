"""MCP server for reading skill prompt fragments from config/skills/."""

from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("skills")

_SKILLS_DIR = Path("config/skills")


def _available_skill_names() -> list[str]:
    if not _SKILLS_DIR.exists():
        return []
    return sorted(f.stem for f in _SKILLS_DIR.glob("*.md"))


@mcp.tool()
def skill_read(name: str) -> str:
    """Read a skill prompt fragment from config/skills/{name}.md.

    Returns the full content of the skill file.
    Use when the system prompt lists an available skill you want to apply.
    """
    if name.endswith(".md"):
        name = name[:-3]

    path = _SKILLS_DIR / f"{name}.md"
    if not path.exists():
        available = _available_skill_names()
        if available:
            return f"Skill {name!r} not found. Available: {', '.join(available)}"
        return f"Skill {name!r} not found. No skills are available."

    return path.read_text(encoding="utf-8")


if __name__ == "__main__":
    mcp.run()
