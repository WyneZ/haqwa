"""Clarification loop: rule text -> C1 rule + Yes/No questions -> owner answers -> updated rule.

Two public functions (C3 endpoints 1 and 2):

- `clarify(rule_text, ...)`: ONE Gemini call returns the draft rule and the decision
  questions together (prompt v2.1 from spikes/clarify). Code then drops noisy
  questions; Gemini is never trusted to stay inside the vocabulary.
- `apply_answers(rule, answers)`: no Gemini. Each answer becomes a confirmed example;
  a "Yes, allowed" to a decision question also adds that question's exception.

Question kinds:
- decision:     a business choice the owner makes (from Gemini). Yes adds `if_yes`.
- confirmation: checks the owner reads the pattern the way core does (from core, see
                `confirmation_questions`). An answer that disagrees is a mismatch.

Every question asks "is this allowed?": allowed=True -> violation False.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from haqwa.core.canonical import canonical_examples
from haqwa.core.compiler import distinguishes
from haqwa.core.spec import (
    AllowIf,
    Condition,
    ConfirmedExample,
    ResetAfter,
    RuleException,
    TimelineEvent,
    UnsupportedRule,
    suggest_rule_id,
)

from .client import GeminiClient
from .parse import C1Rule, DraftRule, UnsupportedDraft, to_rule
from .vocab import Vocabulary

# =========================================================================================
# 1. Gemini wire format (same schema as spike v2.1, so Gemini behaves as measured there)
# =========================================================================================


class WireField(BaseModel):
    key: str = Field(description="field name, e.g. 'payment_type'")
    value: str = Field(description="field value as a string, e.g. 'installment'")


class WireEvent(BaseModel):
    event: str = Field(description="one of the event vocabulary names, e.g. 'charged'")
    data: list[WireField] = Field(
        default_factory=list,
        description="optional fields on this event as key/value pairs; empty list if none",
    )


class WireExample(BaseModel):
    events: list[WireEvent] = Field(description="ordered event occurrences")
    question: str = Field(
        description="Yes/No question to ask the policy owner about this exact timeline"
    )


class WireCondition(BaseModel):
    field: str
    op: Literal["eq", "ne", "in"]
    value: str = Field(description="comma-separated list of values if op is 'in'")


class WireSpecChange(BaseModel):
    kind: Literal["reset_after", "allow_if", "none"]
    event: str | None = Field(default=None, description="required if kind == 'reset_after'")
    condition: WireCondition | None = Field(
        default=None, description="required if kind == 'allow_if'"
    )


class WireAmbiguity(BaseModel):
    id: str = Field(description="short slug, e.g. 'refund-resets-charge'")
    description: str = Field(description="plain English, for a non-technical business owner")
    examples: list[WireExample] = Field(description="1-2 concrete example timelines")
    spec_change_if_yes: WireSpecChange = Field(
        description="exact deterministic spec change to apply if the owner answers Yes"
    )


# What Gemini returns. Field names match spike v2.1 (`parse`, not `draft`) on purpose.
# No docstrings on wire models: Pydantic would send them to Gemini as schema descriptions.
class WireClarify(BaseModel):
    rule_id: str
    parse: DraftRule
    ambiguities: list[WireAmbiguity]


# =========================================================================================
# 2. Public models (C3 shapes)
# =========================================================================================


class Question(BaseModel):
    """One Yes/No card for the owner: "Is this timeline allowed?"."""

    id: str  # "d1", "d2" for decisions; "c1", "c2" for confirmations
    kind: Literal["decision", "confirmation"]
    text: str
    timeline: list[TimelineEvent] = Field(min_length=1)
    if_yes: ResetAfter | AllowIf | None = None  # decision only
    expected_violation: bool | None = None  # confirmation only


class DroppedQuestion(BaseModel):
    """A Gemini question removed by code, kept for evidence and debugging."""

    gemini_id: str
    reasons: list[str]


class ClarifyOutcome(BaseModel):
    """Result of `clarify` for one rule text."""

    source: str
    status: Literal["supported", "unsupported"]
    rule: C1Rule | None = None
    reason: str | None = None  # why unsupported
    questions: list[Question] = Field(default_factory=list)
    dropped: list[DroppedQuestion] = Field(default_factory=list)
    cached: bool = False


class Answer(BaseModel):
    question: Question
    allowed: bool


class AnswersOutcome(BaseModel):
    """Updated rule, plus confirmation answers that contradict the pattern."""

    rule: C1Rule
    mismatches: list[str] = Field(default_factory=list)


# =========================================================================================
# 3. Prompt (text from spike v2.1; the vocabulary is now a parameter)
# =========================================================================================

_CHECKLIST = """Checklist of decisions to consider (use only the ones that apply to the chosen pattern):
- at_most_once: which event resets the count (e.g. a refund or cancellation)?
- never_after: which later event lifts the ban (e.g. the entity is re-opened or re-created)?
- must_precede: can a different earlier event satisfy the requirement?
- within_time: which event removes the obligation (e.g. a cancellation)?
  If the start event happens again, does the clock restart?
