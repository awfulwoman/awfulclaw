from __future__ import annotations

from agent.claude_client import ClaudeClient
from agent.config import Settings
from agent.connectors import InboundEvent


class Agent:
    def __init__(self, client: ClaudeClient, settings: Settings) -> None:
        self._client = client
        self._settings = settings

    async def reply(self, event: InboundEvent) -> str:
        return await self.invoke(event.message.text, [])

    async def invoke(self, prompt: str, history: list[str]) -> str:
        full_prompt = "\n".join(history + [prompt]) if history else prompt
        return await self._client.complete(
            prompt=full_prompt,
            system_prompt="",
            mcp_config_path=self._settings.mcp_config,
            allowed_tools=[],
        )
