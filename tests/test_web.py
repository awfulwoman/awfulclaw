"""Tests for web search module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from awfulclaw.web import SearchResult, search


def test_search_returns_results() -> None:
    mock_hits = [
        {"title": "Example", "href": "https://example.com", "body": "A snippet"},
        {"title": "Other", "href": "https://other.com", "body": "Another"},
    ]
    with patch("ddgs.DDGS") as mock_cls:
        ctx = MagicMock()
        ctx.text.return_value = mock_hits
        mock_cls.return_value.__enter__ = MagicMock(return_value=ctx)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)
        results = search("test query")

    assert len(results) == 2
    assert isinstance(results[0], SearchResult)
    assert results[0].title == "Example"
    assert results[0].url == "https://example.com"


def test_search_ddgs_exception_returns_empty() -> None:
    with patch("ddgs.DDGS") as mock_cls:
        from ddgs.exceptions import DDGSException

        ctx = MagicMock()
        ctx.text.side_effect = DDGSException("No results found.")
        mock_cls.return_value.__enter__ = MagicMock(return_value=ctx)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)
        results = search("obscure query no results")

    assert results == []


def test_search_other_exception_raises_runtime_error() -> None:
    with patch("ddgs.DDGS") as mock_cls:
        ctx = MagicMock()
        ctx.text.side_effect = ConnectionError("Network down")
        mock_cls.return_value.__enter__ = MagicMock(return_value=ctx)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        import pytest

        with pytest.raises(RuntimeError, match="DuckDuckGo search failed"):
            search("test")
