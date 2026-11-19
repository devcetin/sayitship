"""Send a push notification through ntfy."""

import logging

import httpx

log = logging.getLogger("sayitship")


def send_notification(server: str, topic: str, title: str, message: str) -> bool:
    # JSON publishing: unlike HTTP headers, the JSON body can carry non-ASCII text (ş, ğ, ı).
    try:
        response = httpx.post(
            server,
            json={"topic": topic, "title": title, "message": message},
            timeout=10,
        )
        response.raise_for_status()
        return True
    except httpx.HTTPError as exc:
        # A failed notification must not crash the worker.
        log.warning("ntfy notification failed: %s", exc)
        return False
