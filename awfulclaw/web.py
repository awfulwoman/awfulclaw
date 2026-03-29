"""Web search skill — uses DuckDuckGo (no API key required)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


def search(query: str, max_results: int = 5) -> list[SearchResult]:
    """Search DuckDuckGo, return up to max_results results."""
    try:
        from ddgs import DDGS

        with DDGS() as ddgs:
            hits = ddgs.text(query, max_results=max_results)
    except Exception as exc:
        raise RuntimeError(f"DuckDuckGo search failed: {exc}") from exc

    return [
        SearchResult(
            title=h.get("title", ""),
            url=h.get("href", ""),
            snippet=h.get("body", ""),
        )
        for h in (hits or [])
    ]
