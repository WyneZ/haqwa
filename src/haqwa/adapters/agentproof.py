"""AgentProof effect ledger -> Haqwa C2 events.

Duck-typed on purpose: it reads `type`, `data`, `committed_at`, `id` from each effect,
so this module does not import agentproof and core stays framework-agnostic.
Tested against agentproof-sim==0.1.1 (see spikes/agentproof/NOTES.md).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from ..core.events import Event

# AgentProof's virtual clock is float seconds from 0; anchor it to a fixed UTC time.
DEFAULT_ANCHOR = datetime(2026, 1, 1, tzinfo=UTC)


def effects_to_events(effects: Iterable[Any], anchor: datetime = DEFAULT_ANCHOR) -> list[Event]:
    """Convert AgentProof `Effect`s (in commit order) to Haqwa events."""
    return [
        Event(
            event=e.type,
            ts=anchor + timedelta(seconds=float(e.committed_at)),
            data=dict(e.data),
            source_id=e.id,
        )
        for e in effects
    ]
