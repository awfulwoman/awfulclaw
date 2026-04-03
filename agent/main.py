from __future__ import annotations

import argparse
import asyncio
import signal
import sys
import threading

from agent.agent import Agent
from agent.bus import Bus, ScheduleEvent
from agent.claude_client import ClaudeClient
from agent.config import Settings
from agent.mcp import MCPClient
from agent.connectors import InboundEvent, OutboundEvent
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


def tcc_setup() -> None:
    """Request macOS TCC permissions for Calendar, Reminders, and Contacts."""
    results: dict[str, str] = {}

    # --- EventKit (Calendar + Reminders) ---
    try:
        import EventKit as _EK  # type: ignore[import-not-found]

        ek_store = _EK.EKEventStore.alloc().init()

        cal_granted = _request_eventkit_access("Calendar", _EK.EKEntityTypeEvent, ek_store)
        results["Calendar"] = "granted" if cal_granted else "DENIED"

        rem_granted = _request_eventkit_access("Reminders", _EK.EKEntityTypeReminder, ek_store)
        results["Reminders"] = "granted" if rem_granted else "DENIED"

    except ImportError:
        results["Calendar"] = "ERROR (pyobjc-framework-EventKit not installed)"
        results["Reminders"] = "ERROR (pyobjc-framework-EventKit not installed)"

    # --- Contacts ---
    try:
        import Contacts as _CN  # type: ignore[import-not-found]

        cn_store = _CN.CNContactStore.alloc().init()
        cn_granted = _request_contacts_access(cn_store)
        results["Contacts"] = "granted" if cn_granted else "DENIED"

    except ImportError:
        results["Contacts"] = "ERROR (pyobjc-framework-Contacts not installed)"

    # --- Report ---
    print("TCC Permission Status:")
    all_ok = True
    for name, status in results.items():
        icon = "✓" if status == "granted" else "✗"
        print(f"  {icon} {name}: {status}")
        if status != "granted":
            all_ok = False

    if all_ok:
        print("\nAll permissions granted.")
    else:
        print("\nSome permissions missing — grant access in System Settings > Privacy & Security.")
        sys.exit(1)


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
    parser.add_argument(
        "--tcc-setup",
        action="store_true",
        help="Request macOS Calendar, Reminders, and Contacts permissions, then exit.",
    )
    args = parser.parse_args()

    if args.tcc_setup:
        tcc_setup()
        return

    settings = Settings()  # type: ignore[call-arg]
    store = await Store.connect(settings.state_path / "store.db")
    mcp = MCPClient()
    try:
        await preflight(settings, store)

        bus = Bus()
        client = ClaudeClient(settings.model)
        agent = Agent(client, settings, store)

        if args.connector == "telegram":
            if settings.telegram is None:
                raise ValueError("AWFULCLAW_TELEGRAM__BOT_TOKEN and AWFULCLAW_TELEGRAM__ALLOWED_CHAT_IDS are required for the telegram connector")
            connector = TelegramConnector(
                token=settings.telegram.bot_token,
                allowed_chat_ids=settings.telegram.allowed_chat_ids,
                store=store,
            )
        else:
            connector = RESTConnector()

        pipeline = Pipeline([
            RateLimitMiddleware(),
            SecretCaptureMiddleware(store),
            LocationMiddleware(store),
            SlashCommandMiddleware(connector, store),
            TypingMiddleware(connector),
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

        async def on_message(event: InboundEvent) -> None:
            await bus.post(event)

        async def handle_outbound(event: OutboundEvent) -> None:
            await connector.send(event.to, event.message)

        bus.subscribe(InboundEvent, pipeline.run)
        bus.subscribe(OutboundEvent, handle_outbound)
        bus.subscribe(ScheduleEvent, schedule_handler.handle)

        loop = asyncio.get_running_loop()
        main_task = asyncio.current_task()

        def _on_sigterm() -> None:
            if main_task is not None:
                main_task.cancel()

        loop.add_signal_handler(signal.SIGTERM, _on_sigterm)

        async with asyncio.TaskGroup() as tg:
            tg.create_task(bus.run())
            tg.create_task(connector.start(on_message))
            tg.create_task(scheduler.run(bus, store))
            tg.create_task(checkin_loop())
            tg.create_task(orientation_task())
            tg.create_task(mcp.watch_config(settings.mcp_config))
    finally:
        await mcp.disconnect_all()
        await store.close()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

