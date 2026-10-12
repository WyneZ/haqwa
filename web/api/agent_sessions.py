"""In-memory sessions for externally connected MCP agents."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from haqwa.core.errors import SESSION_LIMIT, SESSION_NOT_FOUND, HaqwaError
from haqwa.live.server import Fault, ShopState


@dataclass
class AgentSession:
    """A secret URL token and its private shop world."""

    session_id: str
    fault: Fault
    shop: ShopState
    expires_at: datetime
    calls_started: int = 0


class AgentSessionStore:
    """Keep bounded, expiring sessions in one API process."""

    def __init__(
        self,
        max_sessions: int = 20,
        ttl_seconds: int = 1800,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if max_sessions < 1 or ttl_seconds < 1:
            raise ValueError("session limits must be positive")
        self.max_sessions = max_sessions
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self.sessions: dict[str, AgentSession] = {}

    def sweep(self) -> None:
        """Discard sessions whose deadline has passed."""
        now = self.clock()
        for token, session in list(self.sessions.items()):
            if session.expires_at <= now:
                del self.sessions[token]

    def create(self, fault: Fault) -> AgentSession:
        """Create one private shop, after removing expired sessions."""
        self.sweep()
        if len(self.sessions) >= self.max_sessions:
            raise HaqwaError(SESSION_LIMIT, "Session limit reached")
        token = secrets.token_urlsafe(24)
        session = AgentSession(
            session_id=token,
            fault=fault,
            shop=ShopState(fault),
            expires_at=self.clock() + timedelta(seconds=self.ttl_seconds),
        )
        self.sessions[token] = session
        return session

    def get(self, token: str) -> AgentSession:
        """Find a live session or report the same error for unknown and expired tokens."""
        self.sweep()
        try:
            return self.sessions[token]
        except KeyError as exc:
            raise HaqwaError(SESSION_NOT_FOUND, "Session not found or expired") from exc

    def delete(self, token: str) -> None:
        """Remove a live session."""
        self.get(token)
        del self.sessions[token]
