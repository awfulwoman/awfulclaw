"""MCP server for web search via DuckDuckGo."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("web_search")


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


@mcp.tool()
def web_search(query: str) -> str:
    """Search the web using DuckDuckGo and return titles, URLs, and snippets.

    Use for current events, documentation, or anything not in memory.
    """
    try:
        results = search(query)
        if not results:
            return "[Web search returned no results]"
        lines = [f"[Web search results for: {query}]"]
        for r in results:
            lines.append(f"- {r.title}\n  {r.url}\n  {r.snippet}")
        return "\n\n".join(lines)
    except Exception as exc:
        return f"[Web search unavailable: {exc}]"


if __name__ == "__main__":
    mcp.run()
