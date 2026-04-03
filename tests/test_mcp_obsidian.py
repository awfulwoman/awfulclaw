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


def test_note_write_rejects_path_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Path traversal attempts should be rejected."""
    vault = _setup_vault(tmp_path, monkeypatch)
    result = obs.note_write("../../etc/passwd", "malicious")
    assert isinstance(result, str)
    assert "Rejected" in result
    # File should NOT be created outside vault
    assert not (tmp_path.parent / "etc" / "passwd.md").exists()


def test_note_write_returns_error_string_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Write failures should return error string, not raise exception."""
    vault = _setup_vault(tmp_path, monkeypatch)
    # Make vault read-only to trigger write failure
    vault.chmod(0o555)
    try:
        result = obs.note_write("Test Note", "body")
        assert isinstance(result, str)
        assert "Error" in result
    finally:
        # Restore permissions for cleanup
        vault.chmod(0o755)


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
