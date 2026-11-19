"""Start the server: python -m sayitship"""

import logging
import os
import re
import socket
import sys
import time

import uvicorn

from .config import load_settings


def wait_for_address(host: str, port: int, seconds: int = 180) -> None:
    """At login the Tailscale address may not exist yet; wait for it instead of crashing."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            with socket.socket() as s:
                s.bind((host, port))
            return
        except OSError:
            if time.monotonic() > deadline:
                raise
            logging.getLogger("sayitship").info("waiting for %s:%s to become available", host, port)
            time.sleep(5)


class AccessLogFilter(logging.Filter):
    """Hide the approval hook's once-a-second polling and never log one-time approval keys."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if "/internal/approvals/" in message:
            return False
        if "key=" in message:
            record.msg, record.args = re.sub(r"key=[^\s\"&]+", "key=***", message), ()
        return True


def main() -> None:
    settings = load_settings()  # fail fast on a bad .env or projects.json
    handlers: list[logging.Handler] = [
        logging.FileHandler(settings.data_dir / "sayitship.log", encoding="utf-8")
    ]
    if sys.stderr is not None:  # pythonw (autostart) has no console
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers
    )
    logging.getLogger("uvicorn.access").addFilter(AccessLogFilter())
    host = os.environ.get("HOST", "127.0.0.1")  # set this to your Tailscale IP
    port = int(os.environ.get("PORT", "8787"))
    wait_for_address(host, port)
    uvicorn.run("sayitship.main:app", host=host, port=port, log_config=None)


if __name__ == "__main__":
    main()