- any pattern: an exemption based on a field value, ONLY if that value is in
  the allowed values list below and a real business would plausibly use it."""  # noqa: E501 (prompt text kept identical to spike v2.1)


def build_prompt(rule_id: str, rule_text: str, vocab: Vocabulary) -> str:
    """The v2.1 clarify prompt for one rule."""
    return f"""You are helping a non-technical business/policy owner turn one English
policy rule into a precise, testable specification.

Supported rule patterns (exactly these 4, no others exist), with their fields:
- at_most_once(event, per): event happens at most once per entity
- never_after(after, event, per): once `after` happened, `event` must never happen
- must_precede(requires, event, per): `event` only if `requires` happened earlier
- within_time(start, event, within, per): after `start`, `event` must happen
  within the ISO 8601 duration `within` (e.g. PT24H)
If none fits, use pattern "unsupported" with a reason. Do not force a pattern.

Supported exceptions (exactly these 2):
- reset_after: <event>  (an event resets what the rule has seen for the entity)
- allow_if: {{field, op, value}}  (a structured condition, op is eq/ne/in, that
  makes a matching event invisible to the rule; never code or a string expression)

Event vocabulary (use ONLY these event names, never invent new ones):
{", ".join(vocab.events)}

Available fields on events: {", ".join(vocab.fields)}
Allowed values (use ONLY these values for these fields, never invent others):
{vocab.values_text()}

Rule ({rule_id}): "{rule_text}"

Step 1 - Parse: choose the pattern and fill its fields from the vocabulary.

Step 2 - Find DECISION questions: business decisions the owner must make,
where the Yes/No answer changes whether some real timeline is a violation.
Give 2-5 of them if the rule has that many; do not pad with weak questions.
Do NOT ask confirmation questions; they are generated separately:
- the core case (e.g. the forbidden sequence itself is a violation),
- the order of events (e.g. the events in reverse order),
- whether the rule applies per entity (e.g. two different order ids),
- whether a time window means calendar hours (it always does).
Asking fewer, real questions is better than inventing exemptions.

{_CHECKLIST}

