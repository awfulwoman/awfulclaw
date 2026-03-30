"""Web search skill — uses DuckDuckGo (no API key required)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


def search(query: str, max_results: int = 5) -> list[SearchResult]:
    """Search DuckDuckGo, return up to max_results results."""
    try:
        from ddgs import DDGS  # type: ignore[import-untyped]
        from ddgs.exceptions import DDGSException  # type: ignore[import-untyped]

        try:
            with DDGS() as ddgs:
                hits: list[dict[str, Any]] = ddgs.text(query, max_results=max_results)  # type: ignore[assignment]
        except DDGSException:
            return []
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
