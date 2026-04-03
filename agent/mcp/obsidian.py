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

    Returns a confirmation string.
    """
    path = _note_path(title)
    content = _build_note(title, body, category)
    _atomic_write(path, content)
    return f"Written: {title}.md"


if __name__ == "__main__":
    mcp.run()
