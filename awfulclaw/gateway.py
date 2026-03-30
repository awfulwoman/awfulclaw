"""Gateway — normalises messages from one or more Connectors into a unified queue."""

from __future__ import annotations

import dataclasses
import queue
from datetime import datetime

from awfulclaw.connector import Connector, Message


class Gateway:
    """Wraps one or more Connectors, routing inbound messages through a shared queue.

    For a single connector the behaviour is identical to calling the connector
    directly.  Multiple connectors are aggregated: ``poll()`` drains all of them
    and stamps each ``Message`` with the originating ``channel`` name.
    """

    def __init__(self, connectors: dict[str, Connector]) -> None:
        if not connectors:
            raise ValueError("Gateway requires at least one connector")
        self._connectors = connectors
        self._default_channel = next(iter(connectors))
        self._inbound: queue.Queue[Message] = queue.Queue()

    @property
    def primary_recipient(self) -> str:
        """Default recipient for outbound messages (idle ticks, scheduled tasks)."""
        return self._connectors[self._default_channel].primary_recipient

    @property
    def default_channel(self) -> str:
        """Channel name for the primary connector."""
        return self._default_channel

    def poll(self, since: datetime) -> list[Message]:
        """Poll all connectors and return new messages, tagged with their channel."""
        for channel, connector in self._connectors.items():
            for msg in connector.poll_new_messages(since):
                tagged = dataclasses.replace(msg, channel=channel)
                self._inbound.put_nowait(tagged)

        messages: list[Message] = []
        while True:
            try:
                messages.append(self._inbound.get_nowait())
            except queue.Empty:
                break
        return messages

    def send(self, channel: str, to: str, body: str) -> None:
        """Route an outbound message to the correct connector."""
        self._connectors[channel].send_message(to, body)
