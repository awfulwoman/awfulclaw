"""MCP server for reading emails via IMAP."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from awfulclaw.modules.imap._imap import fetch_unread

mcp = FastMCP("imap_read")


@mcp.tool()
def imap_read() -> str:
    """Fetch unread emails from INBOX via IMAP.

    Returns a summary of unread messages. Only works when IMAP env vars are configured
    (IMAP_HOST, IMAP_USER, IMAP_PASSWORD).
    """
    try:
        emails = fetch_unread()
        if not emails:
            return "[No new emails]"
        lines = [f"[{len(emails)} new email(s):]"]
        for e in emails:
            lines.append(
                f"From: {e.from_addr}\nSubject: {e.subject}\n"
                f"Date: {e.timestamp.isoformat()}\n{e.body_preview}"
            )
        return "\n\n".join(lines)
    except Exception as exc:
        return f"[IMAP unavailable: {exc}]"


if __name__ == "__main__":
    mcp.run()
