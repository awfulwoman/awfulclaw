from __future__ import annotations

import asyncio
from pathlib import Path

from agent.bus import Bus
from agent.connectors import OutboundEvent, OutboundMessage
from agent.llm_client import LLMClient


class BackendManager:
    def __init__(
        self,
        primary: LLMClient,
        fallback: LLMClient | None,
        failure_threshold: int,
        probe_interval: int,
        bus: Bus | None = None,
        notify_channel: tuple[str, str] | None = None,
        locked: bool = False,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._threshold = failure_threshold
        self._probe_interval = probe_interval
        self._bus = bus
        self._notify_channel = notify_channel
        self._locked = locked
        self._active: LLMClient = primary
        self._failures = 0
        self._on_fallback = False

    async def complete(
        self,
        prompt: str,
        system_prompt: str,
        mcp_config_path: Path,
        allowed_tools: list[str],
    ) -> str:
        try:
            result = await self._active.complete(
                prompt, system_prompt, mcp_config_path, allowed_tools
            )
            if not self._locked and not self._on_fallback:
                self._failures = 0
            return result
        except Exception:
            if self._locked or self._fallback is None or self._on_fallback:
                raise
            self._failures += 1
            if self._failures >= self._threshold:
                await self._switch_to_fallback()
                return await self._active.complete(
                    prompt, system_prompt, mcp_config_path, allowed_tools
                )
            raise

    async def health_check(self) -> bool:
        return await self._active.health_check()

    async def switch_to_primary(self) -> None:
        """Called by /use-primary. No-op when locked."""
        if self._locked:
            return
        self._active = self._primary
        self._on_fallback = False
        self._failures = 0
        await self._notify("Switched back to Claude. I'm fully operational again.")

    async def probe_loop(self) -> None:
        """Background asyncio task: probe primary backend and notify on recovery."""
        while True:
            await asyncio.sleep(self._probe_interval)
            await self._check_and_notify()

    async def _check_and_notify(self) -> None:
        if self._locked or not self._on_fallback:
            return
        try:
            ok = await self._primary.health_check()
        except Exception:
            ok = False
        if ok:
            await self._notify(
                "Claude CLI is back. Reply /use-primary to switch back."
            )

    async def _switch_to_fallback(self) -> None:
        self._active = self._fallback  # type: ignore[assignment]
        self._on_fallback = True
        self._failures = 0
        await self._notify(
            "Claude CLI is unavailable. Switched to local Ollama model — "
            "memory and tools are available but responses will be slower "
            "and less accurate."
        )

    async def _notify(self, text: str) -> None:
        if self._bus is None or self._notify_channel is None:
            return
        connector_name, channel = self._notify_channel
        await self._bus.post(
            OutboundEvent(
                channel=channel,
                to=channel,
                message=OutboundMessage(text=text),
                connector_name=connector_name,
            )
        )
