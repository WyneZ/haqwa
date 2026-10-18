"""Owner-confirmed example timelines shared by v1 and v2 rules."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class TimelineEvent(_Strict):
    """An event at an optional offset from the first event in an example."""

    event: str
    data: dict[str, Any] = Field(default_factory=dict)
    at: timedelta | None = None


class ConfirmedExample(_Strict):
    """An owner-confirmed timeline and its expected violation status."""

    timeline: list[TimelineEvent] = Field(min_length=1)
    violation: bool

    @model_validator(mode="after")
    def _offsets_consistent(self) -> ConfirmedExample:
        offsets = [t.at for t in self.timeline]
        if all(o is None for o in offsets):
            return self
        if any(o is None for o in offsets):
            raise ValueError("if one timeline item has `at`, every item must have it")
        if offsets[0] != timedelta(0):
            raise ValueError("the first timeline item must have `at: PT0S`")
        if any(b < a for a, b in zip(offsets, offsets[1:], strict=False)):
            raise ValueError("`at` offsets must not decrease")
        return self
