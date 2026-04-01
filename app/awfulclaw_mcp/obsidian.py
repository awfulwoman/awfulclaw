"""MCP server for Obsidian via the obsidian CLI."""

from __future__ import annotations

import os
import subprocess

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("obsidian")

_VAULT = os.getenv("OBSIDIAN_VAULT", "").strip()


# Commands that require the Obsidian app to be running get a longer timeout.
_APP_COMMANDS = {
    "append", "prepend", "create", "delete", "move", "rename",
    "daily:append", "daily:prepend",
    "bookmark",
    "task",
    "property:set", "property:remove",
}


def _run(*args: str) -> str:
    """Run an obsidian CLI command and return stdout, or an error string."""
    cmd = ["obsidian"]
    if _VAULT:
        cmd.append(f"vault={_VAULT}")
    cmd.extend(args)
    command = args[0] if args else ""
    timeout = 30 if command in _APP_COMMANDS else 10
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        output = result.stdout.strip()
        err = result.stderr.strip()
        if result.returncode != 0:
            return f"[obsidian error: {err or 'non-zero exit'}]"
        return output or "[no output]"
    except FileNotFoundError:
        return "[obsidian error: CLI not found in PATH]"
    except subprocess.TimeoutExpired:
        return f"[obsidian error: timed out after {timeout}s — Obsidian may not be running]"


@mcp.tool()
def obsidian_read(path: str) -> str:
    """Read the contents of a note by file path (e.g. 'Journal/2024-01-01.md') or name.

    Args:
        path: Exact vault-relative file path, or just a note name for fuzzy match.
    """
    return _run("read", f"path={path}")


@mcp.tool()
def obsidian_create(path: str, content: str = "", overwrite: bool = False) -> str:
    """Create a new note. Fails if the note already exists unless overwrite=True.

    Args:
        path: Vault-relative file path (e.g. 'Journal/2024-01-01.md').
        content: Initial note content (markdown).
        overwrite: If True, overwrite an existing note.
    """
    args = ["create", f"path={path}", f"content={content}"]
    if overwrite:
        args.append("overwrite")
    return _run(*args)


@mcp.tool()
def obsidian_append(path: str, content: str) -> str:
    """Append content to an existing note.

    Args:
        path: Vault-relative file path or note name.
        content: Markdown content to append. Use \\n for newlines.
    """
    return _run("append", f"path={path}", f"content={content}")


@mcp.tool()
def obsidian_search(query: str, folder: str = "", limit: int = 20) -> str:
    """Search the vault for notes matching a text query.

    Args:
        query: Full-text search query.
        folder: Limit search to this vault-relative folder (optional).
        limit: Max number of results (default 20).
    """
    args = ["search:context", f"query={query}", f"limit={limit}", "format=json"]
    if folder:
        args.append(f"path={folder}")
    return _run(*args)


@mcp.tool()
def obsidian_daily_read() -> str:
    """Read today's daily note."""
    return _run("daily:read")


@mcp.tool()
def obsidian_daily_append(content: str) -> str:
    """Append content to today's daily note. Creates the note if it doesn't exist.

    Args:
        content: Markdown content to append. Use \\n for newlines.
    """
    return _run("daily:append", f"content={content}")


@mcp.tool()
def obsidian_tasks(
    todo_only: bool = True,
    file: str = "",
    folder: str = "",
) -> str:
    """List tasks (checkboxes) in the vault.

    Args:
        todo_only: If True (default), return only incomplete tasks. Set False for all.
        file: Filter to tasks in a specific note (name or path).
        folder: Filter to tasks under a specific folder path.
    """
    args = ["tasks", "format=json"]
    if todo_only:
        args.append("todo")
    if file:
        args.append(f"file={file}")
    if folder:
        args.append(f"path={folder}")
    return _run(*args)


@mcp.tool()
def obsidian_task_toggle(path: str, line: int) -> str:
    """Toggle a task's done/todo status by file path and line number.

    Use obsidian_tasks with verbose=True first to get the path:line reference.

    Args:
        path: Vault-relative file path of the note containing the task.
        line: Line number of the task (1-indexed).
    """
    return _run("task", f"ref={path}:{line}", "toggle")


@mcp.tool()
def obsidian_files(folder: str = "") -> str:
    """List markdown files in the vault, optionally filtered to a folder.

    Args:
        folder: Vault-relative folder path to filter by (optional).
    """
    args = ["files", "ext=md"]
    if folder:
        args.append(f"folder={folder}")
    return _run(*args)


@mcp.tool()
def obsidian_bookmarks() -> str:
    """List all bookmarks in the vault."""
    return _run("bookmarks", "verbose", "format=json")


@mcp.tool()
def obsidian_bookmark_add(title: str, file: str = "", url: str = "") -> str:
    """Add a bookmark. Provide either a file path or a URL.

    Args:
        title: Bookmark title/label.
        file: Vault-relative file path to bookmark (optional).
        url: External URL to bookmark (optional).
    """
    args = ["bookmark", f"title={title}"]
    if file:
        args.append(f"file={file}")
    if url:
        args.append(f"url={url}")
    return _run(*args)


if __name__ == "__main__":
    mcp.run()
