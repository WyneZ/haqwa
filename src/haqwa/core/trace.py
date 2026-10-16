"""Deterministic summary of a C2 event trace."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .errors import INVALID_EVENTS, HaqwaError
from .events import Event

MAX_EVENTS = 10_000
MAX_CLOSED_VALUES = 8


class TraceVocabulary(BaseModel):
    model_config = ConfigDict(frozen=True)

    events: list[str]
    fields: list[str]
    field_values: dict[str, list[str]]
    numeric_fields: list[str] = Field(default_factory=list, exclude_if=lambda value: not value)


class TraceSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_count: int
    event_counts: dict[str, int]
    first_ts: datetime | None
    last_ts: datetime | None
    fields: list[str]
    field_values: dict[str, list[str]]
    entity_candidates: list[str]
    vocabulary: TraceVocabulary


def summarize_trace(events: Iterable[Event], *, extra_events: Iterable[str] = ()) -> TraceSummary:
    """Summarize observed events and add declared names to the vocabulary."""
    counts: Counter[str] = Counter()
    presence: Counter[str] = Counter()
    values: dict[str, set[str]] = {}
    open_fields: set[str] = set()
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    count = 0
    for event in events:
        count += 1
        if count > MAX_EVENTS:
            raise HaqwaError(INVALID_EVENTS, f"trace exceeds {MAX_EVENTS} events")
        counts[event.event] += 1
        first_ts = event.ts if first_ts is None else min(first_ts, event.ts)
        last_ts = event.ts if last_ts is None else max(last_ts, event.ts)
        for field, value in event.data.items():
            presence[field] += 1
            if field.endswith("_id") or not isinstance(value, str):
                open_fields.add(field)
                continue
            field_values = values.setdefault(field, set())
            field_values.add(value)
            if len(field_values) > MAX_CLOSED_VALUES:
                open_fields.add(field)
    fields = sorted(presence)
    closed = {field: sorted(values[field]) for field in fields if field not in open_fields}
    event_counts = dict(sorted(counts.items()))
    return TraceSummary(
        event_count=count,
        event_counts=event_counts,
        first_ts=first_ts,
        last_ts=last_ts,
        fields=fields,
        field_values=closed,
        entity_candidates=[
            field for field in fields if field.endswith("_id") and presence[field] * 10 >= count * 9
        ],
        vocabulary=TraceVocabulary(
            events=sorted(set(event_counts).union(extra_events)), fields=fields, field_values=closed
        ),
    )
