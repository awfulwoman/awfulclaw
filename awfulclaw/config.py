"""Configuration loaded from environment / .env file."""

import os

from dotenv import load_dotenv

from awfulclaw.connector import Connector

load_dotenv()


def get_connector() -> Connector:
    channel = os.getenv("AWFULCLAW_CHANNEL", "imessage").lower()
    if channel == "imessage":
        from awfulclaw.imessage import IMessageConnector

        return IMessageConnector()
    if channel == "telegram":
        from awfulclaw.telegram import TelegramConnector

        return TelegramConnector()
    raise RuntimeError(
        f"Unrecognised AWFULCLAW_CHANNEL value: {channel!r}. "
        "Valid options: imessage, telegram"
    )


def get_phone() -> str:
    value = os.getenv("AWFULCLAW_PHONE")
    if not value:
        raise RuntimeError(
            "AWFULCLAW_PHONE is not set. Add it to your .env file:\n\n"
            "  AWFULCLAW_PHONE=+15555550100\n\n"
            "Use the phone number or Apple ID of the iMessage contact you want the agent to talk to."  # noqa: E501
        )
    return value


def get_model() -> str:
    return os.getenv("AWFULCLAW_MODEL", "claude-sonnet-4-6")


def get_poll_interval() -> int:
    return int(os.getenv("AWFULCLAW_POLL_INTERVAL", "5"))


def get_idle_interval() -> int:
    return int(os.getenv("AWFULCLAW_IDLE_INTERVAL", "60"))
