"""Gateway: normalises messages from one or more Connectors into a unified queue."""

from __future__ import annotations

import logging
import queue
import threading
from datetime import datetime, timezone

from awfulclaw.connector import Connector, Message

logger = logging.getLogger(__name__)


class Gateway:
    """Owns one or more Connectors; normalises their messages into a unified inbound queue."""

    def __init__(self, connectors: list[tuple[str, Connector]]) -> None:
        """
        Args:
            connectors: list of (channel_name, connector) pairs.
                        The first entry is treated as the primary channel.
        """
        if not connectors:
            raise ValueError("Gateway requires at least one connector")
        self._connectors: dict[str, Connector] = dict(connectors)
        self._primary_channel: str = connectors[0][0]
        self._inbound: queue.Queue[Message] = queue.Queue()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    @property
    def primary_channel(self) -> str:
        return self._primary_channel

    @property
    def primary_recipient(self) -> str:
        return self._connectors[self._primary_channel].primary_recipient

    def primary_recipient_for(self, channel: str) -> str:
        """Return the primary recipient for a given channel (falls back to primary)."""
        connector = self._connectors.get(channel, self._connectors[self._primary_channel])
        return connector.primary_recipient

    def start(self) -> None:
        """Launch a background polling thread per connector."""
        from awfulclaw import config

        interval = config.get_poll_interval()
        for channel_name, connector in self._connectors.items():
            t = threading.Thread(
                target=self._poll_loop,
                args=(channel_name, connector, interval),
                daemon=True,
                name=f"gateway-poll-{channel_name}",
            )
            t.start()
            self._threads.append(t)

    def _poll_loop(self, channel_name: str, connector: Connector, interval: int) -> None:
        last_poll = datetime.now(timezone.utc)
        while not self._stop.wait(interval):
            now = datetime.now(timezone.utc)
            try:
                messages = connector.poll_new_messages(since=last_poll)
                last_poll = now
                for msg in messages:
                    msg.channel = channel_name
                    self._inbound.put(msg)
            except Exception:
                logger.exception("Error polling connector %s", channel_name)

    def get_messages(self) -> list[Message]:
        """Drain all pending inbound messages (non-blocking)."""
        messages: list[Message] = []
        while True:
            try:
                messages.append(self._inbound.get_nowait())
            except queue.Empty:
                break
        return messages

    def send(self, channel: str, to: str, body: str) -> None:
        """Route an outbound message to the correct connector."""
        connector = self._connectors.get(channel)
        if connector is None:
            logger.error("Unknown channel: %s", channel)
            return
        connector.send_message(to, body)

    def stop(self) -> None:
        """Signal all polling threads to stop."""
        self._stop.set()
