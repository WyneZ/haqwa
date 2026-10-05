"""C1 Spec model: the human-confirmed meaning of policy rules (C1 locked 2026-09-25)."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .errors import INVALID_SPEC, HaqwaError, validation_errors


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
    # PROPOSED C1 change (needs Track A agreement): offset from the FIRST event of the
    # timeline, ISO 8601 duration in YAML (e.g. PT65H). None -> events are 1 s apart.
    at: timedelta | None = None


class ConfirmedExample(_Strict):
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

    @model_validator(mode="after")
    def _positive_window(self) -> WithinTime:
        if self.within <= timedelta(0):
            raise ValueError("`within` must be a positive duration")
        return self


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


def parse_spec(data: Any) -> Spec:
    """Validate spec data (e.g. JSON from the web API). Raises HaqwaError `invalid_spec`."""
    try:
        return Spec.model_validate(data)
    except ValidationError as e:
        raise HaqwaError(
            INVALID_SPEC, f"{e.error_count()} problem(s) in the spec", errors=validation_errors(e)
        ) from e


def load_spec(path: str | Path) -> Spec:
    """Load and validate a rules.spec.yaml file. Raises HaqwaError `invalid_spec`."""
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise HaqwaError(INVALID_SPEC, f"not valid YAML: {e}") from e
    return parse_spec(data)


# ---------- Deterministic dump (stable git diffs for every Seal) ----------
_PATTERN_FIELDS: dict[str, tuple[str, ...]] = {
    "at_most_once": ("event",),
    "never_after": ("event", "after"),
    "must_precede": ("event", "requires"),
    "within_time": ("start", "event", "within"),
}


def iso_duration(d: timedelta) -> str:
    """ISO 8601 duration in hours/minutes/seconds, as policies say it: PT48H, PT1H30M, PT0S."""
    total_us = ((d.days * 86400 + d.seconds) * 1_000_000) + d.microseconds
    h, rest = divmod(total_us, 3600 * 1_000_000)
    m, rest = divmod(rest, 60 * 1_000_000)
    sec, us = divmod(rest, 1_000_000)
    seconds = f"{sec}.{us:06d}".rstrip("0") if us else str(sec)
    out = "PT" + (f"{h}H" if h else "") + (f"{m}M" if m else "")
    if sec or us:
        out += f"{seconds}S"
    return out if out != "PT" else "PT0S"


class _Flow(dict):  # type: ignore[type-arg]
    """Mapping written on one line: {event: charged}."""


class _FlowList(list):  # type: ignore[type-arg]
    """Sequence written on one line: [{event: a}, {event: b}]."""


class _SpecDumper(yaml.SafeDumper):
    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        # Indent list items under their key ("rules:\n  - id: ...").
        super().increase_indent(flow, False)


_SpecDumper.add_representer(
    _Flow, lambda d, v: d.represent_mapping("tag:yaml.org,2002:map", v, flow_style=True)
)
_SpecDumper.add_representer(
    _FlowList, lambda d, v: d.represent_sequence("tag:yaml.org,2002:seq", v, flow_style=True)
)


def _timeline_item(t: TimelineEvent) -> _Flow:
    item = _Flow(event=t.event)
    if t.data:
        item["data"] = _Flow(t.data)
    if t.at is not None:
        item["at"] = iso_duration(t.at)
    return item


def _rule_dict(rule: Rule) -> dict[str, Any]:
    d: dict[str, Any] = {"id": rule.id, "source": rule.source, "pattern": rule.pattern}
    for name in _PATTERN_FIELDS[rule.pattern]:
        value = getattr(rule, name)
        d[name] = iso_duration(value) if isinstance(value, timedelta) else value
    d["per"] = rule.per
    if rule.exceptions:
        d["except"] = [
            {"reset_after": x.reset_after}
            if isinstance(x, ResetAfter)
            else {"allow_if": _Flow(x.allow_if.model_dump())}
            for x in rule.exceptions
        ]
    if rule.confirmed_examples:
        d["confirmed_examples"] = [
            {
                "timeline": _FlowList(_timeline_item(t) for t in ex.timeline),
                "violation": ex.violation,
            }
            for ex in rule.confirmed_examples
        ]
    return d


def dump_spec(spec: Spec) -> str:
    """Deterministic YAML: fixed key order, the owner's rule order, no empty fields.

    `load_spec` -> `dump_spec` -> `load_spec` gives an equal spec, and dumping twice gives
    byte-identical text, so each Seal produces a clean git diff. Rule ids are never changed.
    """
    data = {"version": spec.version, "rules": [_rule_dict(r) for r in spec.rules]}
    return yaml.dump(data, Dumper=_SpecDumper, sort_keys=False, allow_unicode=True, width=10_000)


def save_spec(spec: Spec, path: str | Path) -> None:
    """Write `dump_spec(spec)` to a file (UTF-8)."""
    Path(path).write_text(dump_spec(spec), encoding="utf-8")


# ---------- Rule ids (agreed 2026-09-29: suggest once, owner may edit, then frozen) ----------
_STOPWORDS = frozenset(
    "a an the and or of for to in on at by with from is are be been being must should shall "
    "can may will would it its this that these those same any every each per than then "
    "customer customers user users".split()
)
_NEGATIONS = {"not": "no", "never": "no", "no": "no", "cannot": "no"}
_MAX_WORDS = 4


def suggest_rule_id(text: str, existing_ids: Iterable[str] = ()) -> str:
    """Suggest a C1-valid id from rule text. Deterministic; call only for rules without an id.

    "A customer must not be charged twice for the same order." -> "no-charged-twice-order"
    If the slug is taken, "-2", "-3", ... is added.
    """
    words = re.findall(r"[a-z0-9]+", text.lower())
    kept: list[str] = []
    for w in words:
        w = _NEGATIONS.get(w, w)
        if w in _STOPWORDS or (kept and kept[-1] == w):
            continue
        kept.append(w)
    base = "-".join(kept[:_MAX_WORDS]) or "rule"
    taken = set(existing_ids)
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"
