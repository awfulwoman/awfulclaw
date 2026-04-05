"""Smoke test: send one prompt to Claude and print the reply."""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path


async def run() -> None:
    # Import here so errors surface clearly
    from agent.config import Settings
    from agent.store import Store
    from agent.claude_client import ClaudeClient

    settings = Settings()  # type: ignore[call-arg]

    with tempfile.TemporaryDirectory() as tmpdir:
        store = await Store.connect(Path(tmpdir) / "smoke.db")
        try:
            client = ClaudeClient(model=settings.backend.claude_model)

            # Use an empty MCP config so no servers are required
            mcp_config = Path(tmpdir) / "mcp.json"
            mcp_config.write_text("{}")

            print("Sending prompt: What is 2+2?")
            reply = await client.complete(
                prompt="What is 2+2?",
                system_prompt="",
                mcp_config_path=mcp_config,
                allowed_tools=[],
            )
            print(f"Reply: {reply}")
        finally:
            await store.close()


def main() -> None:
    try:
        asyncio.run(run())
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
