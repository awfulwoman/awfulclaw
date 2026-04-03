import json
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import CallToolResult, Tool


class MCPClient:
    def __init__(self) -> None:
        self._sessions: list[ClientSession] = []
        self._tool_map: dict[str, ClientSession] = {}
        self._exit_stack = AsyncExitStack()

    async def connect_all(self, config_path: Path) -> None:
        """Spawn and initialise all MCP servers defined in config_path."""
        raw = json.loads(config_path.read_text())
        for _name, spec in raw.items():
            params = StdioServerParameters(
                command=spec["command"],
                args=spec.get("args", []),
                env=spec.get("env") or None,
            )
            read, write = await self._exit_stack.enter_async_context(stdio_client(params))
            session: ClientSession = await self._exit_stack.enter_async_context(
                ClientSession(read, write)
            )
            await session.initialize()
            self._sessions.append(session)

            result = await session.list_tools()
            for tool in result.tools:
                self._tool_map[tool.name] = session

    async def list_tools(self) -> list[Tool]:
        """Return combined tool catalogue from all connected servers."""
        tools: list[Tool] = []
        for session in self._sessions:
            result = await session.list_tools()
            tools.extend(result.tools)
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> CallToolResult:
        """Dispatch a tool call to whichever server registered the tool."""
        session = self._tool_map.get(name)
        if session is None:
            raise KeyError(f"Unknown tool: {name!r}")
        return await session.call_tool(name, arguments)

    async def disconnect_all(self) -> None:
        """Close all server connections and clean up resources."""
        await self._exit_stack.aclose()
        self._sessions = []
        self._tool_map = {}
