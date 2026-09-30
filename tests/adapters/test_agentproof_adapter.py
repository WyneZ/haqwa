from dataclasses import dataclass, field
from datetime import UTC, datetime

from haqwa.adapters.agentproof import DEFAULT_ANCHOR, effects_to_events


@dataclass
class FakeEffect:  # same attributes as agentproof.Effect
    id: str
    type: str
    committed_at: float
    data: dict = field(default_factory=dict)


def test_effects_become_events_in_order():
    effects = [
        FakeEffect("eff_001", "order_created", 0.0, {"order_id": "A-1"}),
        FakeEffect("eff_002", "charged", 2.5, {"order_id": "A-1", "amount": 50}),
    ]
    events = effects_to_events(effects)
    assert [e.event for e in events] == ["order_created", "charged"]
    assert events[1].ts == DEFAULT_ANCHOR.replace(second=2, microsecond=500000)
    assert events[1].data == {"order_id": "A-1", "amount": 50}
    assert events[1].source_id == "eff_002"


def test_custom_anchor():
    anchor = datetime(2030, 5, 1, tzinfo=UTC)
    (event,) = effects_to_events([FakeEffect("e", "x", 60.0)], anchor=anchor)
    assert event.ts == anchor.replace(minute=1)
