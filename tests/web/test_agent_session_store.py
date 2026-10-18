"""Store behavior shared by shop and event sessions."""

from datetime import UTC, datetime, timedelta

import pytest

from haqwa.core.errors import HaqwaError
from haqwa.core.events import Event
from haqwa.core.trace import TraceVocabulary
from web.api.agent_sessions import MAX_EVENTS_PER_SESSION, AgentSessionStore


def event() -> Event:
    return Event(event="order_approved", ts=datetime(2026, 1, 1, tzinfo=UTC))


def test_events_create_get_and_expire() -> None:
    now = [datetime(2026, 1, 1, tzinfo=UTC)]
    store = AgentSessionStore(ttl_seconds=30, clock=lambda: now[0])
    vocabulary = TraceVocabulary(events=["order_approved"], fields=[], field_values={})

    session = store.create_events(vocabulary)
    assert session.kind == "events"
    assert session.fault is None and session.shop is None
    assert session.vocabulary is vocabulary
    assert session.events == []
    assert session.expires_at == now[0] + timedelta(seconds=30)
    assert store.get(session.session_id) is session
    assert store.add_events(session.session_id, [event()]) == 1
    assert store.get(session.session_id).events == [event()]

    now[0] += timedelta(seconds=30)
    with pytest.raises(HaqwaError) as exc:
        store.get(session.session_id)
    assert exc.value.code == "session_not_found"


def test_event_cap_rejects_entire_batch() -> None:
    store = AgentSessionStore()
    session = store.create_events(None)
    events = [event()] * (MAX_EVENTS_PER_SESSION - 1)
    assert store.add_events(session.session_id, events) == MAX_EVENTS_PER_SESSION - 1

    with pytest.raises(HaqwaError) as exc:
        store.add_events(session.session_id, [event(), event()])
    assert exc.value.code == "invalid_request"
    assert str(exc.value) == "event limit reached"
    assert len(store.get(session.session_id).events) == MAX_EVENTS_PER_SESSION - 1
    assert store.add_events(session.session_id, [event()]) == MAX_EVENTS_PER_SESSION


def test_shop_sessions_unchanged_and_share_limit() -> None:
    store = AgentSessionStore(max_sessions=1)
    shop = store.create("stale_state")
    assert shop.kind == "shop"
    assert shop.fault == "stale_state"
    assert shop.shop is not None
    assert shop.events == [] and shop.vocabulary is None

    with pytest.raises(HaqwaError) as exc:
        store.add_events(shop.session_id, [event()])
    assert exc.value.code == "invalid_request"
    with pytest.raises(HaqwaError) as exc:
        store.create_events(None)
    assert exc.value.code == "session_limit"

    store.delete(shop.session_id)
    events = store.create_events(None)
    with pytest.raises(HaqwaError) as exc:
        store.create("stale_state")
    assert exc.value.code == "session_limit"
    assert store.get(events.session_id) is events
