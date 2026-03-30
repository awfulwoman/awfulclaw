"""Entry point for `python -m awfulclaw`."""

import asyncio
import logging

from awfulclaw import config, loop
from awfulclaw.gateway import Gateway

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    print("awfulclaw v0.1.0 — iMessage AI agent")
    print("Use Ctrl-C to exit.")
    try:
        connector = config.get_connector()
        channel = config.get_channel()
        gateway = Gateway([(channel, connector)])
        asyncio.run(loop.run(gateway))
    except RuntimeError as exc:
        logging.error("%s", exc)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
