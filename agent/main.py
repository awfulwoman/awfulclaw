from __future__ import annotations

import argparse
import asyncio

from agent.agent import Agent
from agent.bus import Bus
from agent.claude_client import ClaudeClient
from agent.config import Settings
from agent.connectors import InboundEvent, OutboundEvent
from agent.connectors.rest import RESTConnector
from agent.connectors.telegram import TelegramConnector
from agent.middleware.invoke import InvokeMiddleware
from agent.pipeline import Pipeline
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--connector", choices=["telegram", "rest"], default="telegram")
    args = parser.parse_args()

    settings = Settings()  # type: ignore[call-arg]
    store = await Store.connect(settings.memory_path / "store.db")
    try:
        await preflight(settings, store)

        bus = Bus()
        client = ClaudeClient(settings.model)
        agent = Agent(client, settings, store)

        if args.connector == "telegram":
            connector = TelegramConnector(
                token=settings.telegram.bot_token,
                allowed_chat_ids=settings.telegram.allowed_chat_ids,
                store=store,
            )
        else:
            connector = RESTConnector()

        pipeline = Pipeline([InvokeMiddleware(agent, bus)])

        async def on_message(event: InboundEvent) -> None:
            await bus.post(event)

        async def handle_outbound(event: OutboundEvent) -> None:
            await connector.send(event.to, event.message)

        bus.subscribe(InboundEvent, pipeline.run)
        bus.subscribe(OutboundEvent, handle_outbound)

        async with asyncio.TaskGroup() as tg:
            tg.create_task(bus.run())
            tg.create_task(connector.start(on_message))
    finally:
        await store.close()
