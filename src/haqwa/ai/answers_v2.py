"""Pure owner-answer handling for v2; core patch application is injected."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from haqwa.core.canonical import CanonicalExample
from haqwa.core.rules_v2 import RuleV2, SelectNode, validate_rule_v2
from haqwa.core.spec import ConfirmedExample, TimelineEvent

from ._decision_wire import RESETTABLE
from .clarify_v2 import (
    AddReset,
    ClarifyV2Outcome,
    Patch,
    _condition,
    _condition_key,
    _patch_key,
)
from .core_v2_ports import ApplyPatch
from .parse import ParseError
from .vocab import Vocabulary


class QuestionV2(BaseModel):
    """One owner card; Yes means the displayed timeline is allowed."""

    id: str = Field(min_length=1)
    kind: Literal["decision", "confirmation"]
    text: str = Field(min_length=1)
    why: str | None = None
    timeline: list[TimelineEvent] = Field(min_length=1)
    patch: Patch | None = None
    expected_violation: bool | None = None

    @model_validator(mode="after")
    def consistent_kind(self) -> QuestionV2:
        """Reject question bodies that mix decisions and fixed confirmations."""
        if self.kind == "decision":
            if self.patch is None or self.expected_violation is not None:
                raise ValueError("a decision requires a patch and no expected_violation")
        elif self.expected_violation is None or self.patch is not None or self.why is not None:
            raise ValueError("a confirmation requires expected_violation and no patch or why")
        return self


class AnswerV2(BaseModel):
    """The owner's allowed/not-allowed answer to a v2 question."""

    question: QuestionV2
    allowed: bool


class AnswersV2Outcome(BaseModel):
    """Updated rule plus answer evidence held separately until Track B B2."""

    rule: RuleV2
    confirmed_examples: list[ConfirmedExample]
    mismatches: list[str]


def _already_applied(rule: RuleV2, patch: Patch) -> bool:
    nodes = {node.id: node for node in rule.nodes}
    if isinstance(patch, AddReset):
        target = nodes.get(patch.node_id)
        return isinstance(target, RESETTABLE) and patch.event in target.since
    key = _condition_key(_condition(patch))
    return all(
        isinstance(target := nodes.get(select_id), SelectNode)
        and any(_condition_key(condition) == key for condition in target.exclude)
        for select_id in patch.select_ids
    )


def _validated(rule: RuleV2, vocab: Vocabulary) -> RuleV2:
    # Revalidate nested mutable lists, including values returned by a core port.
    try:
        result = RuleV2.model_validate(rule.model_dump())
    except ValidationError as exc:
        raise ParseError([error["msg"] for error in exc.errors()]) from exc
    if problems := validate_rule_v2(result, vocab.events, vocab.fields, vocab.numeric_fields):
        raise ParseError(problems)
    return result


def apply_answers_v2(
    rule: RuleV2,
    answers: list[AnswerV2],
    *,
    apply_patch: ApplyPatch,
    vocab: Vocabulary,
) -> AnswersV2Outcome:
    """Record owner evidence and apply each new Yes patch through the core port.

    The vocabulary is required for deterministic validation. Confirmation mismatches
    are not recorded. This function neither calls Gemini nor evaluates timelines.
    Provisional NotImplementedError propagates for the HTTP adapter to map to 501.
    """
    updated = _validated(rule, vocab)
    examples: list[ConfirmedExample] = []
    mismatches: list[str] = []
    applied: set[tuple] = set()
    for answer in answers:
        question = answer.question
        violation = not answer.allowed
        if question.kind == "confirmation" and violation != question.expected_violation:
            expected = "not allowed" if question.expected_violation else "allowed"
            mismatches.append(f"{question.id}: owner answered the opposite of '{expected}'")
            continue
        if question.kind == "decision" and answer.allowed:
            assert question.patch is not None  # QuestionV2's kind validator guarantees this.
            key = _patch_key(question.patch)
            if key not in applied and not _already_applied(updated, question.patch):
                try:
                    updated = apply_patch(updated, question.patch.model_copy(deep=True))
                except ValidationError as exc:
                    raise ParseError([error["msg"] for error in exc.errors()]) from exc
                applied.add(key)
        try:
            example = ConfirmedExample(timeline=question.timeline, violation=violation)
        except ValidationError as exc:
            raise ParseError([error["msg"] for error in exc.errors()]) from exc
        if example not in examples:
            examples.append(example)
    return AnswersV2Outcome(
        rule=_validated(updated, vocab),
        confirmed_examples=examples,  # TODO(B2): move confirmed examples into RuleV2 here.
        mismatches=mismatches,
    )


def build_questions(
    outcome: ClarifyV2Outcome, confirmations: list[CanonicalExample]
) -> list[QuestionV2]:
    """Build confirmation cards then decisions, preserving existing decision ids."""
    questions = [
        QuestionV2(
            id=f"c{index}",
            kind="confirmation",
            text="Is this allowed?",
            timeline=list(example.timeline),
            expected_violation=example.violation,
        )
        for index, example in enumerate(confirmations, 1)
    ]
    questions.extend(
        QuestionV2(
            id=decision.id,
            kind="decision",
            text=decision.question,
            why=decision.why,
            timeline=list(decision.example.timeline),
            patch=decision.patch,
        )
        for decision in outcome.decisions
        if decision.example is not None
    )
    return questions
