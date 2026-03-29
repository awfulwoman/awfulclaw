"""Configuration loaded from environment / .env file."""

import os

from dotenv import load_dotenv

from awfulclaw.connector import Connector

load_dotenv()


def get_connector() -> Connector:
    channel = os.getenv("AWFULCLAW_CHANNEL", "telegram").lower()
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
