"""Tests for MCP memory_write server."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from awfulclaw.mcp.memory_write import memory_write


@pytest.fixture(autouse=True)
def tmp_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


def test_write_regular_file(tmp_path: Path) -> None:
    result = memory_write("USER.md", "Hello user")
    assert result == "Written to memory/USER.md"
    assert (tmp_path / "memory" / "USER.md").read_text() == "Hello user"


def test_write_strips_memory_prefix(tmp_path: Path) -> None:
    result = memory_write("memory/USER.md", "Hello")
    assert result == "Written to memory/USER.md"


def test_write_creates_subdirectory(tmp_path: Path) -> None:
    result = memory_write("tasks/myproject.md", "- [ ] do something")
    assert result == "Written to memory/tasks/myproject.md"
    assert (tmp_path / "memory" / "tasks" / "myproject.md").exists()


def test_write_facts_routes_to_sqlite() -> None:
    with patch("awfulclaw.mcp.memory_write.write_fact") as mock_write:
        result = memory_write("facts/location.md", "Paris")
        mock_write.assert_called_once_with("location", "Paris")
        assert result == "Written to memory/facts/location.md"


def test_write_people_routes_to_sqlite() -> None:
    with patch("awfulclaw.mcp.memory_write.write_person") as mock_write:
        result = memory_write("people/alice.md", "Alice info")
        mock_write.assert_called_once_with("alice", "Alice info")
        assert result == "Written to memory/people/alice.md"


def test_write_facts_strips_md_suffix() -> None:
    with patch("awfulclaw.mcp.memory_write.write_fact") as mock_write:
        memory_write("facts/weather", "Sunny")
        mock_write.assert_called_once_with("weather", "Sunny")


def test_blocked_soul_md() -> None:
    result = memory_write("SOUL.md", "evil override")
    assert "Error" in result
    assert "SOUL.md" in result


def test_blocked_heartbeat_md() -> None:
    result = memory_write("HEARTBEAT.md", "override")
    assert "Error" in result


def test_blocked_skills_dir() -> None:
    result = memory_write("skills/someskill.md", "content")
    assert "Error" in result


def test_path_traversal_rejected() -> None:
    result = memory_write("../evil.txt", "content")
    assert "Error" in result


def test_content_stripped(tmp_path: Path) -> None:
    memory_write("notes.md", "  hello world  \n")
    assert (tmp_path / "memory" / "notes.md").read_text() == "hello world"
