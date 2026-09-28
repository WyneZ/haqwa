import pytest
from pydantic import ValidationError

from haqwa.core.events import (
    Event,
    EventMap,
    group_by,
    load_event_map,
    load_events,
    sort_events,
    synthetic_timeline,
)

from .helpers import ev


def test_naive_timestamp_rejected():
    with pytest.raises(ValidationError):
        Event(event="charged", ts="2026-01-01T10:00:00")


def test_example_files_load(shop_dir):
    events = load_events(shop_dir / "events.json")
    emap = load_event_map(shop_dir / "events.map.yaml")
    assert len(events) == 8
    assert emap.events["charged"] == ["PAYMENT_CAPTURED"]


def test_translate_renames_and_drops_unknown():
    emap = EventMap.model_validate({"events": {"charged": ["PAY_OK", "PAY_CAPTURED"]}})
    out = emap.translate([ev("PAY_OK", 0), ev("EMAIL_SENT", 1), ev("PAY_CAPTURED", 2)])
    assert [e.event for e in out] == ["charged", "charged"]


def test_ambiguous_map_rejected():
    with pytest.raises(ValidationError, match="mapped to both"):
        EventMap.model_validate({"events": {"charged": "X", "refunded": "X"}})


def test_sort_is_stable_for_equal_timestamps():
    a, b, c = ev("a", 5), ev("b", 5), ev("c", 1)
    assert [e.event for e in sort_events([a, b, c])] == ["c", "a", "b"]


def test_group_by_skips_events_without_key():
    keyless = Event(event="x", ts=ev("x", 0).ts, data={})
    groups = group_by([ev("a", 0, "o1"), keyless, ev("b", 1, "o2")], "order_id")
    assert set(groups) == {"o1", "o2"}


def test_synthetic_timeline_increasing_single_entity():
    out = synthetic_timeline([("charged", {}), ("refunded", {"x": 1})], per="order_id")
    assert out[0].ts < out[1].ts
    assert {e.data["order_id"] for e in out} == {"example-1"}
    assert out[1].data["x"] == 1
