"""C1 Spec model: the human-confirmed meaning of policy rules (DRAFT, not locked)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    # extra="forbid": typos like `excpet:` fail loudly instead of being ignored.
    # frozen=True: a sealed spec must not be mutated at runtime.
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


# ---------- Condition (D2: structured, never eval'd) ----------
class Condition(_Strict):
    field: str
    op: Literal["eq", "ne", "in"]
    value: str | int | float | bool | list[str | int | float | bool]

    @model_validator(mode="after")
    def _value_matches_op(self) -> Condition:
        if self.op == "in" and not isinstance(self.value, list):
            raise ValueError("op 'in' needs a list value")
        if self.op != "in" and isinstance(self.value, list):
            raise ValueError(f"op {self.op!r} needs a single value, not a list")
        return self


# ---------- Exceptions ----------
class ResetAfter(_Strict):
    reset_after: str  # event name that resets the rule for this entity


class AllowIf(_Strict):
    allow_if: Condition  # events matching this are ignored by the rule


RuleException = ResetAfter | AllowIf


# ---------- Confirmed examples (D3: same shape as C2 events) ----------
class TimelineEvent(_Strict):
    event: str
    data: dict[str, Any] = Field(default_factory=dict)


class ConfirmedExample(_Strict):
    timeline: list[TimelineEvent] = Field(min_length=1)
    violation: bool


# ---------- Rules (D1: discriminated union) ----------
class _RuleBase(_Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    source: str  # original English rule
    per: str  # entity key, e.g. "order_id"
    exceptions: list[RuleException] = Field(default_factory=list, alias="except")
    confirmed_examples: list[ConfirmedExample] = Field(default_factory=list)


class AtMostOnce(_RuleBase):
    pattern: Literal["at_most_once"]
    event: str


class NeverAfter(_RuleBase):
    pattern: Literal["never_after"]
    event: str  # forbidden event
    after: str  # once this happened, `event` is forbidden


class MustPrecede(_RuleBase):
    pattern: Literal["must_precede"]
    event: str  # gated event
    requires: str  # must have happened earlier for the same entity


class WithinTime(_RuleBase):
    pattern: Literal["within_time"]
    start: str
    event: str  # must happen within `within` after `start`
    within: timedelta  # YAML: seconds (86400) or ISO 8601 ("PT24H")


Rule = Annotated[AtMostOnce | NeverAfter | MustPrecede | WithinTime, Field(discriminator="pattern")]


# ---------- Spec ----------
class Spec(_Strict):
    version: Literal[1] = 1
    rules: list[Rule]

    @model_validator(mode="after")
    def _unique_ids(self) -> Spec:
        ids = [r.id for r in self.rules]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate rule ids: {sorted(dupes)}")
        return self


# ---------- D4: not part of a sealed spec ----------
class UnsupportedRule(_Strict):
    source: str
    reason: str


def load_spec(path: str | Path) -> Spec:
    """Load and validate a rules.spec.yaml file."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return Spec.model_validate(data)
