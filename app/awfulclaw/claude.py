"""Calls the claude CLI via subprocess, or the Anthropic SDK for vision messages."""

from __future__ import annotations

import base64
import logging
import os
import pathlib
import subprocess
import time as _time

from awfulclaw import config

logger = logging.getLogger(__name__)


class ClaudeSession:
    """Persistent claude subprocess that reuses a live process between calls."""

    SENTINEL_START = "---AWFULCLAW_OUTPUT_START---"
    SENTINEL_END = "---AWFULCLAW_OUTPUT_END---"
    IDLE_TIMEOUT = 120  # seconds; overridden by AWFULCLAW_SESSION_TIMEOUT env var

    def __init__(self, system: str) -> None:
        self._system = system
        self._idle_timeout = int(os.getenv("AWFULCLAW_SESSION_TIMEOUT", str(self.IDLE_TIMEOUT)))
        self._process: subprocess.Popen[str] | None = None
        self._last_used: float = 0.0
        self._spawn()

    def _spawn(self) -> None:
        sentinel_instruction = (
            f"IMPORTANT: Always begin your response with the exact line "
            f"'{self.SENTINEL_START}' and end it with the exact line "
            f"'{self.SENTINEL_END}'."
        )
        augmented_system = f"{sentinel_instruction}\n\n{self._system}"
        cmd = [
            "claude",
            "--print",
            "--system-prompt", augmented_system,
            "--model", config.get_model(),
            "--allowedTools", ",".join(config.get_allowed_tools()),
        ]
        cmd = _wrap_sandbox(cmd)
        self._process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._last_used = _time.monotonic()

    def is_alive(self) -> bool:
        """Return True if the subprocess is running and not idle-timed-out."""
        if self._process is None:
            return False
        if self._process.poll() is not None:
            return False
        if _time.monotonic() - self._last_used > self._idle_timeout:
            return False
        return True

    def send(self, messages: list[dict[str, str]]) -> str:
        """Send messages to the persistent subprocess and return the reply."""
        if not self.is_alive():
            self._spawn()

        proc = self._process
        assert proc is not None
        assert proc.stdin is not None
        assert proc.stdout is not None

        prompt = _format_messages(messages)
        proc.stdin.write(prompt + "\n")
        proc.stdin.flush()
        self._last_used = _time.monotonic()

        lines: list[str] = []
        in_response = False
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            stripped = line.rstrip("\n")
            if stripped == self.SENTINEL_START:
                in_response = True
                continue
            if stripped == self.SENTINEL_END:
                break
            if in_response:
                lines.append(stripped)

        return "\n".join(lines).strip()

    def close(self) -> None:
        """Terminate the subprocess cleanly."""
        if self._process is not None:
            self._process.terminate()
            self._process = None


def chat(
    messages: list[dict[str, str]],
    system: str,
    image_data: bytes | None = None,
    image_mime: str | None = None,
    mcp_config_path: pathlib.Path | None = None,
) -> str:
    """Invoke claude and return the assistant reply text.

    If *image_data* is provided the Anthropic SDK is used directly (vision path).
    Otherwise the claude CLI subprocess is used.
    """
    if image_data is not None:
        return _chat_sdk(messages, system, image_data, image_mime or "image/jpeg")
    return _chat_cli(messages, system, mcp_config_path=mcp_config_path)


def _wrap_sandbox(cmd: list[str]) -> list[str]:
    """Wrap *cmd* with sandbox-exec if AWFULCLAW_SANDBOX=1."""
    if not config.get_sandbox():
        return cmd
    sb_profile = pathlib.Path(__file__).parent.parent / "scripts" / "sandbox.sb"
    project_path = str((pathlib.Path(__file__).parent.parent).resolve())
    memory_path = str((pathlib.Path(__file__).parent.parent / "memory").resolve())
    home_path = str(pathlib.Path.home())
    return [
        "sandbox-exec",
        "-f", str(sb_profile),
        "-D", f"PROJECT_PATH={project_path}",
        "-D", f"MEMORY_PATH={memory_path}",
        "-D", f"HOME={home_path}",
    ] + cmd


def _chat_cli(
    messages: list[dict[str, str]],
    system: str,
    mcp_config_path: pathlib.Path | None = None,
) -> str:
    """Invoke the claude CLI and return the assistant reply text."""
    prompt = _format_messages(messages)

    cmd = [
        "claude",
        "--print",
        "--no-session-persistence",
        "--system-prompt", system,
        "--model", config.get_model(),
        "--allowedTools", ",".join(config.get_allowed_tools()),
    ]
    if mcp_config_path is not None:
        cmd += ["--mcp-config", str(mcp_config_path)]
    cmd = _wrap_sandbox(cmd)

    result = subprocess.run(cmd, input=prompt, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"claude CLI exited {result.returncode}: {result.stderr.strip()}")

    return result.stdout.strip()


def _chat_sdk(
    messages: list[dict[str, str]],
    system: str,
    image_data: bytes,
    image_mime: str,
) -> str:
    """Use the Anthropic SDK to send a message with an image on the last user turn."""
    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError(
            "anthropic package is required for image support. "
            "Install it with: uv add anthropic"
        ) from exc

    client = anthropic.Anthropic()
    b64 = base64.standard_b64encode(image_data).decode()

    sdk_messages: list[anthropic.types.MessageParam] = []

    # All but the last message as plain text turns.
    for msg in messages[:-1]:
        role: anthropic.types.MessageParamTypedDict = (  # type: ignore[assignment]
            "user" if msg["role"] == "user" else "assistant"
        )
        sdk_messages.append({"role": role, "content": msg["content"]})

    # Last message gets the image appended.
    last = messages[-1]
    last_content: list[anthropic.types.ContentBlockParam] = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": image_mime,  # type: ignore[typeddict-item]
                "data": b64,
            },
        },
        {"type": "text", "text": last["content"]},
    ]
    sdk_messages.append({"role": "user", "content": last_content})  # type: ignore[arg-type]

    response = client.messages.create(
        model=config.get_model(),
        max_tokens=4096,
        system=system,
        messages=sdk_messages,  # type: ignore[arg-type]
    )

    text_blocks = [b.text for b in response.content if b.type == "text"]
    return "\n".join(text_blocks).strip()


def _format_messages(messages: list[dict[str, str]]) -> str:
    """Render message history as plain text so the CLI receives full context."""
    if not messages:
        return ""

    # All but the last message become a labelled history block.
    history_parts: list[str] = []
    for msg in messages[:-1]:
        label = "Human" if msg["role"] == "user" else "Assistant"
        history_parts.append(f"{label}: {msg['content']}")

    last = messages[-1]
    if history_parts:
        history = "\n\n".join(history_parts)
        return f"Previous conversation:\n{history}\n\nHuman: {last['content']}"
    return last["content"]