For each question give 1-2 concrete example timelines (each event is
{{event, data}}, where data is a list of {{key, value}} pairs, using only the
event vocabulary and fields above) and phrase it as a Yes/No question about
whether that timeline is allowed. Also give the exact spec_change_if_yes:
kind "reset_after" with an event, kind "allow_if" with a structured condition,
or kind "none" if it cannot be captured that way."""


# =========================================================================================
# 4. clarify(): one Gemini call -> rule + questions
# =========================================================================================


def clarify(
    rule_text: str,
    *,
    vocab: Vocabulary,
    client: GeminiClient,
    rule_id: str | None = None,
    existing_ids: Iterable[str] = (),
) -> ClarifyOutcome:
    """Ask Gemini once for the rule's pattern and the owner's decision questions.

    Questions come back confirmations first (from core), then decisions (from Gemini).

    Args:
        rule_text: The owner's rule in English.
        vocab: Allowed events, fields and values.
        client: Gemini client (pass a fake in tests).
        rule_id: Keep an id the owner already has or edited. When omitted, core suggests
            one from the text (`suggest_rule_id`); the caller should then freeze it.
        existing_ids: Ids already used in the spec, so a suggested id is unique.

    Raises:
        ParseError: Gemini's draft uses names outside `vocab` or is not a valid C1 rule.
        GeminiError: quota, availability or bad output (see `client.py`).
    """
    if rule_id is None:
        rule_id = suggest_rule_id(rule_text, existing_ids)
    result = client.generate(build_prompt(rule_id, rule_text, vocab), WireClarify)
    wire = result.value

    if isinstance(wire.parse, UnsupportedDraft):
        return ClarifyOutcome(
            source=rule_text, status="unsupported", reason=wire.parse.reason, cached=result.cached
        )

    rule = to_rule(wire.parse, rule_id=rule_id, source=rule_text, vocab=vocab)
    assert not isinstance(rule, UnsupportedRule)  # handled above

    decisions, dropped = decision_questions(wire.ambiguities, per=rule.per, vocab=vocab, rule=rule)
    return ClarifyOutcome(
        source=rule_text,
        status="supported",
        rule=rule,
        questions=confirmation_questions(rule) + decisions,
        dropped=dropped,
        cached=result.cached,
    )


UNTESTABLE = "Yes and No give the same verdict on this timeline, so the answer cannot be tested"


def decision_questions(
    ambiguities: list[WireAmbiguity],
    *,
    per: str,
    vocab: Vocabulary,
    rule: C1Rule | None = None,
) -> tuple[list[Question], list[DroppedQuestion]]:
    """Turn Gemini's ambiguities into decision cards; drop the ones code cannot trust.

    Only the FIRST example timeline is used: C3 has one timeline per question, and
    asking the owner the same thing twice makes the UI heavier (wireframe decision).

    With `rule`, a question is also dropped when core says Yes and No give the same
    verdict on its timeline (`distinguishes`): the answer could not be tested, and a
    "No" would fail the compile self-test at seal (e.g. a within_time timeline with no
    time in it, so the deadline never passes).
    """
    kept: list[Question] = []
    dropped: list[DroppedQuestion] = []
    for amb in ambiguities:
        reasons = _ambiguity_problems(amb, vocab)
        if_yes = None
        if not reasons:
            if_yes, reason = _to_exception(amb.spec_change_if_yes)
            if reason:
                reasons.append(reason)
        if reasons:
            dropped.append(DroppedQuestion(gemini_id=amb.id, reasons=reasons))
            continue
        example = amb.examples[0]
        timeline = [_to_timeline_event(e, per) for e in example.events]
        assert if_yes is not None  # set whenever there are no reasons
        if rule is not None and not distinguishes(rule, if_yes, timeline):
            dropped.append(DroppedQuestion(gemini_id=amb.id, reasons=[UNTESTABLE]))
            continue
        kept.append(
            Question(
                id=f"d{len(kept) + 1}",
                kind="decision",
                text=example.question,
                timeline=timeline,
                if_yes=if_yes,
            )
        )
    return kept, dropped


def _ambiguity_problems(amb: WireAmbiguity, vocab: Vocabulary) -> list[str]:
    """Unknown events, fields or values anywhere in one Gemini question (spike v2.1 rule C)."""
    if not amb.examples or not amb.examples[0].events:
        return ["no example timeline"]
    problems: list[str] = []
    for ex in amb.examples:
        for occ in ex.events:
            if msg := vocab.event_problem(occ.event, "example"):
                problems.append(msg)
            for f in occ.data:
                msg = vocab.field_problem(f.key, "example") or vocab.value_problem(
                    f.key, f.value, "example"
                )
                if msg:
                    problems.append(msg)
    change = amb.spec_change_if_yes
    if change.kind == "reset_after" and change.event is not None:
        if msg := vocab.event_problem(change.event, "reset_after"):
            problems.append(msg)
    if change.kind == "allow_if" and change.condition is not None:
        cond = change.condition
        msg = vocab.field_problem(cond.field, "allow_if") or vocab.value_problem(
            cond.field, cond.value, "allow_if"
        )
        if msg:
            problems.append(msg)
    return problems


def _to_exception(change: WireSpecChange) -> tuple[RuleException | None, str | None]:
    """Gemini's spec change -> a C1 exception, or a reason to drop the question.

    kind "none" is dropped: a Yes could not change the spec, so the confirmed example
    would contradict the checker and the core self-test would always fail at seal.
    """
    if change.kind == "none":
        return None, "a Yes answer cannot change the spec (kind 'none')"
    if change.kind == "reset_after":
        if not change.event:
            return None, "reset_after without an event"
        return ResetAfter(reset_after=change.event), None
    if change.condition is None:
        return None, "allow_if without a condition"
    cond = change.condition
    value: str | list[str | int | float | bool] = cond.value
    if cond.op == "in":
        value = [v.strip() for v in cond.value.split(",") if v.strip()]
    try:
        return AllowIf(allow_if=Condition(field=cond.field, op=cond.op, value=value)), None
    except ValidationError as e:
        return None, f"invalid allow_if condition: {e.errors()[0]['msg']}"


def _to_timeline_event(occ: WireEvent, per: str) -> TimelineEvent:
    # The entity key (e.g. order_id "123") is dropped: C1 examples describe ONE entity,
    # and core's self-test adds a synthetic id itself (contracts.md, C1 confirmed examples).
    data = {f.key: f.value for f in occ.data if f.key != per}
    return TimelineEvent(event=occ.event, data=data)


# =========================================================================================
# 5. Confirmation questions (from core, no Gemini)
# =========================================================================================


def confirmation_questions(rule: C1Rule) -> list[Question]:
    """Confirmation cards from core's canonical examples (`core/canonical.py`).

    They check that the owner reads the pattern the way core does: the core case, the
    reversed order, a different entity, and for `within_time` the deadline and calendar
    hours. Timelines keep core's `data[per]` (a different entity) and `at` offsets.
    """
    return [
        Question(
            id=f"c{i}",
            kind="confirmation",
            text=f"{example.label}. Is this allowed?",
            timeline=list(example.timeline),
            expected_violation=example.violation,
        )
        for i, example in enumerate(canonical_examples(rule), 1)
    ]


# =========================================================================================
# 6. apply_answers(): owner's Yes/No -> updated rule (deterministic, no Gemini)
# =========================================================================================


def apply_answers(rule: C1Rule, answers: list[Answer]) -> AnswersOutcome:
    """Apply the owner's answers to one rule.

    - Every answer becomes a confirmed example (violation = not allowed).
    - A decision answered "allowed" also adds its `if_yes` exception (no duplicates).
    - A confirmation answer that disagrees with core's expectation is a mismatch: it is
      NOT added to the rule; the UI asks the owner to rewrite the rule instead (C3).

    Contradictions between decision answers are caught later by core's self-test at seal.
    """
    exceptions = list(rule.exceptions)
    examples = list(rule.confirmed_examples)
    mismatches: list[str] = []

    for answer in answers:
        q = answer.question
        violation = not answer.allowed
        if q.kind == "confirmation" and q.expected_violation is not None:
            if violation != q.expected_violation:
                expected = "not allowed" if q.expected_violation else "allowed"
                mismatches.append(f"{q.id}: owner answered the opposite of '{expected}'")
                continue
        if q.kind == "decision" and answer.allowed and q.if_yes and q.if_yes not in exceptions:
            exceptions.append(q.if_yes)
        example = ConfirmedExample(timeline=q.timeline, violation=violation)
        if example not in examples:
            examples.append(example)

    updated = rule.model_copy(update={"exceptions": exceptions, "confirmed_examples": examples})
    return AnswersOutcome(
        rule=type(rule).model_validate(updated.model_dump()), mismatches=mismatches
    )
