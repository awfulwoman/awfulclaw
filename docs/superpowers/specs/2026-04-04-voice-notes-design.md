# Voice Note Transcription Design

**Date:** 2026-04-04
**Status:** Approved

## Overview

Add voice note support to the Telegram connector. When a voice message arrives, the connector downloads the OGG/Opus audio, transcribes it locally using Parakeet, and injects it into the pipeline as `[Voice]: <transcript>`. The transcription layer is generic — a `Transcriber` protocol decouples the connector from any specific model so future backends (e.g. Whisper, macOS Speech) can be swapped in.

## Goals

- Telegram voice notes are transcribed locally and passed to the agent as labelled text
- `Transcriber` protocol enables alternative implementations without changing the connector
- No cloud API calls — transcription runs entirely on-device
- Graceful failure: transcription errors produce a user-facing message, not a crash
- `AWFULCLAW_TRANSCRIPTION_ENABLED=false` disables transcription without code changes

## Non-Goals

- Streaming transcription
- Transcribing video notes or audio file attachments (only `voice` messages)
- Sending voice replies

---

## Architecture

### Transcriber Protocol

New file `agent/transcriber.py`:

```python
from typing import Protocol

class Transcriber(Protocol):
    async def transcribe(self, audio: bytes, mime_type: str) -> str: ...
```

Any class implementing `transcribe(bytes, str) -> str` satisfies the protocol — no registration or subclassing required.

### ParakeetTranscriber

New file `agent/parakeet_transcriber.py`:

- Model is loaded lazily on the first call (avoids startup delay)
- `transcribe()` runs in two steps:
  1. Write audio bytes to a temp file; call `ffmpeg` (checked for at startup via `shutil.which`) to convert OGG/Opus → WAV
  2. Run model inference in a thread via `asyncio.run_in_executor` (CPU-bound)
- Returns the transcript string
- Raises on failure — the caller handles the error

Model: `nvidia/parakeet-tdt-1.1b-v3` by default, overridable via `AWFULCLAW_PARAKEET_MODEL`.

`ffmpeg` must be present on PATH. Checked at startup; if absent and transcription is enabled, log a warning and disable transcription rather than crashing.

### TelegramConnector changes

`TelegramConnector.__init__` gains:

```python
transcriber: Transcriber | None = None
```

In `_poll`, after extracting each `msg`:

1. If `msg` has a `voice` key (no `text`) and `self._transcriber` is set:
   - Call `getFile` with `voice["file_id"]` to obtain the Telegram file path
   - Download audio bytes from `https://api.telegram.org/file/bot{token}/{file_path}`
   - Call `await self._transcriber.transcribe(audio_bytes, "audio/ogg")`
   - Set message text to `[Voice]: <transcript>`
2. If transcription fails, send an error reply to the chat and skip the message
3. If `voice` is present but no transcriber is set, skip silently (existing behaviour)

`_frame()` is unchanged — it operates on the text already populated above.

### Configuration

New `Settings` fields in `agent/config.py`:

```python
transcription_enabled: bool = True
parakeet_model: str = "nvidia/parakeet-tdt-1.1b-v3"
```

### Wiring in main.py

```python
transcriber = None
if settings.transcription_enabled:
    ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin:
        transcriber = ParakeetTranscriber(settings.parakeet_model)
    else:
        logger.warning("ffmpeg not found — voice transcription disabled")

tg = TelegramConnector(..., transcriber=transcriber)
```

### New dependency

`pyproject.toml`:

```
"nemo_toolkit[asr]>=2.0",
```

---

## Data Flow

```
Telegram poll
    → voice message detected
    → getFile → download OGG bytes
    → ParakeetTranscriber.transcribe()
        → ffmpeg: OGG → WAV (subprocess)
        → Parakeet model inference (thread executor)
        → return transcript
    → message.text = "[Voice]: <transcript>"
    → _frame() → InboundEvent → pipeline → Agent
```

---

## Error Handling

| Failure | Behaviour |
|---|---|
| `ffmpeg` not on PATH at startup | Log warning, disable transcription |
| `getFile` / download fails | Reply `"Sorry, I couldn't download that voice note."`, skip message |
| `ffmpeg` conversion fails | Reply `"Sorry, I couldn't process that voice note."`, skip message |
| Model inference fails | Reply `"Sorry, I couldn't transcribe that voice note."`, skip message |
| `AWFULCLAW_TRANSCRIPTION_ENABLED=false` | No transcriber wired, voice silently skipped |

---

## Testing

| Test file | What it covers |
|---|---|
| `tests/test_parakeet_transcriber.py` | OGG bytes written to temp file; ffmpeg called with correct args; model called; transcript returned; failures raise |
| `tests/test_telegram_voice.py` | Voice message → `[Voice]: <transcript>`; transcription failure → error reply + message skipped; voice with no transcriber → silently skipped; `getFile` failure → error reply |
| `tests/test_transcriber_protocol.py` | `ParakeetTranscriber` satisfies `Transcriber` protocol at runtime |

No live model calls or real HTTP in tests — mock at the model inference boundary and mock `httpx`.

---

## Files Changed

| File | Change |
|---|---|
| `agent/transcriber.py` | New — `Transcriber` protocol |
| `agent/parakeet_transcriber.py` | New — `ParakeetTranscriber` |
| `agent/connectors/telegram.py` | Add `transcriber` param, voice detection + download + transcription |
| `agent/config.py` | Add `transcription_enabled`, `parakeet_model` |
| `agent/main.py` | Wire `ParakeetTranscriber` into `TelegramConnector` |
| `pyproject.toml` | Add `nemo_toolkit[asr]` |
| `tests/test_parakeet_transcriber.py` | New |
| `tests/test_telegram_voice.py` | New |
| `tests/test_transcriber_protocol.py` | New |
