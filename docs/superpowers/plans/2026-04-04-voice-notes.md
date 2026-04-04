# Voice Note Transcription Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transcribe Telegram voice notes locally using Parakeet and inject them into the pipeline as `[Voice]: <transcript>`.

**Architecture:** A `Transcriber` protocol decouples the connector from the model. `ParakeetTranscriber` converts OGG to WAV via ffmpeg then runs NeMo inference in a thread. `TelegramConnector` detects voice messages, downloads and transcribes them, and replaces the missing text before the existing `_frame()` logic runs.

**Tech Stack:** Python, NeMo ASR (`nemo_toolkit[asr]`), ffmpeg (system binary), httpx (already in use), asyncio thread executor.

---

## File Structure

| File | Change |
|---|---|
| `agent/transcriber.py` | New — `Transcriber` protocol (`@runtime_checkable`) |
| `agent/parakeet_transcriber.py` | New — `ParakeetTranscriber`: ffmpeg conversion + NeMo inference in thread |
| `agent/config.py` | Add `transcription_enabled: bool = True` and `parakeet_model: str` |
| `agent/connectors/telegram.py` | Add `transcriber` param; `_resolve_text()` and `_download_voice()` methods; async batch loop |
| `agent/main.py` | Wire `ParakeetTranscriber` into `TelegramConnector`; ffmpeg startup check |
| `pyproject.toml` | Add `nemo_toolkit[asr]` dependency |
| `tests/test_transcriber_protocol.py` | New — protocol conformance check |
| `tests/test_parakeet_transcriber.py` | New — ffmpeg call, model call, failure cases |
| `tests/test_telegram_voice.py` | New — voice to transcript, failure to error reply, no-transcriber to skip |

---

## Task 1: `Transcriber` protocol and Settings fields

**Files:**
- Create: `agent/transcriber.py`
- Modify: `agent/config.py` (lines 50-55, after `fallback_probe_interval`)
- Test: `tests/test_transcriber_protocol.py` (new), `tests/test_config.py` (add assertions)

- [ ] **Step 1: Write the failing protocol test**

```python
# tests/test_transcriber_protocol.py
from __future__ import annotations

from agent.transcriber import Transcriber


def test_transcriber_is_a_protocol() -> None:
    # Structural check: any object with transcribe(bytes, str) -> str satisfies it
    class FakeTranscriber:
        async def transcribe(self, audio: bytes, mime_type: str) -> str:
            return "ok"

    assert isinstance(FakeTranscriber(), Transcriber)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_transcriber_protocol.py -v
```
Expected: `ImportError` or `ModuleNotFoundError` — `agent.transcriber` doesn't exist yet.

- [ ] **Step 3: Write the protocol**

Create `agent/transcriber.py`:

```python
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Transcriber(Protocol):
    async def transcribe(self, audio: bytes, mime_type: str) -> str: ...
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_transcriber_protocol.py -v
```
Expected: PASS.

- [ ] **Step 5: Add Settings fields**

In `agent/config.py`, after line 55 (`fallback_probe_interval: int = 600`), add:

```python
    transcription_enabled: bool = True
    parakeet_model: str = "nvidia/parakeet-tdt-1.1b-v3"
```

- [ ] **Step 6: Write failing config tests**

Add to the end of `tests/test_config.py`:

```python
def test_transcription_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in make_telegram_env().items():
        monkeypatch.setenv(k, v)

    settings = Settings()  # type: ignore[call-arg]

    assert settings.transcription_enabled is True
    assert settings.parakeet_model == "nvidia/parakeet-tdt-1.1b-v3"


def test_transcription_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    env = make_telegram_env()
    env["AWFULCLAW_TRANSCRIPTION_ENABLED"] = "false"
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    settings = Settings()  # type: ignore[call-arg]

    assert settings.transcription_enabled is False


def test_parakeet_model_overridable(monkeypatch: pytest.MonkeyPatch) -> None:
    env = make_telegram_env()
    env["AWFULCLAW_PARAKEET_MODEL"] = "nvidia/parakeet-tdt-0.6b-v2"
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    settings = Settings()  # type: ignore[call-arg]

    assert settings.parakeet_model == "nvidia/parakeet-tdt-0.6b-v2"
```

- [ ] **Step 7: Run config tests to verify they pass**

```bash
uv run pytest tests/test_config.py -v
```
Expected: all PASS (including the 3 new ones).

- [ ] **Step 8: Commit**

```bash
git add agent/transcriber.py agent/config.py tests/test_transcriber_protocol.py tests/test_config.py
git commit -m "feat: add Transcriber protocol and transcription settings fields"
```

