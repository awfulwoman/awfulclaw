"""Web search skill — uses DuckDuckGo Instant Answer API (no key required)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_DDG_URL = "https://api.duckduckgo.com/"


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


def search(query: str) -> list[SearchResult]:
    """Search using DuckDuckGo Instant Answer API, return up to 5 results."""
    try:
        resp = httpx.get(
            _DDG_URL,
            params={"q": query, "format": "json", "no_redirect": "1", "no_html": "1"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        raise RuntimeError(f"DuckDuckGo request failed: {exc}") from exc

    results: list[SearchResult] = []

    # RelatedTopics is the main source of results
    for item in data.get("RelatedTopics", []):
        if len(results) >= 5:
            break
        # Topics can be nested under a "Topics" key (grouped results)
        if "Topics" in item:
            for sub in item["Topics"]:
                if len(results) >= 5:
                    break
                result = _extract_result(sub)
                if result:
                    results.append(result)
        else:
            result = _extract_result(item)
            if result:
                results.append(result)

    return results


def _extract_result(item: dict[str, object]) -> SearchResult | None:
    text = str(item.get("Text", "")).strip()
    url = str(item.get("FirstURL", "")).strip()
    if not text or not url:
        return None
    # Split "Title - snippet" format DDG uses
    if " - " in text:
        title, _, snippet = text.partition(" - ")
    else:
        title = text[:60]
        snippet = text
    return SearchResult(title=title.strip(), url=url, snippet=snippet.strip())
