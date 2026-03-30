"""MCP server registry — tracks registered servers and generates mcp.json configs."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from awfulclaw_mcp import generate_mcp_config

logger = logging.getLogger(__name__)

_ENV_RE = re.compile(r"\$\{(\w+)\}")


def _resolve_env(value: str) -> str:
    """Replace ${VAR} references with environment variable values."""
    return _ENV_RE.sub(lambda m: os.getenv(m.group(1), ""), value)


class MCPRegistry:
    """Maintains a dict of registered MCP server configs and generates mcp.json."""

    def __init__(self) -> None:
        self._servers: dict[str, dict[str, object]] = {}
        self._config_mtime: float | None = None

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

    def load_from_config(self, path: Path) -> None:
        """Load server registrations from a JSON config file.

        Servers with an ``env_required`` list are skipped when any of the
        listed environment variables are missing.  ``${VAR}`` references in
        ``env`` values are resolved from the process environment at load time.
        """
        data = json.loads(path.read_text(encoding="utf-8"))
        self._servers = {}
        self._config_mtime = path.stat().st_mtime

        for entry in data.get("servers", []):
            name: str = entry["name"]
            required: list[str] = entry.get("env_required", [])
            missing = [v for v in required if not os.getenv(v)]
            if missing:
                logger.warning(
                    "MCP server %r skipped — missing env vars: %s",
                    name,
                    ", ".join(missing),
                )
                continue

            raw_env: dict[str, str] = entry.get("env", {})
            resolved_env = {k: _resolve_env(v) for k, v in raw_env.items()}

            self._servers[name] = {
                "command": entry["command"],
                "args": entry["args"],
                "env": resolved_env,
            }

    def reload_if_changed(self, path: Path) -> bool:
        """Reload config if the file's mtime has changed.  Returns True if reloaded."""
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return False
        if mtime == self._config_mtime:
            return False
        logger.info("MCP config changed — reloading %s", path)
        self.load_from_config(path)
        return True

    def generate_config(self) -> Path:
        """Write mcp.json and return its path."""
        return generate_mcp_config(self._servers)

    def is_empty(self) -> bool:
        return len(self._servers) == 0
