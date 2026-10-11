"""In-memory sliding windows for the two Gemini-backed routes."""

from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import Request

from haqwa.core.errors import RATE_LIMITED, HaqwaError


class RateLimiter:
    """Count admitted requests per IP and across this single API instance."""

    def __init__(
        self, per_minute: int = 10, per_day: int = 200, clock: Callable[[], float] = time.time
    ) -> None:
        if per_minute < 1 or per_day < 1:
            raise ValueError("rate limits must be positive")
        self.per_minute = per_minute
        self.per_day = per_day
        self.clock = clock
        self.clients: dict[str, deque[float]] = defaultdict(deque)
        self.global_requests: deque[float] = deque()

    def check(self, ip: str) -> None:
        """Admit one request, or report the first time a slot becomes available."""
        now = self.clock()
        recent = self.clients[ip]
        while recent and recent[0] <= now - 60:
            recent.popleft()
        while self.global_requests and self.global_requests[0] <= now - 86400:
            self.global_requests.popleft()
        waits = []
        if len(recent) >= self.per_minute:
            waits.append(recent[0] + 60 - now)
        if len(self.global_requests) >= self.per_day:
            waits.append(self.global_requests[0] + 86400 - now)
        if waits:
            seconds = max(1, math.ceil(max(waits)))
            raise HaqwaError(RATE_LIMITED, f"Rate limit reached; retry in {seconds} seconds.")
        recent.append(now)
        self.global_requests.append(now)


def client_ip(request: Request) -> str:
    """Use Cloud Run's first forwarded hop, then the direct socket address."""
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return forwarded or (request.client.host if request.client else "unknown")
