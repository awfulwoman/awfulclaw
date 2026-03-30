"""Tests for MCP memory_search server."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from awfulclaw_mcp.search import memory_search


@pytest.fixture(autouse=True)
def _patch_deps(tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("awfulclaw_mcp.search.search_facts", lambda q: [])
    monkeypatch.setattr("awfulclaw_mcp.search.search_people", lambda q: [])
    monkeypatch.setattr("awfulclaw_mcp.search.memory.search_all", lambda q, subdirs=None: [])
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.execute.return_value.fetchall.return_value = []
    monkeypatch.setattr("awfulclaw_mcp.search.get_db", lambda: mock_conn)


def test_no_matches() -> None:
    result = memory_search("xyzzy nothing here")
    assert "No matches found" in result
    assert "xyzzy nothing here" in result


def test_facts_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "awfulclaw_mcp.search.search_facts",
        lambda q: [("facts/location", "Paris")],
    )
    result = memory_search("location")
    assert "facts/location" in result
    assert "Paris" in result


def test_people_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "awfulclaw_mcp.search.search_people",
        lambda q: [("people/alice", "Alice Smith")],
    )
    result = memory_search("alice")
    assert "people/alice" in result
    assert "Alice Smith" in result


def test_memory_file_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "awfulclaw_mcp.search.memory.search_all",
        lambda q, subdirs=None: [("tasks/todo.md", "Buy milk")],
    )
    result = memory_search("milk")
    assert "tasks/todo.md" in result
    assert "Buy milk" in result


def test_conversation_results(monkeypatch: pytest.MonkeyPatch) -> None:
    row = MagicMock()
    row.__getitem__ = lambda self, key: {
        "content": "I love Python",
        "timestamp": "2026-01-01T00:00:00Z",
        "role": "user",
    }[key]
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.execute.return_value.fetchall.return_value = [row]
    monkeypatch.setattr("awfulclaw_mcp.search.get_db", lambda: mock_conn)
    result = memory_search("Python")
    assert "conversations" in result


def test_header_contains_query() -> None:
    result = memory_search("no results query")
    assert "no results query" in result


def test_db_exception_silenced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "awfulclaw_mcp.search.memory.search_all",
        lambda q, subdirs=None: [("tasks/a.md", "a line")],
    )
    def _raise() -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr("awfulclaw_mcp.search.get_db", _raise)
    result = memory_search("a line")
    assert "tasks/a.md" in result