---

## Task 2: `ParakeetTranscriber`

**Files:**
- Create: `agent/parakeet_transcriber.py`
- Test: `tests/test_parakeet_transcriber.py` (new)

**Context:** NeMo is a heavy optional dependency — import it only inside `_ensure_model()`, not at module level. The `transcribe()` coroutine handles async orchestration: write to temp file, call ffmpeg as a subprocess, run model inference in a thread via `run_in_executor`. `_transcribe_sync()` is the sync boundary tested independently.

- [ ] **Step 1: Write failing tests**

Create `tests/test_parakeet_transcriber.py`:

```python
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agent.parakeet_transcriber import ParakeetTranscriber
from agent.transcriber import Transcriber


def test_parakeet_satisfies_transcriber_protocol() -> None:
    assert isinstance(ParakeetTranscriber("nvidia/parakeet-tdt-1.1b-v3"), Transcriber)


@pytest.mark.asyncio
async def test_transcribe_success() -> None:
    transcriber = ParakeetTranscriber("nvidia/parakeet-tdt-1.1b-v3")

    mock_proc = MagicMock()
    mock_proc.wait = AsyncMock(return_value=None)
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
         patch.object(transcriber, "_transcribe_sync", return_value="Hello world"):
        result = await transcriber.transcribe(b"fake-ogg", "audio/ogg")

    assert result == "Hello world"


@pytest.mark.asyncio
async def test_transcribe_raises_on_ffmpeg_failure() -> None:
    transcriber = ParakeetTranscriber("nvidia/parakeet-tdt-1.1b-v3")

    mock_proc = MagicMock()
    mock_proc.wait = AsyncMock(return_value=None)
    mock_proc.returncode = 1

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(RuntimeError, match="ffmpeg failed"):
            await transcriber.transcribe(b"fake-ogg", "audio/ogg")


@pytest.mark.asyncio
async def test_temp_files_cleaned_up_on_success() -> None:
    import tempfile
    import os

    transcriber = ParakeetTranscriber("nvidia/parakeet-tdt-1.1b-v3")

    created_paths: list[str] = []
    original_ntf = tempfile.NamedTemporaryFile

    def capturing_ntf(**kwargs):  # type: ignore[no-untyped-def]
        f = original_ntf(**kwargs)
        created_paths.append(f.name)
        return f

    mock_proc = MagicMock()
    mock_proc.wait = AsyncMock(return_value=None)
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
         patch.object(transcriber, "_transcribe_sync", return_value="hi"), \
         patch("tempfile.NamedTemporaryFile", side_effect=capturing_ntf):
        await transcriber.transcribe(b"fake-ogg", "audio/ogg")

    for path in created_paths:
        assert not os.path.exists(path), f"temp file not cleaned up: {path}"


def test_transcribe_sync_calls_model() -> None:
    transcriber = ParakeetTranscriber("nvidia/parakeet-tdt-1.1b-v3")

    mock_model = MagicMock()
    mock_model.transcribe.return_value = ["Hello from model"]
    transcriber._model = mock_model  # bypass lazy load

    result = transcriber._transcribe_sync("/tmp/test.wav")

    mock_model.transcribe.assert_called_once_with(["/tmp/test.wav"])
    assert result == "Hello from model"


def test_transcribe_sync_returns_empty_on_no_output() -> None:
    transcriber = ParakeetTranscriber("nvidia/parakeet-tdt-1.1b-v3")

    mock_model = MagicMock()
    mock_model.transcribe.return_value = []
    transcriber._model = mock_model

    result = transcriber._transcribe_sync("/tmp/test.wav")

    assert result == ""
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_parakeet_transcriber.py -v
```
Expected: `ImportError` — `agent.parakeet_transcriber` doesn't exist yet.

- [ ] **Step 3: Write the implementation**

Create `agent/parakeet_transcriber.py`:

