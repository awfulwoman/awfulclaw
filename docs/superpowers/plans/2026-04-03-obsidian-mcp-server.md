# Obsidian MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an MCP server that lets Claude read and write Obsidian vault notes mid-conversation, respecting the vault's organisation conventions.

**Architecture:** A `FastMCP` stdio server (`agent/mcp/obsidian.py`) exposing five tools — `note_write`, `note_append`, `note_read`, `note_search`, `note_list`. All notes live at the vault root (no subfolders); writes use atomic temp-file + rename. Configured via `VAULT_PATH` env var and registered in `config/mcp_servers.json`.

**Tech Stack:** Python, `mcp.server.fastmcp.FastMCP`, `pathlib`, `os.rename` for atomic writes, `pytest` + `tmp_path` for tests.

---

## File map

| File | Status | Responsibility |
|------|--------|----------------|
| `agent/mcp/obsidian.py` | Create | MCP server: all five tools + vault path helper |
| `tests/test_mcp_obsidian.py` | Create | Unit tests for all tools |
| `config/mcp_servers.json` | Modify | Register `obsidian` server with `VAULT_PATH` |

---

### Task 1: `note_write` — create or overwrite a vault note

**Files:**
- Create: `agent/mcp/obsidian.py`
- Create: `tests/test_mcp_obsidian.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mcp_obsidian.py
"""Unit tests for agent/mcp/obsidian.py"""
from __future__ import annotations

from pathlib import Path

import pytest

import agent.mcp.obsidian as obs


def _setup_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    return tmp_path


def test_note_write_creates_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = _setup_vault(tmp_path, monkeypatch)
    result = obs.note_write("My Note", "Hello world")
    assert result == "Written: My Note.md"
    assert (vault / "My Note.md").exists()


def test_note_write_includes_default_frontmatter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _setup_vault(tmp_path, monkeypatch)
    obs.note_write("Test Note", "body text")
    content = (vault / "Test Note.md").read_text()
    assert "created:" in content
    assert "tags:" in content
    assert "- note" in content
    assert "- journal" in content
    assert "body text" in content


def test_note_write_with_category_includes_wikilink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _setup_vault(tmp_path, monkeypatch)
    obs.note_write("Meeting Note", "discussed things", category="Meetings")
    content = (vault / "Meeting Note.md").read_text()
    assert '[[Meetings]]' in content


def test_note_write_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Temp file must not linger after write."""
    vault = _setup_vault(tmp_path, monkeypatch)
    obs.note_write("Atomic Test", "content")
    tmp_files = list(vault.glob("*.tmp"))
    assert tmp_files == []


def test_note_write_overwrites_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _setup_vault(tmp_path, monkeypatch)
    (vault / "Existing.md").write_text("old content")
    obs.note_write("Existing", "new content")
    assert "new content" in (vault / "Existing.md").read_text()
    assert "old content" not in (vault / "Existing.md").read_text()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/test_mcp_obsidian.py -v
```

Expected: `ModuleNotFoundError` or `AttributeError` — `agent.mcp.obsidian` doesn't exist yet.

- [ ] **Step 3: Implement `note_write`**

```python
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
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/test_mcp_obsidian.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/mcp/obsidian.py tests/test_mcp_obsidian.py
git commit -m "feat: add obsidian MCP server with note_write tool"
```

---

### Task 2: `note_append` — append to an existing note

**Files:**
- Modify: `agent/mcp/obsidian.py`
- Modify: `tests/test_mcp_obsidian.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mcp_obsidian.py`:

```python
def test_note_append_adds_to_existing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = _setup_vault(tmp_path, monkeypatch)
    (vault / "Running Log.md").write_text("# Running Log\n\nFirst entry.")
    result = obs.note_append("Running Log", "\nSecond entry.")
    assert result == "Appended to: Running Log.md"
    content = (vault / "Running Log.md").read_text()
    assert "First entry." in content
    assert "Second entry." in content


def test_note_append_creates_if_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = _setup_vault(tmp_path, monkeypatch)
    result = obs.note_append("Brand New", "first content")
    assert "Brand New.md" in result
    assert (vault / "Brand New.md").exists()
    assert "first content" in (vault / "Brand New.md").read_text()


def test_note_append_preserves_original_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _setup_vault(tmp_path, monkeypatch)
    obs.note_write("My Note", "original body")
    obs.note_append("My Note", "\nextra line")
    content = (vault / "My Note.md").read_text()
    assert "original body" in content
    assert "extra line" in content
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/test_mcp_obsidian.py::test_note_append_adds_to_existing -v
```

