"""Trace vocabulary, closed fields and size limits."""

from datetime import UTC, datetime, timedelta

import pytest

from haqwa.core.errors import HaqwaError
from haqwa.core.events import Event
from haqwa.core.trace import MAX_EVENTS, summarize_trace


def event(name, offset, data):
    return Event(
        event=name, ts=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=offset), data=data
    )


def test_summary_sorts_and_detects_closed_fields_and_entities():
    events = [
        event("z", 2, {"employee_id": "E1", "status": "done", "mixed": "a"}),
        event("a", 0, {"employee_id": "E2", "status": "open", "mixed": 1}),
        event("a", 1, {"employee_id": "E1", "status": "done", "rare_id": "R"}),
    ]
    summary = summarize_trace(events)
    assert summary.event_count == 3
    assert summary.event_counts == {"a": 2, "z": 1}
    assert summary.first_ts == events[1].ts
    assert summary.last_ts == events[0].ts
    assert summary.fields == ["employee_id", "mixed", "rare_id", "status"]
    assert summary.field_values == {"status": ["done", "open"]}
    assert summary.entity_candidates == ["employee_id"]
    assert summary.vocabulary.model_dump() == {
        "events": ["a", "z"],
        "fields": summary.fields,
        "field_values": summary.field_values,
    }


def test_summary_empty_open_values_and_limit():
    empty = summarize_trace([])
    assert empty.event_count == 0
    assert empty.first_ts is None and empty.last_ts is None
    events = [event("x", i, {"kind": str(i)}) for i in range(9)]
    assert summarize_trace(events).field_values == {}
    with pytest.raises(HaqwaError, match="exceeds") as exc:
        summarize_trace(event("x", 0, {}) for _ in range(MAX_EVENTS + 1))
    assert exc.value.code == "invalid_events"


def test_declared_events_extend_only_vocabulary():
    summary = summarize_trace(
        [event("leave_requested", 0, {"leave_id": "L1"})],
        extra_events=["payroll_run", "leave_requested", "payroll_run"],
    )
    assert summary.vocabulary.events == ["leave_requested", "payroll_run"]
    assert summary.event_counts == {"leave_requested": 1}
