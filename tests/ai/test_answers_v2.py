"""Owner answers are pure transformations through an injected core patch port."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from haqwa.ai.answers_v2 import AnswerV2, QuestionV2, apply_answers_v2, build_questions
from haqwa.ai.clarify_v2 import AddExclude, AddReset, ClarifyV2Outcome, Decision
from haqwa.ai.parse import ParseError
from haqwa.ai.render_v2 import render_rule
from haqwa.core.canonical import CanonicalExample
from haqwa.core.rules_v2 import ConditionV2

from .test_clarify_v2 import SHOP, exclude, reset, rule


def decision(**changes: Any) -> QuestionV2:
    """Build one valid decision question."""
    return QuestionV2.model_validate(
        {
            "id": "d1",
            "kind": "decision",
            "text": "Is a charge after refund allowed?",
            "why": "The owner decides whether a refund resets the count.",
            "timeline": [{"event": "charged"}, {"event": "refunded"}, {"event": "charged"}],
            "patch": reset(),
            **changes,
        }
    )


def confirmation(**changes: Any) -> QuestionV2:
    """Build one valid confirmation question."""
    return QuestionV2.model_validate(
        {
            "id": "c1",
            "kind": "confirmation",
            "text": "Is this allowed?",
            "timeline": [{"event": "charged"}, {"event": "charged"}],
            "expected_violation": True,
            **changes,
        }
    )


def test_yes_applies_patch_without_mutating_input() -> None:
    original = rule()
    snapshot = original.model_dump_json()
    calls = []

    def apply_patch(target, patch):
        calls.append(patch)
        target.nodes[-1].since.append(patch.event)
        return target

    result = apply_answers_v2(
        original,
        [AnswerV2(question=decision(), allowed=True)],
        vocab=SHOP,
        apply_patch=apply_patch,
    )
    assert len(calls) == 1
    assert result.rule.nodes[-1].since == ["refunded"]
    assert result.meaning == render_rule(result.rule)
    assert "starts again after each refunded event" in result.meaning
    assert result.confirmed_examples[0].violation is False
    assert not result.mismatches and original.model_dump_json() == snapshot


def test_meaning_is_unchanged_when_owner_says_no() -> None:
    result = apply_answers_v2(
        rule(),
        [AnswerV2(question=decision(), allowed=False)],
        vocab=SHOP,
        apply_patch=lambda r, _: r,
    )
    assert result.meaning == render_rule(rule())


def test_no_does_not_apply_patch() -> None:
    def forbidden(*_):
        pytest.fail("No must not invoke the core patch port")

    result = apply_answers_v2(
        rule(),
        [AnswerV2(question=decision(), allowed=False)],
        vocab=SHOP,
        apply_patch=forbidden,
    )
    assert result.rule.nodes == rule().nodes
    assert result.confirmed_examples[0].violation is True
    assert result.rule.confirmed_examples == result.confirmed_examples  # B2: inside the rule


def test_duplicate_examples_and_patches_are_skipped() -> None:
    calls = []

    def apply_patch(target, patch):
        calls.append(patch)
        target.nodes[-1].since.append(patch.event)
        return target

    answers = [AnswerV2(question=decision(), allowed=True)] * 2
    result = apply_answers_v2(rule(), answers, vocab=SHOP, apply_patch=apply_patch)
    assert len(calls) == len(result.confirmed_examples) == 1


@pytest.mark.parametrize("kind", ["reset", "exclude"])
def test_patch_already_in_rule_is_not_applied_again(kind) -> None:
    original = rule()
    if kind == "reset":
        original.nodes[-1].since.append("refunded")
        question = decision()
    else:
        original.nodes[0].exclude.append(
            ConditionV2(field="payment_type", op="eq", value="installment")
        )
        question = decision(patch=exclude())

    def forbidden(*_):
        pytest.fail("An existing patch must not call the core patch port")

    result = apply_answers_v2(
        original,
        [AnswerV2(question=question, allowed=True)],
        vocab=SHOP,
        apply_patch=forbidden,
    )
    assert result.rule.nodes == original.nodes and len(result.confirmed_examples) == 1


@pytest.mark.parametrize("expected,allowed", [(True, True), (False, False)])
def test_confirmation_mismatch_is_not_recorded(expected, allowed) -> None:
    result = apply_answers_v2(
        rule(),
        [AnswerV2(question=confirmation(expected_violation=expected), allowed=allowed)],
        vocab=SHOP,
        apply_patch=lambda r, _: r,
    )
    expected_word = "not allowed" if expected else "allowed"
    assert result.mismatches == [f"c1: owner answered the opposite of '{expected_word}'"]
    assert not result.confirmed_examples


@pytest.mark.parametrize("expected", [True, False])
def test_confirmation_agreement_is_recorded(expected) -> None:
    result = apply_answers_v2(
        rule(),
        [AnswerV2(question=confirmation(expected_violation=expected), allowed=not expected)],
        vocab=SHOP,
        apply_patch=lambda r, _: r,
    )
    assert result.confirmed_examples[0].violation is expected
    assert not result.mismatches


@pytest.mark.parametrize(
    "changes",
    [
        {"patch": None},
        {"expected_violation": False},
        {"timeline": []},
    ],
)
def test_inconsistent_decision_rejected(changes) -> None:
    with pytest.raises(ValidationError):
        decision(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"expected_violation": None},
        {"patch": reset()},
        {"why": "not a confirmation"},
    ],
)
def test_inconsistent_confirmation_rejected(changes) -> None:
    with pytest.raises(ValidationError):
        confirmation(**changes)


def test_invalid_patched_rule_becomes_parse_error() -> None:
    original = rule()
    with pytest.raises(ParseError, match="unknown reset event"):
        apply_answers_v2(
            original,
            [AnswerV2(question=decision(), allowed=True)],
            vocab=SHOP,
            apply_patch=lambda r, _: r.model_copy(
                update={
                    "nodes": [r.nodes[0], r.nodes[1].model_copy(update={"since": ["invented"]})]
                }
            ),
        )
    assert original.nodes[-1].since == []


def test_invalid_input_rule_is_rejected_even_without_answers() -> None:
    with pytest.raises(ParseError):
        apply_answers_v2(
            rule().model_copy(update={"root": "missing"}),
            [],
            vocab=SHOP,
            apply_patch=lambda r, _: r,
        )


def test_core_validation_error_becomes_parse_error() -> None:
    def apply_patch(target, _):
        return type(target).model_validate({**target.model_dump(), "root": ""})

    with pytest.raises(ParseError):
        apply_answers_v2(
            rule(),
            [AnswerV2(question=decision(), allowed=True)],
            vocab=SHOP,
            apply_patch=apply_patch,
        )


@pytest.mark.parametrize(
    ("patch", "reason"),
    [
        (exclude(condition={"field": "order_id", "op": "eq", "value": "o-1"}), "closed value"),
        (exclude(condition={"field": "payment_type", "op": "eq", "value": "paypal"}), "outside"),
        (exclude(select_ids=["check"]), "must be a select node"),
        (reset(node_id="charges"), "reset target"),
        (reset(event="invented"), "not in the vocabulary"),
    ],
)
def test_yes_rechecks_client_patch_before_core(patch, reason) -> None:
    # /answers is stateless: the patch is browser input, so clarify's policy runs again.
    calls = []

    def apply_patch(target, applied):
        calls.append(applied)
        return target

    with pytest.raises(ParseError, match=reason):
        apply_answers_v2(
            rule(),
            [AnswerV2(question=decision(patch=patch), allowed=True)],
            vocab=SHOP,
            apply_patch=apply_patch,
        )
    assert calls == []


def test_no_answer_does_not_recheck_patch() -> None:
    bad = exclude(condition={"field": "order_id", "op": "eq", "value": "o-1"})
    result = apply_answers_v2(
        rule(),
        [AnswerV2(question=decision(patch=bad), allowed=False)],
        vocab=SHOP,
        apply_patch=lambda r, _: r,
    )
    assert result.confirmed_examples[0].violation is True


def test_build_questions_keeps_decision_ids_and_numbers_confirmations() -> None:
    example = CanonicalExample("One charge", tuple(decision().timeline), False)
    decisions = [
        Decision(
            id="d1",
            question="Missing example?",
            why="Dropped",
            patch=AddReset.model_validate(reset()),
            example=None,
        ),
        Decision(
            id="d2",
            question="Is this exception allowed?",
            why="Owner decides",
            patch=AddExclude.model_validate(exclude()),
            example=example,
        ),
    ]
    outcome = ClarifyV2Outcome(
        rule=rule(),
        meaning=render_rule(rule()),
        decisions=decisions,
        dropped=[],
        cached=False,
    )
    questions = build_questions(outcome, [example, example])
    assert [q.id for q in questions] == ["c1", "c2", "d2"]
    assert questions[0].text == "Is this allowed?" and questions[0].expected_violation is False
    assert questions[0].patch is questions[0].why is None
    assert questions[-1].text == decisions[-1].question
    assert questions[-1].why == "Owner decides"
    assert questions[-1].patch == decisions[-1].patch
