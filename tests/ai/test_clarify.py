"""clarify() and apply_answers(). Gemini is faked with REAL spike v2.1 outputs: no quota used."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from haqwa.ai.clarify import (
    Answer,
    Question,
    WireAmbiguity,
    WireClarify,
    apply_answers,
    build_prompt,
    clarify,
    decision_questions,
)
from haqwa.ai.client import GeminiClient
from haqwa.ai.parse import ParseError
from haqwa.ai.vocab import Vocabulary
from haqwa.core.spec import (
    AllowIf,
    AtMostOnce,
    Condition,
    ConfirmedExample,
    NeverAfter,
    ResetAfter,
    TimelineEvent,
)

RUNS = Path(__file__).resolve().parents[2] / "spikes" / "clarify" / "runs"

SHOP = Vocabulary(
    events=["order_created", "charged", "charge_failed", "refunded", "cancelled", "shipped",
            "refund_requested", "refund_completed"],
    fields=["order_id", "customer_id", "payment_type", "amount", "time"],
    field_values={"payment_type": ["card", "installment"]},
)  # fmt: skip


def spike_raw(rule: str) -> dict[str, Any]:
    """Gemini's real answer for R1/R2/R3 from spike v2.1, run 1."""
    path = RUNS / f"v21_gemini-3.6-flash_{rule}_run1.json"
    return json.loads(path.read_text(encoding="utf-8"))["raw"]


class _Response:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeSDK:
    """Stands in for google.genai.Client and always returns one fixed JSON answer."""

    def __init__(self, answer: dict[str, Any]) -> None:
        self.answer = json.dumps(answer)
        self.prompts: list[str] = []
        self.models = self

    def generate_content(self, **kwargs: Any) -> _Response:
        self.prompts.append(kwargs["contents"])
        return _Response(self.answer)


def run_clarify(answer: dict[str, Any], text: str = "rule text", rule_id: str = "r1"):
    sdk = FakeSDK(answer)
    client = GeminiClient(model="test", cache_dir=None, sdk=sdk)
    return clarify(text, rule_id=rule_id, vocab=SHOP, client=client), sdk


# ---- clarify() on real Gemini output ------------------------------------------------------


def test_r1_rule_and_two_decision_questions() -> None:
    outcome, _ = run_clarify(spike_raw("R1"), rule_id="no-double-charge")

    assert outcome.status == "supported"
    assert isinstance(outcome.rule, AtMostOnce)
    assert (outcome.rule.id, outcome.rule.event, outcome.rule.per) == (
        "no-double-charge",
        "charged",
        "order_id",
    )
    assert [q.id for q in outcome.questions] == ["d1", "d2"]
    assert outcome.questions[0].if_yes == ResetAfter(reset_after="refunded")
    assert outcome.questions[1].if_yes == AllowIf(
        allow_if=Condition(field="payment_type", op="eq", value="installment")
    )
    assert outcome.dropped == []


def test_timeline_drops_the_entity_key_but_keeps_other_fields() -> None:
    outcome, _ = run_clarify(spike_raw("R1"))
    # Gemini wrote order_id "123"; core's self-test adds its own entity id.
    assert outcome.questions[0].timeline[0] == TimelineEvent(event="charged", data={})
    assert outcome.questions[1].timeline[0] == TimelineEvent(
        event="charged", data={"payment_type": "installment"}
    )


def test_r2_never_after_with_reset_question() -> None:
    outcome, _ = run_clarify(spike_raw("R2"))
    assert isinstance(outcome.rule, NeverAfter)
    assert [q.if_yes for q in outcome.questions] == [ResetAfter(reset_after="order_created")]


def test_r3_within_time_has_three_questions() -> None:
    outcome, _ = run_clarify(spike_raw("R3"))
    assert outcome.rule is not None and outcome.rule.pattern == "within_time"
    assert len(outcome.questions) == 3


def test_prompt_uses_the_callers_vocabulary() -> None:
    _, sdk = run_clarify(spike_raw("R1"), text="A customer must not be charged twice.")
    prompt = sdk.prompts[0]
    assert "refund_completed" in prompt
    assert "payment_type: card, installment" in prompt
    assert '"A customer must not be charged twice."' in prompt


def test_unsupported_rule() -> None:
    answer = {"rule_id": "r1", "parse": {"pattern": "unsupported", "reason": "sums"},
              "ambiguities": []}  # fmt: skip
    outcome, _ = run_clarify(answer)
    assert outcome.status == "unsupported"
    assert outcome.reason == "sums"
    assert outcome.rule is None and outcome.questions == []


def test_draft_outside_vocabulary_raises_parse_error() -> None:
    answer = spike_raw("R2")
    answer["parse"]["after"] = "closed"
    with pytest.raises(ParseError, match="closed"):
        run_clarify(answer)


def test_wire_schema_is_accepted_by_gemini() -> None:
    schema = json.dumps(WireClarify.model_json_schema())
    for rejected in ("oneOf", "discriminator", "additionalProperties"):
        assert rejected not in schema


