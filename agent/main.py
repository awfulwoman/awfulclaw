from __future__ import annotations

import argparse
import asyncio
import datetime
import signal
import threading

from dotenv import load_dotenv
load_dotenv()


class _ShutdownRequested(Exception):
    """Raised by the shutdown watcher task to exit the TaskGroup cleanly on SIGTERM."""

from agent.agent import Agent
from agent.bus import Bus, ScheduleEvent
from agent.claude_client import ClaudeClient
from agent.config import Settings
from agent.mcp import MCPClient
from agent.connectors import Connector, InboundEvent, OutboundEvent
from agent.connectors.rest import RESTConnector
from agent.connectors.telegram import TelegramConnector
from agent.handlers.checkin import CheckinHandler
from agent.handlers.orientation import OrientationHandler
from agent.handlers.schedule import ScheduleHandler
from agent.middleware.invoke import InvokeMiddleware
from agent.middleware.location import LocationMiddleware
from agent.middleware.rate_limit import RateLimitMiddleware
from agent.middleware.secret import SecretCaptureMiddleware
from agent.middleware.slash import SlashCommandMiddleware
from agent.middleware.typing import TypingMiddleware
from agent.pipeline import Pipeline
from agent.scheduler import Scheduler
from agent.store import Store


def _request_eventkit_access(entity_type_name: str, entity_type: int, store: object) -> bool:
    """Request EventKit access for one entity type; blocks until callback fires."""
    granted_holder: list[bool] = []
    done = threading.Event()

    def handler(granted: bool, error: object) -> None:
        granted_holder.append(bool(granted))
        done.set()

    store.requestAccessToEntityType_completion_(entity_type, handler)  # type: ignore[union-attr]
    done.wait(timeout=30)
    return granted_holder[0] if granted_holder else False


def _request_contacts_access(store: object) -> bool:
    """Request Contacts access; blocks until callback fires."""
    granted_holder: list[bool] = []
    done = threading.Event()

    def handler(granted: bool, error: object) -> None:
        granted_holder.append(bool(granted))
        done.set()

    import Contacts as _CN  # type: ignore[import-not-found]
    store.requestAccessForEntityType_completionHandler_(_CN.CNEntityTypeContacts, handler)  # type: ignore[union-attr]
    done.wait(timeout=30)
    return granted_holder[0] if granted_holder else False


def _request_tcc_permissions() -> dict[str, str]:
    """Request macOS TCC permissions; returns name→status map. Non-blocking on subsequent runs."""
    results: dict[str, str] = {}

    try:
        import EventKit as _EK  # type: ignore[import-not-found]

        ek_store = _EK.EKEventStore.alloc().init()
        results["Calendar"] = "granted" if _request_eventkit_access("Calendar", _EK.EKEntityTypeEvent, ek_store) else "DENIED"
        results["Reminders"] = "granted" if _request_eventkit_access("Reminders", _EK.EKEntityTypeReminder, ek_store) else "DENIED"
    except ImportError:
        results["Calendar"] = results["Reminders"] = "unavailable (pyobjc-framework-EventKit not installed)"

    try:
        import Contacts as _CN  # type: ignore[import-not-found]

        cn_store = _CN.CNContactStore.alloc().init()
        results["Contacts"] = "granted" if _request_contacts_access(cn_store) else "DENIED"
    except ImportError:
        results["Contacts"] = "unavailable (pyobjc-framework-Contacts not installed)"

    return results