```python
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from typing import Any


class ParakeetTranscriber:
    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model: Any = None  # loaded lazily on first call

    async def transcribe(self, audio: bytes, mime_type: str) -> str:
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            f.write(audio)
            in_path = f.name

        out_path = in_path[:-4] + ".wav"

        try:
            ffmpeg = shutil.which("ffmpeg")
            if ffmpeg is None:
                raise RuntimeError("ffmpeg not found in PATH")

            proc = await asyncio.create_subprocess_exec(
                ffmpeg, "-y", "-i", in_path, "-ar", "16000", "-ac", "1", out_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            if proc.returncode != 0:
                raise RuntimeError(f"ffmpeg failed with exit code {proc.returncode}")

            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self._transcribe_sync, out_path)
        finally:
            os.unlink(in_path)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def _transcribe_sync(self, wav_path: str) -> str:
        self._ensure_model()
        transcriptions = self._model.transcribe([wav_path])
        return str(transcriptions[0]) if transcriptions else ""

    def _ensure_model(self) -> None:
        if self._model is None:
            import nemo.collections.asr as nemo_asr  # deferred: heavy dep
            self._model = nemo_asr.models.ASRModel.from_pretrained(self._model_name)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_parakeet_transcriber.py -v
```
Expected: all 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/parakeet_transcriber.py tests/test_parakeet_transcriber.py
git commit -m "feat: add ParakeetTranscriber with ffmpeg conversion and NeMo inference"
```

---

## Task 3: `TelegramConnector` voice handling

**Files:**
- Modify: `agent/connectors/telegram.py`
- Test: `tests/test_telegram_voice.py` (new)

**Context:** Current `_poll` loop builds combined text synchronously via `_frame()`. The change makes the batch loop async: each message goes through `_resolve_text()` which handles both text and voice. `_download_voice()` calls `getFile` then fetches the audio bytes. On failure, `send()` dispatches the error reply and the message is skipped (returning `""`). The batch is skipped entirely if `combined` is empty after processing. `_frame()` is unchanged.

- [ ] **Step 1: Write failing tests**

Create `tests/test_telegram_voice.py`:

```python
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agent.connectors import InboundEvent, OutboundMessage
from agent.connectors.telegram import TelegramConnector


def make_voice_update(
    update_id: int,
    chat_id: int,
    file_id: str = "FILEID123",
    user_id: int = 99,
    username: str = "alice",
) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": user_id, "first_name": username, "username": username},
            "voice": {"file_id": file_id, "duration": 5, "mime_type": "audio/ogg"},
        },
    }


def make_store(offset: str | None = None) -> MagicMock:
    store = MagicMock()
    store.kv_get = AsyncMock(return_value=offset)
    store.kv_set = AsyncMock()
    return store


def make_mock_client(get_side_effect: list) -> MagicMock:
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=get_side_effect)
    mock_client.post = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


def make_getfile_resp(file_path: str = "voice/file.ogg") -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={"result": {"file_path": file_path}})
    return resp


def make_download_resp(content: bytes = b"fake-ogg-data") -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.content = content
    return resp


def make_poll_resp(updates: dict) -> MagicMock:
    resp = MagicMock()
    resp.json = MagicMock(return_value=updates)
    return resp


@pytest.mark.asyncio
async def test_voice_message_transcribed() -> None:
    store = make_store()
    transcriber = MagicMock()
    transcriber.transcribe = AsyncMock(return_value="Hello from voice")

    connector = TelegramConnector(
        token="tok", allowed_chat_ids=[100], store=store, transcriber=transcriber
    )

    updates = {"result": [make_voice_update(1, 100, file_id="FILE123")]}

    received: list[InboundEvent] = []

    async def on_message(event: InboundEvent) -> None:
        received.append(event)
        connector._running = False

    mock_client = make_mock_client([
        make_poll_resp(updates),   # getUpdates
        make_getfile_resp(),       # getFile
        make_download_resp(),      # file download
    ])

    with patch("agent.connectors.telegram.httpx.AsyncClient", return_value=mock_client):
        await connector.start(on_message)

    assert len(received) == 1
    assert received[0].message.text == "[Voice]: Hello from voice"
    transcriber.transcribe.assert_called_once_with(b"fake-ogg-data", "audio/ogg")


@pytest.mark.asyncio
async def test_voice_transcription_failure_sends_error_and_skips() -> None:
    store = make_store()

    async def stop_after_set(key: str, value: str) -> None:
        connector._running = False

    store.kv_set = AsyncMock(side_effect=stop_after_set)

    transcriber = MagicMock()
    transcriber.transcribe = AsyncMock(side_effect=RuntimeError("model exploded"))

    connector = TelegramConnector(
        token="tok", allowed_chat_ids=[100], store=store, transcriber=transcriber
    )

    updates = {"result": [make_voice_update(1, 100)]}

    received: list[InboundEvent] = []

    async def on_message(event: InboundEvent) -> None:
        received.append(event)

    mock_client = make_mock_client([
        make_poll_resp(updates),
        make_getfile_resp(),
        make_download_resp(),
    ])

    with patch("agent.connectors.telegram.httpx.AsyncClient", return_value=mock_client):
        await connector.start(on_message)

    assert len(received) == 0
    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args[1]
    assert call_kwargs["json"]["text"] == "Sorry, I couldn't transcribe that voice note."


