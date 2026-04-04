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
