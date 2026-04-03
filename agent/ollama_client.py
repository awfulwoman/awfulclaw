from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import httpx

from agent.mcp import MCPClient


class OllamaClient:
    def __init__(self, url: str, model: str) -> None:
        self._url = url.rstrip("/")
        self._model = model

    async def complete(
        self,
        prompt: str,
        system_prompt: str,
        mcp_config_path: Path,
        allowed_tools: list[str],
    ) -> str:
        # Filter to stdio-only servers (mirrors ClaudeClient behaviour)
        raw = json.loads(mcp_config_path.read_text())
        servers = raw.get("mcpServers", raw)
        stdio_servers = {k: v for k, v in servers.items() if "command" in v}
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, dir=mcp_config_path.parent
        )
        json.dump({"mcpServers": stdio_servers}, tmp)
        tmp.flush()
        tmp.close()
        effective_config = Path(tmp.name)

        mcp = MCPClient()
        try:
            await mcp.connect_all(effective_config)
            tools = await mcp.list_tools()
            ollama_tools = [_tool_to_ollama(t) for t in tools]
            if allowed_tools:
                ollama_tools = [t for t in ollama_tools if t["function"]["name"] in allowed_tools]

            messages: list[dict[str, Any]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            _MAX_TOOL_ROUNDS = 20
            async with httpx.AsyncClient(timeout=120.0) as http:
                for _ in range(_MAX_TOOL_ROUNDS):
                    resp = await http.post(
                        f"{self._url}/api/chat",
                        json={
                            "model": self._model,
                            "messages": messages,
                            "tools": ollama_tools,
                            "stream": False,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    msg = data["message"]
                    tool_calls = msg.get("tool_calls")

                    if not tool_calls:
                        return msg.get("content", "")

                    messages.append({
                        "role": "assistant",
                        "content": msg.get("content", ""),
                        "tool_calls": tool_calls,
                    })
                    for tc in tool_calls:
                        fn = tc["function"]
                        result = await mcp.call_tool(fn["name"], fn.get("arguments") or {})
                        messages.append({
                            "role": "tool",
                            "content": _extract_content(result),
                        })
            raise RuntimeError(
                f"OllamaClient exceeded {_MAX_TOOL_ROUNDS} tool-call rounds without a final response"
            )
        finally:
            await mcp.disconnect_all()
            effective_config.unlink(missing_ok=True)

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as http:
                resp = await http.get(f"{self._url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False


def _tool_to_ollama(tool: Any) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.inputSchema,
        },
    }


def _extract_content(result: Any) -> str:
    parts: list[str] = []
    for item in result.content:
        if hasattr(item, "text"):
            parts.append(item.text)
        else:
            parts.append(str(item))
    return "\n".join(parts)
