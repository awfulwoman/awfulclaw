from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import time
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
        # The claude CLI only supports stdio (command-based) MCP servers.
        # Filter out url-based servers (e.g. remote SSE/HTTP) to avoid schema errors.
        raw = json.loads(mcp_config_path.read_text())
        servers = raw.get("mcpServers", raw)
        stdio_servers = {k: v for k, v in servers.items() if "command" in v}
        if len(stdio_servers) < len(servers):
            filtered = {"mcpServers": stdio_servers}
            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, dir=mcp_config_path.parent
            )
            json.dump(filtered, tmp)
            tmp.flush()
            effective_config = Path(tmp.name)
        else:
            effective_config = mcp_config_path
        cmd += ["--mcp-config", str(effective_config)]

        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt

        last_error: str = ""
        try:
            for attempt in range(3):
                t0 = time.perf_counter()
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await proc.communicate(full_prompt.encode())
                elapsed = time.perf_counter() - t0
                print(f"[timing] claude attempt={attempt + 1} rc={proc.returncode} {elapsed:.2f}s", flush=True)

                if proc.returncode == 0:
                    return _parse_stream_json(stdout.decode())

                last_error = stderr.decode().strip()
                if attempt < 2:
                    await asyncio.sleep(2**attempt)
        finally:
            if effective_config != mcp_config_path:
                effective_config.unlink(missing_ok=True)

        raise RuntimeError(
            f"Claude CLI failed after 3 attempts: {last_error}"
        )

    async def health_check(self) -> bool:
        claude_bin = shutil.which("claude")
        if claude_bin is None:
            return False
        proc = await asyncio.create_subprocess_exec(
            claude_bin, "--version",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        return proc.returncode == 0


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