def test_prompt_is_stable_for_the_cache() -> None:
    # Same inputs -> same prompt text -> same cache key (client.py).
    assert build_prompt("r1", "x", SHOP) == build_prompt("r1", "x", SHOP)


# ---- noise filter (spike v2.1 rule C) -----------------------------------------------------


def ambiguity(**change: Any) -> dict[str, Any]:
    return {
        "id": "q",
        "description": "d",
        "examples": [{"events": [{"event": "charged", "data": []}], "question": "Allowed?"}],
        "spec_change_if_yes": change,
    }


def decide(*items: dict[str, Any]):
    parsed = [WireAmbiguity.model_validate(i) for i in items]
    return decision_questions(parsed, per="order_id", vocab=SHOP)


def test_invented_value_is_dropped() -> None:
    cond = {"field": "payment_type", "op": "eq", "value": "store_credit"}
    kept, dropped = decide(ambiguity(kind="allow_if", condition=cond))
    assert kept == []
    assert "store_credit" in dropped[0].reasons[0]


def test_invented_event_is_dropped() -> None:
    item = ambiguity(kind="reset_after", event="replacement_sent")
    kept, dropped = decide(item)
    assert kept == [] and "replacement_sent" in dropped[0].reasons[0]


def test_kind_none_is_dropped() -> None:
    kept, dropped = decide(ambiguity(kind="none"))
    assert kept == [] and "cannot change the spec" in dropped[0].reasons[0]


def test_allow_if_in_becomes_a_list() -> None:
    cond = {"field": "payment_type", "op": "in", "value": "card, installment"}
    kept, _ = decide(ambiguity(kind="allow_if", condition=cond))
    assert kept[0].if_yes == AllowIf(
        allow_if=Condition(field="payment_type", op="in", value=["card", "installment"])
    )


def test_ids_stay_consecutive_after_a_drop() -> None:
    kept, _ = decide(
        ambiguity(kind="none"),
        ambiguity(kind="reset_after", event="refunded"),
        ambiguity(kind="reset_after", event="cancelled"),
    )
    assert [q.id for q in kept] == ["d1", "d2"]


# ---- apply_answers() ----------------------------------------------------------------------

RULE = AtMostOnce(id="r1", source="s", pattern="at_most_once", event="charged", per="order_id")
TWICE = [TimelineEvent(event="charged"), TimelineEvent(event="charged")]
REFUND = [TimelineEvent(event="charged"), TimelineEvent(event="refunded"),
          TimelineEvent(event="charged")]  # fmt: skip
RESET = ResetAfter(reset_after="refunded")


def decision(timeline: list[TimelineEvent], if_yes: Any = RESET) -> Question:
    return Question(id="d1", kind="decision", text="?", timeline=timeline, if_yes=if_yes)


def confirmation(timeline: list[TimelineEvent], expected: bool) -> Question:
    return Question(
        id="c1", kind="confirmation", text="Is this allowed?", timeline=timeline,
        expected_violation=expected,
    )  # fmt: skip


def test_yes_adds_exception_and_allowed_example() -> None:
    out = apply_answers(RULE, [Answer(question=decision(REFUND), allowed=True)])
    assert out.rule.exceptions == [RESET]
    assert out.rule.confirmed_examples == [ConfirmedExample(timeline=REFUND, violation=False)]
    assert out.mismatches == []


def test_no_adds_violation_example_only() -> None:
    out = apply_answers(RULE, [Answer(question=decision(REFUND), allowed=False)])
    assert out.rule.exceptions == []
    assert out.rule.confirmed_examples == [ConfirmedExample(timeline=REFUND, violation=True)]


def test_same_answer_twice_is_not_duplicated() -> None:
    answer = Answer(question=decision(REFUND), allowed=True)
    out = apply_answers(RULE, [answer, answer])
    assert len(out.rule.exceptions) == 1
    assert len(out.rule.confirmed_examples) == 1


def test_confirmation_that_matches_is_recorded() -> None:
    out = apply_answers(RULE, [Answer(question=confirmation(TWICE, True), allowed=False)])
    assert out.mismatches == []
    assert out.rule.confirmed_examples == [ConfirmedExample(timeline=TWICE, violation=True)]


def test_confirmation_that_contradicts_is_a_mismatch_and_not_recorded() -> None:
    out = apply_answers(RULE, [Answer(question=confirmation(TWICE, True), allowed=True)])
    assert len(out.mismatches) == 1 and out.mismatches[0].startswith("c1")
    assert out.rule.confirmed_examples == []


def test_original_rule_is_not_changed() -> None:
    apply_answers(RULE, [Answer(question=decision(REFUND), allowed=True)])
    assert RULE.exceptions == [] and RULE.confirmed_examples == []


def test_updated_rule_serialises_with_c1_alias() -> None:
    out = apply_answers(RULE, [Answer(question=decision(REFUND), allowed=True)])
    dumped = out.rule.model_dump(by_alias=True, exclude_none=True)
    assert dumped["except"] == [{"reset_after": "refunded"}]
