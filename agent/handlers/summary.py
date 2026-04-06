"""Periodic handler — generates agent-authored summaries of self-understanding."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.agent import Agent
    from agent.store import Store

_LAST_SUMMARY_KEY = "last_summary"
_SUMMARY_INTERVAL = 86400.0  # once per day

_PROMPTS: dict[str, str] = {
    "user": (
        "Write 2-3 paragraphs summarising your current understanding of the person you work for. "
        "Cover their background, habits, preferences, and anything important you have learned about them. "
        "Be specific and draw on everything you know."
    ),
    "personality": (
        "Write 2-3 paragraphs describing your own personality and working style as you currently understand it. "
        "Be concrete — what are your values, how do you communicate, what are your strengths?"
    ),
    "protocols": (
        "Write 2-3 paragraphs summarising the key protocols and rules you follow. "
        "Focus on what actually shapes your behaviour day-to-day."
    ),
}


class SummaryHandler:
    def __init__(self, agent: "Agent", store: "Store", state_path: Path) -> None:
        self._agent = agent
        self._store = store
        self._out_dir = state_path / "info"

    async def run(self) -> None:
        last_str = await self._store.kv_get(_LAST_SUMMARY_KEY)
        if last_str is not None and (time.time() - float(last_str)) < _SUMMARY_INTERVAL:
            return

        self._out_dir.mkdir(parents=True, exist_ok=True)

        results = await asyncio.gather(
            *[self._generate(name, prompt) for name, prompt in _PROMPTS.items()],
            return_exceptions=True,
        )

        for name, result in zip(_PROMPTS, results):
            if isinstance(result, Exception):
                print(f"[summary] failed for {name!r}: {result}", flush=True)

        # Only record completion time if at least some files were written
        if any(not isinstance(r, Exception) for r in results):
            await self._store.kv_set(_LAST_SUMMARY_KEY, str(time.time()))

    async def _generate(self, name: str, prompt: str) -> None:
        text = await self._agent.invoke(prompt)
        (self._out_dir / f"{name}.md").write_text(text, encoding="utf-8")
        print(f"[summary] wrote {name}.md ({len(text)} chars)", flush=True)
