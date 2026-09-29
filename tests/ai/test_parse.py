"""Draft (Gemini wire format) -> C1 rule. Pure functions: no Gemini, no quota."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from pydantic import BaseModel, ValidationError

from haqwa.ai.parse import (
    AtMostOnceDraft,
    DraftRule,
    MustPrecedeDraft,
    NeverAfterDraft,
    ParseError,
    UnsupportedDraft,
    WithinTimeDraft,
    draft_problems,
    to_rule,
)
from haqwa.ai.vocab import Vocabulary
from haqwa.core.spec import AtMostOnce, MustPrecede, NeverAfter, UnsupportedRule, WithinTime

SHOP = Vocabulary(
    events=["order_created", "charged", "refunded", "cancelled", "shipped",
            "refund_requested", "refund_completed"],
    fields=["order_id", "customer_id", "payment_type", "amount"],
    field_values={"payment_type": ["card", "installment"]},
)  # fmt: skip


def convert(draft: DraftRule) -> object:
    return to_rule(draft, rule_id="r1", source="rule text", vocab=SHOP)


# ---- positive: one per pattern ---------------------------------------------------------


def test_at_most_once() -> None:
    rule = convert(AtMostOnceDraft(pattern="at_most_once", event="charged", per="order_id"))
    assert rule == AtMostOnce(
        id="r1", source="rule text", pattern="at_most_once", event="charged", per="order_id"
    )


def test_never_after() -> None:
    draft = NeverAfterDraft(
        pattern="never_after", after="cancelled", event="shipped", per="order_id"
    )
    rule = convert(draft)
    assert isinstance(rule, NeverAfter)
    assert (rule.after, rule.event, rule.per) == ("cancelled", "shipped", "order_id")


def test_must_precede() -> None:
    draft = MustPrecedeDraft(
        pattern="must_precede", requires="charged", event="shipped", per="order_id"
    )
    rule = convert(draft)
    assert isinstance(rule, MustPrecede)
    assert (rule.requires, rule.event) == ("charged", "shipped")


def test_within_time_converts_iso_duration() -> None:
    draft = WithinTimeDraft(
        pattern="within_time",
        start="refund_requested",
        event="refund_completed",
        within="PT24H",
        per="order_id",
    )
    rule = convert(draft)
    assert isinstance(rule, WithinTime)
    assert rule.within == timedelta(hours=24)


def test_unsupported_keeps_reason_and_source() -> None:
    rule = convert(UnsupportedDraft(pattern="unsupported", reason="needs amounts summed"))
    assert rule == UnsupportedRule(source="rule text", reason="needs amounts summed")


def test_new_rule_has_no_exceptions_or_examples_yet() -> None:
    rule = convert(AtMostOnceDraft(pattern="at_most_once", event="charged", per="order_id"))
    assert isinstance(rule, AtMostOnce)
    assert rule.exceptions == []
    assert rule.confirmed_examples == []


# ---- the wire format --------------------------------------------------------------------


class _Wrapper(BaseModel):
    draft: DraftRule


def test_wire_json_picks_the_right_draft_model() -> None:
    raw = '{"draft": {"pattern": "never_after", "after": "cancelled", "event": "shipped",'
    raw += ' "per": "order_id"}}'
    assert isinstance(_Wrapper.model_validate_json(raw).draft, NeverAfterDraft)


def test_wire_schema_is_accepted_by_gemini() -> None:
    # google-genai rejects oneOf + discriminator and additionalProperties (spike v2 finding).
    schema = json.dumps(_Wrapper.model_json_schema())
    assert "anyOf" in schema
    for rejected in ("oneOf", "discriminator", "additionalProperties"):
        assert rejected not in schema


def test_wire_json_with_unknown_pattern_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _Wrapper.model_validate_json('{"draft": {"pattern": "at_least_once", "event": "x"}}')


# ---- negative: vocabulary and C1 checks --------------------------------------------------


def test_unknown_event_is_a_problem() -> None:
    draft = NeverAfterDraft(pattern="never_after", after="closed", event="shipped", per="order_id")
    with pytest.raises(ParseError) as info:
        convert(draft)
    assert info.value.problems == ["draft.after: event 'closed' is not in the vocabulary"]


def test_unknown_per_field_is_a_problem() -> None:
    draft = AtMostOnceDraft(pattern="at_most_once", event="charged", per="invoice_id")
    with pytest.raises(ParseError, match="invoice_id"):
        convert(draft)


def test_all_problems_are_reported_together() -> None:
    draft = MustPrecedeDraft(pattern="must_precede", requires="paid", event="sent", per="order")
    assert len(draft_problems(draft, SHOP)) == 3


def test_same_event_twice_is_a_problem() -> None:
    draft = NeverAfterDraft(pattern="never_after", after="shipped", event="shipped", per="order_id")
    with pytest.raises(ParseError, match="two different events"):
        convert(draft)


def test_bad_iso_duration_is_a_parse_error() -> None:
    draft = WithinTimeDraft(
        pattern="within_time",
        start="refund_requested",
        event="refund_completed",
        within="24 hours",
        per="order_id",
    )
    with pytest.raises(ParseError, match="within"):
        convert(draft)


def test_bad_rule_id_is_a_parse_error() -> None:
    draft = AtMostOnceDraft(pattern="at_most_once", event="charged", per="order_id")
    with pytest.raises(ParseError, match="id"):
        to_rule(draft, rule_id="No Double Charge", source="x", vocab=SHOP)


def test_unsupported_draft_skips_vocabulary_checks() -> None:
    assert draft_problems(UnsupportedDraft(pattern="unsupported", reason="r"), SHOP) == []


# ---- Vocabulary ------------------------------------------------------------------------


def test_vocabulary_value_check() -> None:
    assert SHOP.value_problem("payment_type", "card, installment", "x") is None
    assert SHOP.value_problem("order_id", "anything", "x") is None  # free field
    assert "replacement" in (SHOP.value_problem("payment_type", "replacement", "x") or "")


def test_vocabulary_rejects_values_for_unknown_field() -> None:
    with pytest.raises(ValidationError):
        Vocabulary(events=["a"], fields=["x"], field_values={"y": ["1"]})


def test_vocabulary_needs_at_least_one_event() -> None:
    with pytest.raises(ValidationError):
        Vocabulary(events=[])


def test_vocabulary_values_text() -> None:
    assert SHOP.values_text() == "payment_type: card, installment"
