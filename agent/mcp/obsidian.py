# agent/mcp/obsidian.py
"""obsidian MCP server — read and write Obsidian vault notes.

Exposes:
  note_write(title, body, category?) — create or overwrite a note
  note_append(title, body)           — append to an existing note (creates if missing)
  note_read(title)                   — read a note by title
  note_search(query)                 — search note titles and content
  note_list(category?)               — list notes, optionally filtered by category

Run via stdio; configure with env var VAULT_PATH.

Vault conventions (from vault CLAUDE.md):
  - Notes live at vault root — no subfolders for organisation.
  - Organised via 'categories' frontmatter: e.g. categories: ["[[Meetings]]"].
  - Use wikilinks [[Note Title]] liberally for internal references.
  - Dates in YYYY-MM-DD format.
  - Ratings use a 7-point scale.
  - British English.
  - Avoid non-standard Markdown.
  - Task/to-do management is handled by the agent, not Obsidian.
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("obsidian")


def _get_vault_path() -> Path:
    raw = os.environ.get("VAULT_PATH", ".")
    return Path(raw).resolve()


def _note_path(title: str) -> Path:
    return _get_vault_path() / f"{title}.md"


def _atomic_write(path: Path, content: str) -> None:
    """Write content atomically: temp file in same dir, then os.rename()."""
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp_path.write_text(content, encoding="utf-8")
        os.rename(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _build_note(title: str, body: str, category: Optional[str]) -> str:
    today = date.today().strftime("%Y-%m-%d")
    if category:
        frontmatter = (
            f"---\n"
            f"created: {today}\n"
            f"categories:\n"
            f'  - "[[{category}]]"\n'
            f"tags:\n"
            f"  - note\n"
            f"  - journal\n"
            f"---\n"
        )
    else:
        frontmatter = (
            f"---\n"
            f"created: {today}\n"
            f"tags:\n"
            f"  - note\n"
            f"  - journal\n"
            f"---\n"
        )
    return frontmatter + body


@mcp.tool()
def note_write(title: str, body: str, category: Optional[str] = None) -> str:
    """Create or overwrite an Obsidian vault note.

    title:    Note title — becomes the filename ({title}.md) at the vault root.
    body:     Markdown content. Use [[Wikilinks]] for internal references.
              Dates in YYYY-MM-DD. British English. Ratings on a 7-point scale.
              Avoid non-standard Markdown (no Obsidian callouts, no templates syntax).
    category: Optional category for frontmatter (e.g. 'Meetings', 'Projects', 'People').
              Written as [[category]] wikilink. This is the primary organisational
              mechanism — do not use subfolders.

    Returns a confirmation string, or error message if validation fails or write fails.
    """
    vault_root = _get_vault_path()
    path = _note_path(title)

    # Validate path doesn't escape vault root via path traversal
    try:
        resolved = Path(os.path.realpath(path))
        resolved.relative_to(vault_root)
    except ValueError:
        return f"Rejected: path traversal detected in title {title!r}"

    content = _build_note(title, body, category)

    # Wrap atomic write in try/except to return error string on failure
    try:
        _atomic_write(path, content)
    except Exception as e:
        return f"Error writing note: {e}"

    return f"Written: {title}.md"


@mcp.tool()
def note_append(title: str, body: str) -> str:
    """Append text to an existing Obsidian vault note.

    title: Note title (without .md extension).
    body:  Markdown text to append. Use [[Wikilinks]] for internal references.
           Dates in YYYY-MM-DD. British English. Standard Markdown only.
           Good for: adding entries to a daily note, appending to a running log.

    If the note does not exist, creates it with default Journal Template frontmatter.
    Returns a confirmation string.
    """
    path = _note_path(title)
    # Path traversal guard
    vault = _get_vault_path()
    try:
        Path(os.path.realpath(path)).relative_to(vault)
    except ValueError:
        return f"Rejected: path traversal detected in title {title!r}"
    if not path.exists():
        content = _build_note(title, body, category=None)
        try:
            _atomic_write(path, content)
        except Exception as e:
            return f"Error writing note: {e}"
        return f"Created and written: {title}.md"
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(body)
    except Exception as e:
        return f"Error appending to note: {e}"
    return f"Appended to: {title}.md"


@mcp.tool()
def note_read(title: str) -> str:
    """Read an Obsidian vault note by title.

    title: Note title (without .md extension). If unsure of the exact title,
           use note_search first to find it.

    Returns the full file contents including frontmatter, or an error message if not found.
    """
    path = _note_path(title)
    vault = _get_vault_path()
    try:
        Path(os.path.realpath(path)).relative_to(vault)
    except ValueError:
        return f"Rejected: path traversal detected in title {title!r}"
    if not path.exists():
        return f"Not found: {title!r}"
    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading note: {e}"


@mcp.tool()
def note_search(query: str) -> list[dict]:
    """Search Obsidian vault notes by title and content.

    query: Search string (case-insensitive). Use this to find a note before
           reading or appending when the exact title is uncertain.

    Returns a list of dicts with keys: title, snippet.
    snippet is the first matching line (content match) or the note title (title match).
    Returns an empty list if no matches found.
    """
    vault = _get_vault_path()
    query_lower = query.lower()
    results: list[dict] = []
    seen: set[str] = set()

    for md_file in sorted(vault.glob("*.md")):
        title = md_file.stem
        # Title match
        if query_lower in title.lower():
            results.append({"title": title, "snippet": title})
            seen.add(title)
            continue
        # Content match — find first matching line
        try:
            for line in md_file.read_text(encoding="utf-8").splitlines():
                if query_lower in line.lower():
                    if title not in seen:
                        results.append({"title": title, "snippet": line.strip()})
                        seen.add(title)
                    break
        except OSError:
            continue

    return results


if __name__ == "__main__":
    mcp.run()
