"""env_manager MCP server — write-only credential storage.

Exposes two tools:
  env_keys() — returns key names from .env (values never returned)
  env_set(key) — registers a pending credential request in store.kv

No env_get tool exists by design.

Run via stdio; configure with env vars DB_PATH and ENV_PATH.
"""
from __future__ import annotations

import os
from pathlib import Path

import aiosqlite
from mcp.server.fastmcp import FastMCP

# Key used by SecretCaptureMiddleware to know which credential to capture next.
_PENDING_KEY = "pending_secret_key"

mcp = FastMCP("env_manager")


def _get_env_path() -> Path:
    raw = os.environ.get("ENV_PATH", ".env")
    return Path(raw)


def _get_db_path() -> Path:
    raw = os.environ.get("DB_PATH", "agent.db")
    return Path(raw)


def _parse_env_keys(env_path: Path) -> list[str]:
    """Return key names from an .env file; values are never read."""
    if not env_path.exists():
        return []
    keys: list[str] = []
    for line in env_path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key:
                keys.append(key)
    return keys


@mcp.tool()
def env_keys() -> list[str]:
    """Return the list of key names defined in the .env file.

    Values are never returned — this is read-only for key names.
    """
    return _parse_env_keys(_get_env_path())


@mcp.tool()
async def env_set(key: str) -> str:
    """Register a pending credential request.

    After calling this, the next user message will be captured by
    SecretCaptureMiddleware as the value and appended to .env.

    Returns a confirmation message.
    """
    db_path = _get_db_path()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (_PENDING_KEY, key),
        )
        await db.commit()
    return f"Pending credential request registered for key: {key!r}. Send the value in your next message."


if __name__ == "__main__":
    mcp.run()
