from __future__ import annotations

from agent.transcriber import Transcriber


def test_transcriber_is_a_protocol() -> None:
    # Structural check: any object with transcribe(bytes, str) -> str satisfies it
    class FakeTranscriber:
        async def transcribe(self, audio: bytes, mime_type: str) -> str:
            return "ok"

    assert isinstance(FakeTranscriber(), Transcriber)
