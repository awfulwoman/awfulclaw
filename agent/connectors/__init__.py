from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Coroutine, Any


@dataclass
class Message:
    text: str
    sender: str
    sender_name: str
    images: list[bytes] = field(default_factory=list)


@dataclass
class OutboundMessage:
    text: str
    images: list[bytes] = field(default_factory=list)


@dataclass
class InboundEvent:
    channel: str
    message: Message
    connector_name: str


@dataclass
class OutboundEvent:
    channel: str
    to: str
    message: OutboundMessage


OnMessage = Callable[[InboundEvent], Coroutine[Any, Any, None]]


class Connector(ABC):
    @abstractmethod
    async def start(self, on_message: OnMessage) -> None: ...

    @abstractmethod
    async def send(self, to: str, message: OutboundMessage) -> None: ...

    @abstractmethod
    async def send_typing(self, to: str) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...