@pytest.mark.asyncio
async def test_voice_download_failure_sends_error_and_skips() -> None:
    store = make_store()

    async def stop_after_set(key: str, value: str) -> None:
        connector._running = False

    store.kv_set = AsyncMock(side_effect=stop_after_set)

    transcriber = MagicMock()
    transcriber.transcribe = AsyncMock()

    connector = TelegramConnector(
        token="tok", allowed_chat_ids=[100], store=store, transcriber=transcriber
    )

    updates = {"result": [make_voice_update(1, 100)]}

    received: list[InboundEvent] = []

    async def on_message(event: InboundEvent) -> None:
        received.append(event)

    failing_getfile = MagicMock()
    failing_getfile.raise_for_status = MagicMock(side_effect=Exception("getFile failed"))

    mock_client = make_mock_client([
        make_poll_resp(updates),
        failing_getfile,
    ])

    with patch("agent.connectors.telegram.httpx.AsyncClient", return_value=mock_client):
        await connector.start(on_message)

    assert len(received) == 0
    transcriber.transcribe.assert_not_called()
    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args[1]
    assert call_kwargs["json"]["text"] == "Sorry, I couldn't transcribe that voice note."


@pytest.mark.asyncio
async def test_voice_without_transcriber_silently_skipped() -> None:
    store = make_store()

    async def stop_after_set(key: str, value: str) -> None:
        connector._running = False

    store.kv_set = AsyncMock(side_effect=stop_after_set)

    connector = TelegramConnector(
        token="tok", allowed_chat_ids=[100], store=store
    )

    updates = {"result": [make_voice_update(1, 100)]}

    received: list[InboundEvent] = []

    async def on_message(event: InboundEvent) -> None:
        received.append(event)

    mock_client = make_mock_client([make_poll_resp(updates)])

    with patch("agent.connectors.telegram.httpx.AsyncClient", return_value=mock_client):
        await connector.start(on_message)

    assert len(received) == 0
    mock_client.post.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_telegram_voice.py -v
```
Expected: 4 FAIL — `TelegramConnector` doesn't accept a `transcriber` argument yet.

- [ ] **Step 3: Update `agent/connectors/telegram.py`**

Read the current file first (`agent/connectors/telegram.py`), then apply these four changes.

**Change 1** — add import at top, after `from agent.connectors import ...`:
```python
from agent.transcriber import Transcriber
```

**Change 2** — `__init__` signature: add `transcriber: Transcriber | None = None` parameter and store it:
```python
    def __init__(self, token: str, allowed_chat_ids: list[int], store: Any, owner_id: int | None = None, transcriber: "Transcriber | None" = None) -> None:
        self._token = token
        self._allowed_chat_ids = set(allowed_chat_ids)
        self._store = store
        self._owner_id = owner_id
        self._transcriber = transcriber
        self._running = False
        self._client: httpx.AsyncClient | None = None
```

**Change 3** — replace the synchronous batch dispatch loop in `_poll`:

Old block (starting at `for chat_id, msgs in batches.items():`):
```python
        for chat_id, msgs in batches.items():
            combined = "\n".join(self._frame(m) for m in msgs)
            first = msgs[0]
            from_user = first.get("from", {})
            sender_id = str(from_user.get("id", chat_id))
            sender_name = from_user.get("first_name", sender_id)

            message = Message(text=combined, sender=sender_id, sender_name=sender_name)
            event = InboundEvent(channel=str(chat_id), message=message, connector_name="telegram")
            await on_message(event)
```

New block:
```python
        for chat_id, msgs in batches.items():
            parts: list[str] = []
            for m in msgs:
                text = await self._resolve_text(m, chat_id)
                if text:
                    parts.append(text)
            combined = "\n".join(parts)
            if not combined:
                continue

            first = msgs[0]
            from_user = first.get("from", {})
            sender_id = str(from_user.get("id", chat_id))
            sender_name = from_user.get("first_name", sender_id)

            message = Message(text=combined, sender=sender_id, sender_name=sender_name)
            event = InboundEvent(channel=str(chat_id), message=message, connector_name="telegram")
            await on_message(event)
