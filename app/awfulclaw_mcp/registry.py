"""MCP server registry — tracks registered servers and generates mcp.json configs."""

from __future__ import annotations

from pathlib import Path

from awfulclaw_mcp import generate_mcp_config


class MCPRegistry:
    """Maintains a dict of registered MCP server configs and generates mcp.json."""

    def __init__(self) -> None:
        self._servers: dict[str, dict[str, object]] = {}

    def register(
        self,
        name: str,
        command: str,
        args: list[str],
        env: dict[str, str] | None = None,
    ) -> None:
        """Register an MCP server."""
        self._servers[name] = {
            "command": command,
            "args": args,
            "env": env or {},
        }

    def generate_config(self) -> Path:
        """Write mcp.json and return its path."""
        return generate_mcp_config(self._servers)

    def is_empty(self) -> bool:
        return len(self._servers) == 0
