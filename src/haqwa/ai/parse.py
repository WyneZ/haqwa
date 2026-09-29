"""Turn Gemini's draft of one rule into a C1 rule (`core/spec.py`).

No Gemini call happens here: `clarify` asks Gemini once for the draft and the
questions together (one call saves free-tier quota), then uses `to_rule` to translate
the draft. That keeps this module a pure function that is easy to test.

The draft models are the Gemini "wire format". They use C1 field names, but:
- they are a plain union (`anyOf`), because google-genai rejects `oneOf` + discriminator;
- `within` is an ISO 8601 string ("PT24H"), converted to `timedelta` by the C1 model;
- there is no `id`, `source` or `except` (ids come from the owner/core, exceptions from
  the owner's answers in `clarify`).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from haqwa.core.spec import AtMostOnce, MustPrecede, NeverAfter, Rule, UnsupportedRule, WithinTime

from .vocab import Vocabulary

# ---- Gemini wire format (one model per pattern) ------------------------------------------


class AtMostOnceDraft(BaseModel):
    pattern: Literal["at_most_once"]
    event: str = Field(description="the event that may happen at most once")
    per: str = Field(description="entity key field, e.g. 'order_id'")


class NeverAfterDraft(BaseModel):
    pattern: Literal["never_after"]
    after: str = Field(description="once this event happened ...")
    event: str = Field(description="... this event must never happen")
    per: str = Field(description="entity key field, e.g. 'order_id'")


class MustPrecedeDraft(BaseModel):
    pattern: Literal["must_precede"]
    requires: str = Field(description="this event must happen earlier ...")
    event: str = Field(description="... than this event")
    per: str = Field(description="entity key field, e.g. 'order_id'")


class WithinTimeDraft(BaseModel):
    pattern: Literal["within_time"]
    start: str = Field(description="the event that starts the clock")
    event: str = Field(description="the event that must follow")
    within: str = Field(description="ISO 8601 duration, e.g. 'PT24H'")
    per: str = Field(description="entity key field, e.g. 'order_id'")


class UnsupportedDraft(BaseModel):
    pattern: Literal["unsupported"]
    reason: str = Field(description="why none of the 4 patterns fits")


# Plain union -> JSON Schema `anyOf`. The Literal `pattern` still lets Pydantic pick the model.
DraftRule = (
    AtMostOnceDraft | NeverAfterDraft | MustPrecedeDraft | WithinTimeDraft | UnsupportedDraft
)

C1Rule = AtMostOnce | NeverAfter | MustPrecede | WithinTime
_RULE_ADAPTER: TypeAdapter[C1Rule] = TypeAdapter(Rule)

# Which draft fields hold event names (the rest are `per`, `within`, `reason`).
_EVENT_FIELDS = ("event", "after", "requires", "start")


class ParseError(ValueError):
    """Gemini's draft cannot become a valid C1 rule. `problems` lists every reason."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def draft_problems(draft: DraftRule, vocab: Vocabulary) -> list[str]:
    """Every name in `draft` that is outside `vocab`, plus same-event mistakes."""
    if isinstance(draft, UnsupportedDraft):
        return []
    problems: list[str] = []
    for name in _EVENT_FIELDS:
        value = getattr(draft, name, None)
        if value is not None and (msg := vocab.event_problem(value, f"draft.{name}")):
            problems.append(msg)
    if msg := vocab.field_problem(draft.per, "draft.per"):
        problems.append(msg)
    other = next((getattr(draft, n) for n in _EVENT_FIELDS[1:] if hasattr(draft, n)), None)
    if other == draft.event:
        problems.append(
            f"draft: both events are {draft.event!r}; a rule needs two different events"
        )
    return problems


def to_rule(
    draft: DraftRule, *, rule_id: str, source: str, vocab: Vocabulary
) -> C1Rule | UnsupportedRule:
    """Translate a Gemini draft into a C1 rule, or an `UnsupportedRule`.

    Args:
        draft: The rule part of Gemini's answer.
        rule_id: Stable rule id (`^[a-z0-9][a-z0-9-]*$`), chosen by core/the owner, not Gemini.
        source: The owner's original English rule text.
        vocab: Allowed events and fields.

    Raises:
        ParseError: a name is outside the vocabulary, or the C1 model rejects the draft
            (bad id, bad ISO 8601 duration, ...).
    """
    if isinstance(draft, UnsupportedDraft):
        return UnsupportedRule(source=source, reason=draft.reason)

    problems = draft_problems(draft, vocab)
    if problems:
        raise ParseError(problems)

    data = draft.model_dump() | {"id": rule_id, "source": source}
    try:
        return _RULE_ADAPTER.validate_python(data)
    except ValidationError as e:
        raise ParseError([f"C1: {err['loc']}: {err['msg']}" for err in e.errors()]) from e
