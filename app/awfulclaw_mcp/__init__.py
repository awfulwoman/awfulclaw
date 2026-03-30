"""MCP (Model Context Protocol) infrastructure for awfulclaw."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def generate_mcp_config(servers: dict[str, dict[str, object]]) -> Path:
    """Write an mcp.json config file and return its path.

    servers: mapping of server_name -> {"command": ..., "args": [...], "env": {...}}
    """
    config = {"mcpServers": servers}
    fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix="awfulclaw_mcp_")
    tmp = Path(tmp_path)
    os.close(fd)
    tmp.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return tmp