Expected: `AttributeError: module 'agent.mcp.obsidian' has no attribute 'note_append'`

- [ ] **Step 3: Implement `note_append`**

Add to `agent/mcp/obsidian.py` after `note_write`, before the `if __name__` block:

```python
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
    if not path.exists():
        content = _build_note(title, body, category=None)
        _atomic_write(path, content)
        return f"Created and written: {title}.md"
    with path.open("a", encoding="utf-8") as f:
        f.write(body)
    return f"Appended to: {title}.md"
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/test_mcp_obsidian.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/mcp/obsidian.py tests/test_mcp_obsidian.py
git commit -m "feat: add note_append tool to obsidian MCP server"
```

---

### Task 3: `note_read` — read a note by title


**Files:**
- Modify: `agent/mcp/obsidian.py`
- Modify: `tests/test_mcp_obsidian.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mcp_obsidian.py`:

```python
def test_note_read_existing_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = _setup_vault(tmp_path, monkeypatch)
    (vault / "Hello.md").write_text("# Hello\n\ncontent here")
    result = obs.note_read("Hello")
    assert result == "# Hello\n\ncontent here"


def test_note_read_missing_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_vault(tmp_path, monkeypatch)
    result = obs.note_read("Does Not Exist")
    assert "Not found" in result


def test_note_read_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Write then read should return the same content."""
    _setup_vault(tmp_path, monkeypatch)
    obs.note_write("Roundtrip", "some body text")
    content = obs.note_read("Roundtrip")
    assert "some body text" in content
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/test_mcp_obsidian.py::test_note_read_existing_note -v
```

Expected: `AttributeError: module 'agent.mcp.obsidian' has no attribute 'note_read'`

- [ ] **Step 3: Implement `note_read`**

Add to `agent/mcp/obsidian.py` before the `if __name__` block:

```python
@mcp.tool()
def note_read(title: str) -> str:
    """Read an Obsidian vault note by title.

    title: Note title (without .md extension). If unsure of the exact title,
           use note_search first to find it.

    Returns the full file contents including frontmatter, or an error message if not found.
    """
    path = _note_path(title)
    if not path.exists():
        return f"Not found: {title!r}"
    return path.read_text(encoding="utf-8")
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/test_mcp_obsidian.py -v
```

