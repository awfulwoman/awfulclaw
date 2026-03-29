"""Entry point for `python -m awfulclaw`."""

import logging

from awfulclaw import loop

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    print("awfulclaw v0.1.0 — iMessage AI agent")
    print("Use Ctrl-C to exit.")
    try:
        loop.run()
    except RuntimeError as exc:
        logging.error("%s", exc)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
