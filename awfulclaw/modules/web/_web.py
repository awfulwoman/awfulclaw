"""Web search module — uses DuckDuckGo (no API key required)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from awfulclaw.modules.base import Module, SkillTag

logger = logging.getLogger(__name__)

_SKILL_WEB_RE = re.compile(r'<skill:web\s+query="([^"]*?)"\s*/?>')


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


class WebModule(Module):
    @property
    def name(self) -> str:
        return "web"

    @property
    def skill_tags(self) -> list[SkillTag]:
        return [
            SkillTag(
                name="web",
                pattern=_SKILL_WEB_RE,
                description="Search the web using DuckDuckGo",
                usage='<skill:web query="..."/>',
            )
        ]

    @property
    def system_prompt_fragment(self) -> str:
        return """\
### Web Search
Search the web with:
```
<skill:web query="search terms"/>
```
Returns titles, URLs, and snippets from DuckDuckGo.
Use for current events, documentation, or anything not in memory."""

    def dispatch(self, tag_match: re.Match[str], history: list[dict[str, str]], system: str) -> str:
        query = tag_match.group(1)
        try:
            results = search(query)
            if not results:
                return "[Web search returned no results]"
            lines = [f"[Web search results for: {query}]"]
            for r in results:
                lines.append(f"- {r.title}\n  {r.url}\n  {r.snippet}")
            return "\n\n".join(lines)
        except Exception as exc:
            logger.warning("Web search error: %s", exc)
            return f"[Web search unavailable: {exc}]"

    def is_available(self) -> bool:
        try:
            import ddgs  # type: ignore[import-untyped]  # noqa: F401

            return True
        except ImportError:
            return False
