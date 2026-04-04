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
