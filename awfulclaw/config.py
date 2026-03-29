"""Configuration loaded from environment / .env file."""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# The Claude CLI (Claude Code) stores OAuth tokens in ~/.claude/.credentials.json
# under the key claudeAiOauth.accessToken.
_CREDENTIALS_FILE = Path.home() / ".claude" / ".credentials.json"


def get_auth_token() -> str:
    """Return an auth token for the Anthropic API.

    Prefers ANTHROPIC_API_KEY env var if set (useful for CI or explicit key auth).
    Otherwise reads the OAuth access token stored by the ``claude`` CLI at
    ~/.claude/.credentials.json under claudeAiOauth.accessToken.

    Raises RuntimeError if neither source yields a token.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key:
        return api_key

    if not _CREDENTIALS_FILE.exists():
        raise RuntimeError(
            f"Claude CLI credentials not found at {_CREDENTIALS_FILE}. "
            "Run `claude auth login` to authenticate, or set ANTHROPIC_API_KEY."
        )

    try:
        data = json.loads(_CREDENTIALS_FILE.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(
            f"Failed to read Claude CLI credentials from {_CREDENTIALS_FILE}: {exc}"
        ) from exc

    token = data.get("claudeAiOauth", {}).get("accessToken")
    if not token:
        raise RuntimeError(
            f"No OAuth access token found in {_CREDENTIALS_FILE}. "
            "Run `claude auth login` to authenticate, or set ANTHROPIC_API_KEY."
        )
    return token


def get_phone() -> str:
    value = os.getenv("AWFULCLAW_PHONE")
    if not value:
        raise RuntimeError("Missing required env var: AWFULCLAW_PHONE")
    return value


def get_model() -> str:
    return os.getenv("AWFULCLAW_MODEL", "claude-sonnet-4-6")


def get_poll_interval() -> int:
    return int(os.getenv("AWFULCLAW_POLL_INTERVAL", "5"))


def get_idle_interval() -> int:
    return int(os.getenv("AWFULCLAW_IDLE_INTERVAL", "60"))
