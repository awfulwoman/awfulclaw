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
