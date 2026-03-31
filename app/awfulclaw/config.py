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




def get_sandbox() -> bool:
    """Return True unless AWFULCLAW_SANDBOX=0 is explicitly set."""
    return os.getenv("AWFULCLAW_SANDBOX", "1").strip() != "0"


def get_poll_interval() -> int:
    return int(os.getenv("AWFULCLAW_POLL_INTERVAL", "5"))


def get_idle_interval() -> int:
    return int(os.getenv("AWFULCLAW_IDLE_INTERVAL", "60"))


def get_email_check_interval() -> int:
    """Seconds between proactive email checks. Default: 5 minutes."""
    return int(os.getenv("AWFULCLAW_EMAIL_CHECK_INTERVAL", "300"))


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


def get_owntracks_url() -> str:
    return os.getenv("OWNTRACKS_URL", "").strip()


def get_owntracks_user() -> str:
    return os.getenv("OWNTRACKS_USER", "charlie").strip()


def get_owntracks_device() -> str:
    return os.getenv("OWNTRACKS_DEVICE", "iphone").strip()