Expected: all 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/mcp/obsidian.py tests/test_mcp_obsidian.py
git commit -m "feat: add note_read tool to obsidian MCP server"
```

---

### Task 4: `note_search` — search by title and content

**Files:**
- Modify: `agent/mcp/obsidian.py`
- Modify: `tests/test_mcp_obsidian.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mcp_obsidian.py`:

```python
def test_note_search_matches_title(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = _setup_vault(tmp_path, monkeypatch)
    (vault / "Berlin Trip.md").write_text("notes about berlin")
    (vault / "London Notes.md").write_text("notes about london")
    results = obs.note_search("Berlin")
    titles = [r["title"] for r in results]
    assert "Berlin Trip" in titles
    assert "London Notes" not in titles


def test_note_search_matches_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = _setup_vault(tmp_path, monkeypatch)
    (vault / "Random.md").write_text("I saw a penguin today")
    (vault / "Other.md").write_text("nothing interesting here")
    results = obs.note_search("penguin")
    titles = [r["title"] for r in results]
    assert "Random" in titles
    assert "Other" not in titles


def test_note_search_no_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = _setup_vault(tmp_path, monkeypatch)
    (vault / "Unrelated.md").write_text("completely different")
    results = obs.note_search("zzznomatchzzz")
    assert results == []


def test_note_search_returns_snippet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = _setup_vault(tmp_path, monkeypatch)
    (vault / "Snippet Test.md").write_text("line one\nthe keyword is here\nline three")
    results = obs.note_search("keyword")
    assert len(results) == 1
    assert "keyword" in results[0]["snippet"]
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/test_mcp_obsidian.py::test_note_search_matches_title -v
```

Expected: `AttributeError: module 'agent.mcp.obsidian' has no attribute 'note_search'`

- [ ] **Step 3: Implement `note_search`**

Add to `agent/mcp/obsidian.py` before the `if __name__` block:

```python
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
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/test_mcp_obsidian.py -v
```

Expected: all 15 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/mcp/obsidian.py tests/test_mcp_obsidian.py
git commit -m "feat: add note_search tool to obsidian MCP server"
```

---

### Task 5: `note_list` — list all notes, optionally by category

**Files:**
- Modify: `agent/mcp/obsidian.py`
- Modify: `tests/test_mcp_obsidian.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mcp_obsidian.py`:

```python
def test_note_list_returns_all_notes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = _setup_vault(tmp_path, monkeypatch)
    (vault / "Alpha.md").write_text("a")
    (vault / "Beta.md").write_text("b")
    results = obs.note_list()
    assert "Alpha" in results
    assert "Beta" in results


def test_note_list_filters_by_category(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = _setup_vault(tmp_path, monkeypatch)
    (vault / "Meeting One.md").write_text(
        '---\ncategories:\n  - "[[Meetings]]"\n---\nbody'
    )
    (vault / "Personal Note.md").write_text(
        '---\ncategories:\n  - "[[Journal]]"\n---\nbody'
    )
    results = obs.note_list(category="Meetings")
    assert "Meeting One" in results
    assert "Personal Note" not in results


def test_note_list_empty_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_vault(tmp_path, monkeypatch)
    results = obs.note_list()
    assert results == []
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/test_mcp_obsidian.py::test_note_list_returns_all_notes -v
```

Expected: `AttributeError: module 'agent.mcp.obsidian' has no attribute 'note_list'`

- [ ] **Step 3: Implement `note_list`**

Add to `agent/mcp/obsidian.py` before the `if __name__` block:

```python
@mcp.tool()
def note_list(category: Optional[str] = None) -> list[str]:
    """List Obsidian vault notes, optionally filtered by category.

    category: If provided, only return notes whose frontmatter categories
              include [[category]]. Common categories: Meetings, Projects,
              People, Journal. Categories are the primary organisational
              structure — there are no subfolders.

    Returns a sorted list of note titles (without .md extension).
    """
    vault = _get_vault_path()
    titles: list[str] = []

    for md_file in sorted(vault.glob("*.md")):
        if category is not None:
            try:
                content = md_file.read_text(encoding="utf-8")
                if f"[[{category}]]" not in content:
                    continue
            except OSError:
                continue
        titles.append(md_file.stem)

    return titles
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/test_mcp_obsidian.py -v
```

Expected: all 18 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/mcp/obsidian.py tests/test_mcp_obsidian.py
git commit -m "feat: add note_list tool to obsidian MCP server"
```

---

### Task 6: Register in `config/mcp_servers.json`

**Files:**
- Modify: `config/mcp_servers.json`

- [ ] **Step 1: Add the obsidian server entry**

In `config/mcp_servers.json`, add after the last server entry (before the closing `}`):

```json
    "obsidian": {
      "command": "/opt/homebrew/bin/uv",
      "args": ["run", "python", "-m", "agent.mcp.obsidian"],
      "env": {
        "VAULT_PATH": "/Users/charlie/Code/obsidian"
      }
    }
```

- [ ] **Step 2: Run the full test suite to confirm nothing is broken**

```bash
uv run pytest tests/test_mcp_obsidian.py -v
```

Expected: all 18 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add config/mcp_servers.json
git commit -m "feat: register obsidian MCP server in mcp_servers.json"
```

---

## Self-review

**Spec coverage:**
- `note_write` with Journal Template frontmatter ✓
- `note_write` with category as wikilink ✓
- `note_append` to existing note ✓
- `note_append` creates note if missing ✓
- `note_read` by title ✓
- `note_search` title + content ✓
- `note_list` with optional category filter ✓
- Atomic writes ✓
- Vault path from env var ✓
- Registered in `mcp_servers.json` ✓

**Placeholder scan:** No TBDs, no "handle edge cases", all test code is concrete.

**Type consistency:** `note_write` returns `str`, `note_search` returns `list[dict]`, `note_list` returns `list[str]`, `note_read` returns `str` — consistent across all tasks.
