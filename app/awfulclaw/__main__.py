"""Entry point for `python -m awfulclaw`."""

import asyncio
import logging
import os

from awfulclaw import config, loop
from awfulclaw.gateway import Gateway

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    print("awfulclaw v0.1.0 — iMessage AI agent")
    print("Use Ctrl-C to exit.")
    try:
        channel = config.get_channel()
        connector = config.get_connector()
        connectors = [(channel, connector)]

        extra = os.getenv("AWFULCLAW_EXTRA_CHANNELS", "").strip().lower()
        if "stdio" in extra:
            from awfulclaw.stdio import StdioConnector
            connectors.append(("stdio", StdioConnector()))

        gateway = Gateway(connectors)
        asyncio.run(loop.run(gateway))
    except RuntimeError as exc:
        logging.error("%s", exc)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
