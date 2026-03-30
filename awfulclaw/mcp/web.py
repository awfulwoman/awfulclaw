"""MCP server for web search via DuckDuckGo."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from awfulclaw.modules.web._web import search

mcp = FastMCP("web_search")


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