async def preflight(settings: Settings, store: Store) -> None:
    """Validate external dependencies before entering the main loop.
    Raises on failure — a clear startup error beats a runtime surprise."""
    await store.check_schema()
    for name in ("PERSONALITY.md", "PROTOCOLS.md", "USER.md"):
        path = settings.profile_path / name
        if not path.is_file():
            raise FileNotFoundError(f"Missing required config: {path}")
    if not settings.mcp_config.is_file():
        raise FileNotFoundError(f"Missing MCP config: {settings.mcp_config}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--connector",
        choices=["telegram", "rest"],
        nargs="+",
        default=["telegram"],
        dest="connectors",
    )
    args = parser.parse_args()

    tcc = _request_tcc_permissions()
    for name, status in tcc.items():
        if status != "granted":
            print(f"[tcc] WARNING: {name}: {status}", flush=True)

    settings = Settings()  # type: ignore[call-arg]
    store = await Store.connect(settings.state_path / "store.db")
    mcp = MCPClient()
    try:
        await preflight(settings, store)

        bus = Bus()
        client = ClaudeClient(settings.model)
        agent = Agent(client, settings, store)

        connectors: dict[str, "Connector"] = {}
        if "telegram" in args.connectors:
            if settings.telegram is None:
                raise ValueError("AWFULCLAW_TELEGRAM__BOT_TOKEN and AWFULCLAW_TELEGRAM__ALLOWED_CHAT_IDS are required for the telegram connector")
            connectors["telegram"] = TelegramConnector(
                token=settings.telegram.bot_token,
                allowed_chat_ids=settings.telegram.allowed_chat_ids,
                store=store,
            )
        if "rest" in args.connectors:
            connectors["rest"] = RESTConnector()

        pipeline = Pipeline([
            RateLimitMiddleware(),
            SecretCaptureMiddleware(store),
            LocationMiddleware(store),
            SlashCommandMiddleware(connectors, store),
            TypingMiddleware(connectors),
            InvokeMiddleware(agent, bus, store),
        ])

        await mcp.connect_all(settings.mcp_config)

        checkin_handler = CheckinHandler(agent, bus, store, settings)
        orientation_handler = OrientationHandler(agent, bus, store, settings.mcp_config)
        schedule_handler = ScheduleHandler(agent, bus, store)
        scheduler = Scheduler()

        async def orientation_task() -> None:
            try:
                await orientation_handler.run()
            except Exception as exc:
                print(f"[orientation] failed: {exc}", flush=True)

        async def checkin_loop() -> None:
            while True:
                try:
                    await checkin_handler.run()
                except Exception as exc:
                    print(f"[checkin] failed: {exc}", flush=True)
                await asyncio.sleep(60)

        def _log(direction: str, connector: str, channel: str, sender: str, text: str) -> None:
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{ts}] {direction} [{connector}/{channel}] {sender}: {text}", flush=True)

        async def on_message(event: InboundEvent) -> None:
            _log("IN ", event.connector_name, event.channel,
                 event.message.sender_name or event.message.sender,
                 event.message.text)
            await bus.post(event)

        async def handle_outbound(event: OutboundEvent) -> None:
            _log("OUT", event.connector_name, event.channel,
                 "agent", event.message.text)
            c = connectors.get(event.connector_name)
            if c is None:
                # Fall back to first available connector
                c = next(iter(connectors.values()), None)
            if c is not None:
                await c.send(event.to, event.message)

        bus.subscribe(InboundEvent, pipeline.run)
        bus.subscribe(OutboundEvent, handle_outbound)
        bus.subscribe(ScheduleEvent, schedule_handler.handle)

        shutdown_event = asyncio.Event()

        def _on_sigterm() -> None:
            shutdown_event.set()

        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGTERM, _on_sigterm)

        async def _shutdown_watcher() -> None:
            await shutdown_event.wait()
            raise _ShutdownRequested()

        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(bus.run())
                for c in connectors.values():
                    tg.create_task(c.start(on_message))
                tg.create_task(scheduler.run(bus, store))
                tg.create_task(checkin_loop())
                tg.create_task(orientation_task())
                tg.create_task(mcp.watch_config(settings.mcp_config))
                tg.create_task(_shutdown_watcher())
        except* _ShutdownRequested:
            pass  # Normal SIGTERM shutdown — main task not cancelled, cleanup runs cleanly
    finally:
        # Clear any pending asyncio cancellations so async teardown can proceed.
        # asyncio.TaskGroup internally calls parent_task.cancel() when a child raises;
        # leftover cancellations cause anyio cancel scope errors inside disconnect_all().
        task = asyncio.current_task()
        if task is not None:
            while task.cancelling():
                task.uncancel()
        try:
            await asyncio.wait_for(mcp.disconnect_all(), timeout=3.0)
        except (RuntimeError, asyncio.TimeoutError):
            pass  # MCP subprocess hung or cancel scope mismatch — process exiting anyway
        await store.close()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

