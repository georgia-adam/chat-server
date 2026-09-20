"""Pieces shared by every transport: the per-client send queue and the password check."""

from __future__ import annotations

import asyncio
import hmac

from .events import Event

QUEUE_SIZE = 256
FAIL_DELAY = 2.0  # seconds to stall a client after a wrong password
CLOSE = None  # sentinel telling a pump to stop after flushing


class QueueSink:
    """Non-blocking sink: events go on a bounded queue drained by a pump task."""

    def __init__(self, maxsize: int = QUEUE_SIZE) -> None:
        self.queue: asyncio.Queue = asyncio.Queue(maxsize)
        self.overflowed = False

    def send(self, event: Event) -> None:
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            self.overflowed = True

    def close(self) -> None:
        try:
            self.queue.put_nowait(CLOSE)
        except asyncio.QueueFull:
            self.overflowed = True


def password_matches(supplied: str, expected: str) -> bool:
    """Constant-time comparison so response timing does not leak how much of the password matched."""
    return hmac.compare_digest(supplied.encode(), expected.encode())
