from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Transcriber(Protocol):
    async def transcribe(self, audio: bytes, mime_type: str) -> str: ...
