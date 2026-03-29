"""Configuration loaded from environment / .env file."""

import os

from dotenv import load_dotenv

load_dotenv()


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
