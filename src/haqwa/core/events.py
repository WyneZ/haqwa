"""C2 Event format: what a system did, in the rule vocabulary (DRAFT, not locked).

Pipeline: raw events (system names) -> EventMap.translate -> Event (rule names).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator

from .errors import INVALID_EVENT_MAP, INVALID_EVENTS, HaqwaError, validation_errors


class Event(BaseModel):
    """One thing that happened in a system.

    `event` is the event name, `ts` a timezone-aware timestamp, and `data` holds
    every other field (entity keys such as `order_id`, amounts, payment_type...).
    Rules find their entity through `data[rule.per]`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    event: str = Field(min_length=1)
    ts: AwareDatetime
    data: dict[str, Any] = Field(default_factory=dict)
    source_id: str | None = None  # id in the original system, for traceability


class EventMap(BaseModel):
    """Maps system event names to rule vocabulary.

    YAML form (rule name -> one or more system names):

        version: 1
        events:
          charged: [PAYMENT_CAPTURED]
          refunded: REFUND_ISSUED
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = 1
    events: dict[str, list[str]]

    @model_validator(mode="before")
    @classmethod
    def _wrap_single_names(cls, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("events"), dict):
            data = dict(data)
            data["events"] = {
                k: [v] if isinstance(v, str) else v for k, v in data["events"].items()
            }
        return data

    @model_validator(mode="after")
    def _no_ambiguous_system_names(self) -> EventMap:
        seen: dict[str, str] = {}
        for rule_name, system_names in self.events.items():
            for name in system_names:
                if name in seen and seen[name] != rule_name:
                    raise ValueError(
                        f"system event {name!r} mapped to both {seen[name]!r} and {rule_name!r}"
                    )
                seen[name] = rule_name
        return self

    @property
    def vocabulary(self) -> set[str]:
        """Rule-side event names this map can produce."""
        return set(self.events)

    def translate(self, events: Iterable[Event]) -> list[Event]:
        """Rename mapped events to rule vocabulary; drop events the map doesn't know."""
        lookup = {sys: rule for rule, names in self.events.items() for sys in names}
        return [
            e.model_copy(update={"event": lookup[e.event]}) for e in events if e.event in lookup
        ]


def sort_events(events: Iterable[Event]) -> list[Event]:
    """Sort by timestamp. Stable: equal timestamps keep their input order."""
    return sorted(events, key=lambda e: e.ts)


def group_by(events: Iterable[Event], key: str) -> dict[Any, list[Event]]:
    """Group events by `data[key]`, keeping order. Events without the key are skipped."""
    groups: dict[Any, list[Event]] = {}
    for e in events:
        if key in e.data:
            groups.setdefault(e.data[key], []).append(e)
    return groups


def parse_events(raw: Any) -> list[Event]:
    """Validate a list of event dicts. Raises HaqwaError `invalid_events`."""
    if not isinstance(raw, list):
        raise HaqwaError(INVALID_EVENTS, "events must be a JSON array")
    try:
        return [Event.model_validate(item) for item in raw]
    except ValidationError as e:
        raise HaqwaError(
            INVALID_EVENTS, str(e.errors()[0]["msg"]), errors=validation_errors(e)
        ) from e


def load_events(path: str | Path) -> list[Event]:
    """Load a JSON array of events. Raises HaqwaError `invalid_events`."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise HaqwaError(INVALID_EVENTS, f"not valid JSON: {e}") from e
    return parse_events(raw)


def parse_event_map(data: Any) -> EventMap:
    """Validate event map data. Raises HaqwaError `invalid_event_map`."""
    try:
        return EventMap.model_validate(data)
    except ValidationError as e:
        raise HaqwaError(
            INVALID_EVENT_MAP,
            f"{e.error_count()} problem(s) in the event map",
            errors=validation_errors(e),
        ) from e


def load_event_map(path: str | Path) -> EventMap:
    """Load an events.map.yaml file. Raises HaqwaError `invalid_event_map`."""
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise HaqwaError(INVALID_EVENT_MAP, f"not valid YAML: {e}") from e
    return parse_event_map(data)


def synthetic_timeline(
    timeline: Iterable[tuple[str, dict[str, Any]] | tuple[str, dict[str, Any], timedelta | None]],
    per: str,
    entity_id: str = "example-1",
    start: datetime | None = None,
) -> list[Event]:
    """Build events from (name, data[, at]) items for one synthetic entity.

    Items without an `at` offset are 1 second apart; with `at`, ts = start + at.
    `data` may override `per` to put an item on a different entity.
    Used by the compiler self-test, canonical examples and question checks.
    """
    t0 = start or datetime(2000, 1, 1, tzinfo=UTC)
    events: list[Event] = []
    for i, item in enumerate(timeline):
        name, data = item[0], item[1]
        at = item[2] if len(item) > 2 else None
        ts = t0 + (at if at is not None else timedelta(seconds=i))
        events.append(Event(event=name, ts=ts, data={per: entity_id, **data}))
    return events
