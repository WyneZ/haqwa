"""Types shared by pattern evaluators."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from ..events import Event


@dataclass(frozen=True)
class Finding:
    """A violation inside one entity's event stream."""

    index: int  # position of the offending event in the stream
    message: str


class Evaluator(Protocol):
    """(rule, one entity's time-sorted events, trace end) -> findings.

    `trace_end` is the last timestamp of the whole checked trace (all entities);
    only time-based patterns use it. Defaults to the entity's last event.
    """

    def __call__(
        self, rule: Any, events: list[Event], trace_end: datetime | None = None
    ) -> list[Finding]: ...
