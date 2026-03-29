"""Abstract Connector interface and shared Message dataclass."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Message:
    sender: str
    body: str
    timestamp: datetime
    is_from_me: bool
    image_data: bytes | None = None
    image_mime: str | None = None


class Connector(ABC):
    @property
    @abstractmethod
    def primary_recipient(self) -> str:
        """The default recipient for outbound messages (idle ticks, scheduled tasks)."""
        ...

    @abstractmethod
    def poll_new_messages(self, since: datetime) -> list[Message]: ...

    @abstractmethod
    def send_message(self, to: str, body: str) -> None: ...
