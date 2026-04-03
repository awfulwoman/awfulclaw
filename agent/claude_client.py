from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path


class ClaudeClient:
    def __init__(self, model: str) -> None:
        self.model = model

    async def complete(
        self,
        prompt: str,
        system_prompt: str,
        mcp_config_path: Path,
        allowed_tools: list[str],
    ) -> str:
        claude_bin = shutil.which("claude")
        if claude_bin is None:
            raise FileNotFoundError(
                "claude CLI not found in PATH — install it from https://claude.ai/download"
            )

        cmd = [
            claude_bin,
            "--print",
            "--output-format", "stream-json",
            "--verbose",
            "--model", self.model,
        ]
        if allowed_tools:
            cmd += ["--allowedTools", ",".join(allowed_tools)]
        else:
            cmd += ["--dangerously-skip-permissions"]
        cmd += ["--mcp-config", str(mcp_config_path)]

        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt

        last_error: str = ""
        for attempt in range(3):
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate(full_prompt.encode())

            if proc.returncode == 0:
                return _parse_stream_json(stdout.decode())

            last_error = stderr.decode().strip()
            if attempt < 2:
                await asyncio.sleep(2**attempt)

        raise RuntimeError(
            f"Claude CLI failed after 3 attempts: {last_error}"
        )


def _parse_stream_json(output: str) -> str:
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
            if event.get("type") == "result":
                return str(event.get("result", ""))
        except json.JSONDecodeError:
            continue
    return ""
