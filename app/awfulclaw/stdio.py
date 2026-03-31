"""Stdio connector — read messages from stdin, write replies to stdout."""

from __future__ import annotations

import queue
import sys
import threading
from datetime import datetime, timezone

from awfulclaw.connector import Connector, Message


class StdioConnector(Connector):
    """Connector that reads lines from stdin and writes to stdout.

    Useful for local testing without Telegram. Run with:
        AWFULCLAW_CHANNEL=stdio uv run python -m awfulclaw
    """

    def __init__(self) -> None:
        self._queue: queue.Queue[str] = queue.Queue()
        t = threading.Thread(target=self._read_stdin, daemon=True)
        t.start()

    def _read_stdin(self) -> None:
        for line in sys.stdin:
            line = line.rstrip("\n")
            if line:
                self._queue.put(line)

    @property
    def primary_recipient(self) -> str:
        return "user"

    def poll_new_messages(self, since: datetime) -> list[Message]:
        messages: list[Message] = []
        while True:
            try:
                line = self._queue.get_nowait()
                messages.append(
                    Message(
                        sender="user",
                        body=line,
                        timestamp=datetime.now(timezone.utc),
                        is_from_me=False,
                        channel="stdio",
                    )
                )
            except queue.Empty:
                break
        return messages

    def send_message(self, to: str, body: str) -> None:
        print(body, flush=True)
