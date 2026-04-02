from __future__ import annotations

import asyncio

from agent.config import Settings
from agent.store import Store


async def preflight(settings: Settings, store: Store) -> None:
    """Validate external dependencies before entering the main loop.
    Raises on failure — a clear startup error beats a runtime surprise."""
    await store.check_schema()
    for name in ("PERSONALITY.md", "PROTOCOLS.md", "USER.md"):
        path = settings.agent_config_path / name
        if not path.is_file():
            raise FileNotFoundError(f"Missing required config: {path}")
    if not settings.mcp_config.is_file():
        raise FileNotFoundError(f"Missing MCP config: {settings.mcp_config}")


async def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    store = await Store.connect(settings.memory_path / "store.db")
    try:
        await preflight(settings, store)
    finally:
        await store.close()
