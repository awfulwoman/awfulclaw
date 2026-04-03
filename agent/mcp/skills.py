"""skills MCP server — read-only skill prompt fragments.

Exposes two tools:
  skill_list() — returns filenames in config/skills/
  skill_read(name) — returns content of the named skill file

Paths with '..' or absolute paths are rejected.

Run via stdio; configure with env var SKILLS_DIR.
"""
from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("skills")


def _get_skills_dir() -> Path:
    raw = os.environ.get("SKILLS_DIR", "config/skills")
    return Path(raw)


def _validate_name(name: str) -> str | None:
    """Return error string if name is invalid, else None."""
    if os.path.isabs(name):
        return f"Rejected: absolute path not allowed: {name!r}"
    if ".." in Path(name).parts:
        return f"Rejected: path traversal not allowed: {name!r}"
    return None


@mcp.tool()
def skill_list() -> list[str]:
    """Return the list of skill filenames in config/skills/."""
    skills_dir = _get_skills_dir()
    if not skills_dir.exists():
        return []
    return sorted(f.name for f in skills_dir.iterdir() if f.is_file())


@mcp.tool()
def skill_read(name: str) -> str:
    """Return the content of a skill file by name.

    Rejects paths with '..' or absolute paths.
    Returns an error message (not an exception) for denied or missing paths.
    """
    error = _validate_name(name)
    if error:
        return error

    skills_dir = _get_skills_dir()
    skill_path = (skills_dir / name).resolve()
    skills_dir_resolved = skills_dir.resolve()

    # Confirm resolved path is inside skills dir
    try:
        skill_path.relative_to(skills_dir_resolved)
    except ValueError:
        return f"Rejected: path outside skills directory: {name!r}"

    if not skill_path.exists():
        return f"Not found: {name!r}"

    return skill_path.read_text()


if __name__ == "__main__":
    mcp.run()
