from __future__ import annotations

from agent.llm_client import LLMClient
from agent.config import Settings
from agent.connectors import InboundEvent
from agent.context import ContextAssembler
from agent.store import Store, Turn

_HISTORY_TURNS = 20  # number of recent turns to include as history


class Agent:
    def __init__(self, client: LLMClient, settings: Settings, store: Store) -> None:
        self._client = client
        self._settings = settings
        self._store = store
        self._assembler = ContextAssembler(store, settings)

    async def reply(self, event: InboundEvent) -> str:
        channel = event.channel
        sender = event.message.sender_name or event.message.sender
        text = event.message.text

        # Store user turn before assembly so it's in history for next call
        await self._store.add_turn(channel, "user", text)

        system_prompt = await self._assembler.build(text, sender, channel, connector=event.connector_name)
        history = await self._store.recent_turns(channel, _HISTORY_TURNS)

        prompt = _format_history(history[:-1]) + text  # exclude just-added user turn duplicate
        reply_text = await self._client.complete(
            prompt=prompt,
            system_prompt=system_prompt,
            mcp_config_path=self._settings.mcp_config,
            allowed_tools=[],
        )

        await self._store.add_turn(channel, "assistant", reply_text)
        return reply_text

    async def invoke(self, prompt: str, history: list[Turn] | None = None) -> str:
        """Used by the scheduler for prompt-driven turns (no inbound event)."""
        system_prompt = await self._assembler.build(prompt, None, "scheduler")
        full_prompt = _format_history(history or []) + prompt
        return await self._client.complete(
            prompt=full_prompt,
            system_prompt=system_prompt,
            mcp_config_path=self._settings.mcp_config,
            allowed_tools=[],
        )


def _format_history(turns: list[Turn]) -> str:
    if not turns:
        return ""
    lines = [f"{t.role}: {t.content}" for t in turns]
    return "\n".join(lines) + "\n"
