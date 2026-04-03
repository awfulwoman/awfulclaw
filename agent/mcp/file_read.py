"""file_read MCP server — project-scoped file reading.

Exposes one tool:
  file_read(path) — returns file contents as text

Path restrictions:
  - Resolved via os.path.realpath; must be inside project root
  - .env is always denied even when inside the project
  - Symlink escapes are caught by realpath resolution

Run via stdio; configure with env var PROJECT_ROOT.
"""
from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("file_read")


def _get_project_root() -> Path:
    raw = os.environ.get("PROJECT_ROOT", ".")
    return Path(raw).resolve()


def _check_path(path: str) -> tuple[Path, str | None]:
    """Resolve path and check it's allowed.

    Returns (resolved_path, error_message). error_message is None if allowed.
    """
    project_root = _get_project_root()

    # Resolve relative to project root if not absolute
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = project_root / candidate

    resolved = Path(os.path.realpath(candidate))

    # Reject .env regardless of location
    if resolved.name == ".env":
        return resolved, f"Rejected: .env is not readable: {path!r}"

    # Must be inside project root
    try:
        resolved.relative_to(project_root)
    except ValueError:
        return resolved, f"Rejected: path outside project directory: {path!r}"

    return resolved, None


@mcp.tool()
def file_read(path: str) -> str:
    """Return the contents of a project file as text.

    Rejects .env and any path that resolves outside the project directory.
    Returns an error message (not an exception) for denied or missing paths.
    """
    resolved, error = _check_path(path)
    if error:
        return error

    if not resolved.exists():
        return f"Not found: {path!r}"

    if not resolved.is_file():
        return f"Not a file: {path!r}"

    return resolved.read_text()


if __name__ == "__main__":
    mcp.run()
