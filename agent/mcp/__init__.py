import asyncio
import json
import os
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import CallToolResult, Tool


class MCPClient:
    def __init__(self) -> None:
        self._sessions: list[ClientSession] = []
        self._tool_map: dict[str, ClientSession] = {}
        # Per-server tracking for hot-reload
        self._server_stacks: dict[str, AsyncExitStack] = {}
        self._server_tools: dict[str, list[str]] = {}
        self._server_sessions: dict[str, ClientSession] = {}
        # Config tracking
        self._config_path: Path | None = None
        self._config_mtime: float | None = None
        self._exclude: frozenset[str] = frozenset()

    async def _connect_server(self, name: str, spec: dict[str, Any]) -> None:
        """Connect a single MCP server and register its tools."""
        stack = AsyncExitStack()
        if "url" in spec:
            headers = spec.get("headers") or {}
            read, write, _ = await stack.enter_async_context(streamablehttp_client(spec["url"], headers=headers))
        else:
            params = StdioServerParameters(
                command=spec["command"],
                args=spec.get("args", []),
                env=spec.get("env") or None,
            )
            read, write = await stack.enter_async_context(stdio_client(params))
        session: ClientSession = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()

        result = await session.list_tools()
        tool_names = [tool.name for tool in result.tools]

        self._server_stacks[name] = stack
        self._server_tools[name] = tool_names
        self._server_sessions[name] = session
        self._sessions.append(session)
        for tool_name in tool_names:
            self._tool_map[tool_name] = session

    async def _disconnect_server(self, name: str) -> None:
        """Disconnect a single MCP server and unregister its tools."""
        session = self._server_sessions.pop(name, None)
        stack = self._server_stacks.pop(name, None)
        tool_names = self._server_tools.pop(name, [])

        for tool_name in tool_names:
            self._tool_map.pop(tool_name, None)

        if session is not None and session in self._sessions:
            self._sessions.remove(session)

        if stack is not None:
            await stack.aclose()

    @staticmethod
    def _expand_env(spec: dict[str, Any]) -> dict[str, Any]:
        """Expand ${VAR} references in env and headers values using os.environ."""
        result = dict(spec)
        if result.get("env"):
            result["env"] = {k: os.path.expandvars(v) for k, v in result["env"].items()}
        if result.get("headers"):
            result["headers"] = {k: os.path.expandvars(v) for k, v in result["headers"].items()}
        if isinstance(result.get("url"), str):
            result["url"] = os.path.expandvars(result["url"])
        return result

    async def connect_all(self, config_path: Path, exclude: frozenset[str] = frozenset()) -> None:
        """Spawn and initialise all MCP servers defined in config_path."""
        self._exclude = exclude
        self._config_path = config_path
        self._config_mtime = config_path.stat().st_mtime
        raw: dict[str, Any] = json.loads(config_path.read_text())
        servers = raw.get("mcpServers", raw)
        for name, spec in servers.items():
            if name in self._exclude:
                continue
            await self._connect_server(name, self._expand_env(spec))

    async def reload_if_changed(self) -> None:
        """Check config mtime; if changed, disconnect removed servers and connect new ones."""
        if self._config_path is None:
            return
        try:
            current_mtime = self._config_path.stat().st_mtime
        except FileNotFoundError:
            return
        if current_mtime == self._config_mtime:
            return

        self._config_mtime = current_mtime
        raw: dict[str, Any] = json.loads(self._config_path.read_text())
        servers = raw.get("mcpServers", raw)

        old_names = set(self._server_sessions.keys())
        new_names = set(servers.keys())

        for name in old_names - new_names:
            await self._disconnect_server(name)

        for name in new_names - old_names:
            if name in self._exclude:
                continue
            await self._connect_server(name, self._expand_env(servers[name]))

    async def watch_config(self, path: Path, interval: float = 10.0) -> None:
        """Async task: periodically check config for changes and reload."""
        self._config_path = path
        while True:
            await asyncio.sleep(interval)
            await self.reload_if_changed()

    async def list_tools(self) -> list[Tool]:
        """Return combined tool catalogue from all connected servers."""
        tools: list[Tool] = []
        for session in self._sessions:
            result = await session.list_tools()
            tools.extend(result.tools)
        return tools

    def server_status(self) -> dict[str, bool]:
        """Return {name: connected} for all configured servers not in _exclude."""
        if self._config_path is None:
            return {}
        try:
            raw: dict[str, Any] = json.loads(self._config_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {name: True for name in self._server_sessions}
        servers = raw.get("mcpServers", raw)
        return {
            name: name in self._server_sessions
            for name in servers
            if name not in self._exclude
        }

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> CallToolResult:
        """Dispatch a tool call to whichever server registered the tool."""
        session = self._tool_map.get(name)
        if session is None:
            raise KeyError(f"Unknown tool: {name!r}")
        return await session.call_tool(name, arguments)

    async def disconnect_all(self) -> None:
        """Close all server connections and clean up resources."""
        for stack in list(self._server_stacks.values()):
            try:
                await stack.aclose()
            except RuntimeError:
                pass  # anyio cancel scope mismatch on shutdown — process is exiting anyway
        self._sessions = []
        self._tool_map = {}
        self._server_stacks = {}
        self._server_tools = {}
        self._server_sessions = {}
