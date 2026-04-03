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
