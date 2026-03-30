"""Configuration loaded from environment / .env file."""

import os
from datetime import time

from dotenv import load_dotenv

from awfulclaw.connector import Connector

load_dotenv()


def get_channel() -> str:
    return os.getenv("AWFULCLAW_CHANNEL", "telegram").lower()


def get_connector() -> Connector:
    channel = get_channel()
    if channel == "telegram":
        from awfulclaw.telegram import TelegramConnector

        return TelegramConnector()
    raise RuntimeError(
        f"Unrecognised AWFULCLAW_CHANNEL value: {channel!r}. "
        "Valid options: telegram"
    )


def get_model() -> str:
    return os.getenv("AWFULCLAW_MODEL", "claude-sonnet-4-6")


def get_allowed_tools() -> list[str]:
    """Return list of allowed Claude tools from env, or sensible default."""
    raw = os.getenv("AWFULCLAW_ALLOWED_TOOLS", "").strip()
    if raw:
        return [t.strip() for t in raw.split(",") if t.strip()]
    return [
        "Read(memory/**)",
        "Write(memory/**)",
        "Edit(memory/**)",
        "WebSearch",
        "WebFetch",
        "mcp__memory_write__memory_write",
        "mcp__memory_search__memory_search",
        "mcp__schedule__schedule_create",
        "mcp__schedule__schedule_delete",
        "mcp__schedule__schedule_list",
        "mcp__imap_read__imap_read",
        "mcp__skills__skill_read",
        "mcp__mcp_manager__mcp_server_list",
        "mcp__mcp_manager__mcp_server_add",
        "mcp__mcp_manager__mcp_server_add_from_github",
        "mcp__mcp_manager__mcp_server_remove",
    ]


def get_sandbox() -> bool:
    """Return True if AWFULCLAW_SANDBOX=1 is set."""
    return os.getenv("AWFULCLAW_SANDBOX", "0").strip() == "1"


def get_poll_interval() -> int:
    return int(os.getenv("AWFULCLAW_POLL_INTERVAL", "5"))


def get_idle_interval() -> int:
    return int(os.getenv("AWFULCLAW_IDLE_INTERVAL", "60"))


def get_idle_nudge_cooldown() -> int:
    """Minimum seconds between unsolicited idle messages. Default: 24h."""
    return int(os.getenv("AWFULCLAW_IDLE_NUDGE_COOLDOWN", str(60 * 60 * 24)))


def get_briefing_time() -> time | None:
    """Return configured briefing time in UTC, or None if not set."""
    raw = os.getenv("AWFULCLAW_BRIEFING_TIME", "").strip()
    if not raw:
        return None
    try:
        parts = raw.split(":")
        return time(int(parts[0]), int(parts[1]))
    except (ValueError, IndexError):
        return None
