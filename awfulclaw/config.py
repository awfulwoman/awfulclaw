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


def get_poll_interval() -> int:
    return int(os.getenv("AWFULCLAW_POLL_INTERVAL", "5"))


def get_idle_interval() -> int:
    return int(os.getenv("AWFULCLAW_IDLE_INTERVAL", "60"))


def get_allowed_tools() -> list[str]:
    """Return the list of tools Claude is allowed to use, or [] to add no restriction."""
    raw = os.getenv("AWFULCLAW_ALLOWED_TOOLS", "Read,Write,Edit").strip()
    if not raw:
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]


def get_sandbox_enabled() -> bool:
    return os.getenv("AWFULCLAW_SANDBOX", "0").strip() == "1"


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
