"""Tests for MCP web_search server."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from awfulclaw.mcp.web import SearchResult, web_search


def _make_results(*titles: str) -> list[SearchResult]:
    return [
        SearchResult(title=t, url=f"https://example.com/{i}", snippet=f"Snippet {i}")
        for i, t in enumerate(titles)
    ]


def test_web_search_returns_results() -> None:
    results = _make_results("First Result", "Second Result")
    with patch("awfulclaw.mcp.web.search", return_value=results) as mock_search:
        output = web_search("python tutorials")
        mock_search.assert_called_once_with("python tutorials")
    assert "First Result" in output
    assert "Second Result" in output
    assert "python tutorials" in output


def test_web_search_no_results() -> None:
    with patch("awfulclaw.mcp.web.search", return_value=[]):
        output = web_search("xyzzy nothing here")
    assert "no results" in output.lower()


def test_web_search_includes_url_and_snippet() -> None:
    results = [SearchResult(title="Title", url="https://example.com/page", snippet="A snippet")]
    with patch("awfulclaw.mcp.web.search", return_value=results):
        output = web_search("test query")
    assert "https://example.com/page" in output
    assert "A snippet" in output


def test_web_search_handles_exception() -> None:
    with patch("awfulclaw.mcp.web.search", side_effect=RuntimeError("network error")):
        output = web_search("anything")
    assert "unavailable" in output.lower()
    assert "network error" in output


@pytest.mark.parametrize("query", ["hello world", "python 3.12 release notes"])
def test_web_search_query_in_header(query: str) -> None:
    results = _make_results("A Result")
    with patch("awfulclaw.mcp.web.search", return_value=results):
        output = web_search(query)
    assert query in output
