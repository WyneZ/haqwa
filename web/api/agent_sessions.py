"""In-memory sessions for externally connected agents."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from haqwa.core.errors import INVALID_REQUEST, SESSION_LIMIT, SESSION_NOT_FOUND, HaqwaError
from haqwa.core.events import Event
from haqwa.core.trace import TraceVocabulary
from haqwa.live.server import Fault, ShopState

MAX_EVENTS_PER_SESSION = 1000


@dataclass
class AgentSession:
    """A secret URL token and its private shop world or event trace."""

    session_id: str
    fault: Fault | None
    shop: ShopState | None
    expires_at: datetime
    calls_started: int = 0
    kind: Literal["shop", "events"] = "shop"
    events: list[Event] = field(default_factory=list)
    vocabulary: TraceVocabulary | None = None


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
        session = AgentSession(
            session_id=self._new_token(),
            fault=fault,
            shop=ShopState(fault),
            expires_at=self.clock() + timedelta(seconds=self.ttl_seconds),
        )
        self.sessions[session.session_id] = session
        return session

    def create_events(self, vocabulary: TraceVocabulary | None) -> AgentSession:
        """Create one private, expiring event trace."""
        session = AgentSession(
            session_id=self._new_token(),
            fault=None,
            shop=None,
            expires_at=self.clock() + timedelta(seconds=self.ttl_seconds),
            kind="events",
            vocabulary=vocabulary,
        )
        self.sessions[session.session_id] = session
        return session

    def _new_token(self) -> str:
        self.sweep()
        if len(self.sessions) >= self.max_sessions:
            raise HaqwaError(SESSION_LIMIT, "Session limit reached")
        return secrets.token_urlsafe(24)

    def add_events(self, token: str, events: list[Event]) -> int:
        """Append a whole batch or reject it without changing the trace."""
        session = self.get(token)
        if session.kind != "events":
            raise HaqwaError(INVALID_REQUEST, "not an events session")
        if len(session.events) + len(events) > MAX_EVENTS_PER_SESSION:
            raise HaqwaError(INVALID_REQUEST, "event limit reached")
        session.events.extend(events)
        return len(session.events)

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
