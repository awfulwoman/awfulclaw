"""MCP server for write-only management of project .env variables."""

from __future__ import annotations

from awfulclaw.env_utils import get_env_keys, set_env_var
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("env_manager")


@mcp.tool()
def env_set(key: str, value: str) -> str:
    """Add or update an environment variable in the project .env file.

    The value is stored securely and cannot be read back via this tool.
    Key must be uppercase letters, digits, and underscores (e.g. SOME_API_KEY).
    The app must be restarted for new values to take effect.
    """
    try:
        set_env_var(key, value)
    except ValueError as exc:
        return f"Error: {exc}"
    return f"Set {key} in .env (restart required to take effect)"


@mcp.tool()
def env_keys() -> str:
    """List the names of environment variables currently set in .env.

    Returns key names only — values are never exposed.
    """
    keys = get_env_keys()
    if not keys:
        return "No keys set in .env"
    return "\n".join(keys)


if __name__ == "__main__":
    mcp.run()