```

**Change 4** — add `_resolve_text` and `_download_voice` methods immediately before `_frame`:

```python
    async def _resolve_text(self, msg: dict[str, Any], chat_id: int) -> str:
        if "text" in msg:
            return self._frame(msg)
        if "voice" in msg and self._transcriber is not None:
            try:
                audio = await self._download_voice(msg["voice"]["file_id"])
                transcript = await self._transcriber.transcribe(audio, "audio/ogg")
                framed = dict(msg)
                framed["text"] = f"[Voice]: {transcript}"
                return self._frame(framed)
            except Exception:
                await self.send(str(chat_id), OutboundMessage(text="Sorry, I couldn't transcribe that voice note."))
                return ""
        return self._frame(msg)

    async def _download_voice(self, file_id: str) -> bytes:
        assert self._client is not None  # always set when called from _poll
        resp = await self._client.get(self._url("getFile"), params={"file_id": file_id})
        resp.raise_for_status()
        file_path = resp.json()["result"]["file_path"]
        file_url = f"https://api.telegram.org/file/bot{self._token}/{file_path}"
        resp = await self._client.get(file_url)
        resp.raise_for_status()
        return resp.content
```

- [ ] **Step 4: Run voice tests to verify they pass**

```bash
uv run pytest tests/test_telegram_voice.py -v
```
Expected: 4 PASS.

- [ ] **Step 5: Run full connector test suite to verify no regression**

```bash
uv run pytest tests/test_connectors_telegram.py tests/test_telegram_voice.py -v
```
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add agent/connectors/telegram.py tests/test_telegram_voice.py
git commit -m "feat: add voice note transcription to TelegramConnector"
```

---

## Task 4: Wire in `main.py` and add `nemo_toolkit` dependency

**Files:**
- Modify: `agent/main.py`
- Modify: `pyproject.toml`

**Context:** The wiring is minimal — check for `ffmpeg` at startup, create `ParakeetTranscriber` if enabled and ffmpeg is present, pass to `TelegramConnector`. No new tests needed; the logic is covered by Tasks 2 and 3.

- [ ] **Step 1: Add `nemo_toolkit[asr]` to `pyproject.toml`**

Read `pyproject.toml` first. In the `dependencies` list, add after `"aioimaplib>=2.0",`:
```toml
    "nemo_toolkit[asr]>=2.0",
```

- [ ] **Step 2: Add `shutil` import to `main.py`**

Read `agent/main.py` first. After the existing `import os` line, add:
```python
import shutil
```

- [ ] **Step 3: Add `ParakeetTranscriber` import to `main.py`**

After the existing `from agent.store import Store` import line, add:
```python
from agent.parakeet_transcriber import ParakeetTranscriber
from agent.transcriber import Transcriber
```

- [ ] **Step 4: Add transcriber wiring in `main.py`**

Find this block in `main()` (around line 167):
```python
        if "telegram" in args.connectors:
            if settings.telegram is None:
                raise ValueError("AWFULCLAW_TELEGRAM__BOT_TOKEN and AWFULCLAW_TELEGRAM__ALLOWED_CHAT_IDS are required for the telegram connector")
            connectors["telegram"] = TelegramConnector(
                token=settings.telegram.bot_token,
                allowed_chat_ids=settings.telegram.allowed_chat_ids,
                store=store,
            )
```

Replace with:
```python
        if "telegram" in args.connectors:
            if settings.telegram is None:
                raise ValueError("AWFULCLAW_TELEGRAM__BOT_TOKEN and AWFULCLAW_TELEGRAM__ALLOWED_CHAT_IDS are required for the telegram connector")
            transcriber: Transcriber | None = None
            if settings.transcription_enabled:
                if shutil.which("ffmpeg"):
                    transcriber = ParakeetTranscriber(settings.parakeet_model)
                else:
                    print("[startup] WARNING: ffmpeg not found — voice transcription disabled", flush=True)
            connectors["telegram"] = TelegramConnector(
                token=settings.telegram.bot_token,
                allowed_chat_ids=settings.telegram.allowed_chat_ids,
                store=store,
                transcriber=transcriber,
            )
```

- [ ] **Step 5: Run the full test suite**

```bash
uv run pytest --ignore=tests/test_live_agent.py -q
```
Expected: same pass/fail split as before this task. Pre-existing failures are in `test_claude_client.py`, `test_agent_integration.py`, `test_middleware_typing.py`, and `test_pipeline.py` — these are unrelated to this feature. All new tests pass.

- [ ] **Step 6: Commit**

```bash
git add agent/main.py pyproject.toml
git commit -m "feat: wire ParakeetTranscriber into TelegramConnector with ffmpeg startup check"
```
