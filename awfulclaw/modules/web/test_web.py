"""Tests for web search module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from awfulclaw.modules.web._web import SearchResult, WebModule, search


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

        with pytest.raises(RuntimeError, match="DuckDuckGo search failed"):
            search("test")


def test_web_module_dispatch_returns_formatted() -> None:
    mod = WebModule()
    mock_hits = [
        {"title": "Python Docs", "href": "https://docs.python.org", "body": "Official docs"},
    ]
    with patch("ddgs.DDGS") as mock_cls:
        ctx = MagicMock()
        ctx.text.return_value = mock_hits
        mock_cls.return_value.__enter__ = MagicMock(return_value=ctx)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)
        tag = mod.skill_tags[0]
        raw = '<skill:web query="python"/>'
        m = tag.pattern.match(raw)
        assert m is not None
        result = mod.dispatch(m, [], "")

    assert "Python Docs" in result
    assert "docs.python.org" in result


def test_web_module_dispatch_no_results() -> None:
    mod = WebModule()
    with patch("ddgs.DDGS") as mock_cls:
        ctx = MagicMock()
        ctx.text.return_value = []
        mock_cls.return_value.__enter__ = MagicMock(return_value=ctx)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)
        tag = mod.skill_tags[0]
        m = tag.pattern.match('<skill:web query="nothing"/>')
        assert m is not None
        result = mod.dispatch(m, [], "")

    assert "no results" in result.lower()


def test_web_module_is_available() -> None:
    mod = WebModule()
    # ddgs is installed in dev deps, so should be True in test env
    assert mod.is_available() is True


def test_web_module_is_available_false_when_no_ddgs() -> None:
    mod = WebModule()
    with patch.dict("sys.modules", {"ddgs": None}):
        assert mod.is_available() is False
