"""parse_v2(): Gemini is faked, so no quota is used."""

from __future__ import annotations

import json
from typing import Any

import pytest

from haqwa.ai.client import GeminiBadOutput, GeminiClient
from haqwa.ai.parse import ParseError
from haqwa.ai.parse_v2 import _examples, build_prompt, parse_v2
from haqwa.ai.rule_wire import WireRule, to_rule_v2
from haqwa.ai.vocab import Vocabulary
from haqwa.core.rules_v2 import RuleV2

from .test_rule_wire import SHOP


class _Response:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeSDK:
    """Stands in for google.genai.Client and returns one fixed JSON answer."""

    def __init__(self, answer: dict[str, Any]) -> None:
        self.answer = json.dumps(answer)
        self.prompts: list[str] = []
        self.models = self

    def generate_content(self, **kwargs: Any) -> _Response:
        self.prompts.append(kwargs["contents"])
        return _Response(self.answer)


def run(answer: dict[str, Any], text: str = "rule text", rule_id: str | None = "r1"):
    sdk = FakeSDK(answer)
    client = GeminiClient(model="test", cache_dir=None, sdk=sdk)
    return parse_v2(text, rule_id=rule_id, vocab=SHOP, client=client), sdk


NO_DOUBLE_CHARGE = {
    "per": "order_id",
    "root": "check",
    "nodes": [
        {"id": "charges", "type": "select", "event": "charged"},
        {"id": "check", "type": "count", "of": "charges", "op": "le", "value": 1,
         "since": ["refunded"]},
    ],
}  # fmt: skip


# ---- positive -------------------------------------------------------------------------


def test_supported_rule_with_meaning() -> None:
    outcome, _ = run(NO_DOUBLE_CHARGE, text="A customer must not be charged twice.")
    assert outcome.status == "supported"
    assert isinstance(outcome.rule, RuleV2)
    assert outcome.rule.id == "r1"
    assert outcome.rule.source == "A customer must not be charged twice."
    assert outcome.meaning == (
        "For each order: there must be at most 1 charged event "
        "(it starts again after each refunded event)."
    )


def test_unsupported() -> None:
    outcome, _ = run({"unsupported_reason": "needs a moving average"})
    assert outcome.status == "unsupported"
    assert outcome.reason == "needs a moving average"
    assert outcome.rule is None and outcome.meaning is None


def test_rule_id_suggested_when_missing() -> None:
    outcome, _ = run(NO_DOUBLE_CHARGE, text="No double charge.", rule_id=None)
    assert outcome.rule is not None
    assert outcome.rule.id  # core's suggest_rule_id picked one


def test_prompt_carries_vocabulary_and_rule() -> None:
    _, sdk = run(NO_DOUBLE_CHARGE, text="Refunds need a charge.")
    prompt = sdk.prompts[0]
    assert 'Rule: "Refunds need a charge."' in prompt
    assert "Events: order_created, charged, refunded" in prompt
    assert "payment_type: card, installment" in prompt
    assert "Numeric fields (only these can be summed or compared with gt/ge/lt/le): amount" in (
        prompt
    )


def test_prompt_is_deterministic() -> None:
    assert build_prompt("x", SHOP) == build_prompt("x", SHOP)


# ---- negative: bad Gemini answers become ParseError, never a rule ------------------------


def test_invented_event_rejected_by_schema() -> None:
    """Event names are an enum in the per-vocabulary schema, so this cannot even decode."""
    bad = json.loads(json.dumps(NO_DOUBLE_CHARGE))
    bad["nodes"][0]["event"] = "payment_captured"
    with pytest.raises(GeminiBadOutput):
        run(bad)


def test_corrupted_name_from_g1_run2_rejected_by_schema() -> None:
    bad = json.loads(json.dumps(NO_DOUBLE_CHARGE))
    bad["nodes"][0]["event"] = "refun d_requested"
    with pytest.raises(GeminiBadOutput):
        run(bad)


def test_select_as_root_rejected() -> None:
    bad = {"per": "order_id", "root": "charges",
           "nodes": [{"id": "charges", "type": "select", "event": "charged"}]}  # fmt: skip
    with pytest.raises(ParseError):
        run(bad)


def test_example_names_leaking_into_answer_rejected() -> None:
    leaked = json.loads(json.dumps(NO_DOUBLE_CHARGE))
    leaked["per"] = "claim_id"  # from the HR worked examples, not this system
    with pytest.raises(GeminiBadOutput):
        run(leaked)


def test_schema_sent_to_gemini_is_per_vocabulary() -> None:
    from haqwa.ai.rule_wire import wire_schema

    schema = wire_schema(SHOP).model_json_schema()
    assert "payment_captured" not in json.dumps(schema)
    assert '"refund_requested"' in json.dumps(schema)


# ---- the worked examples in the prompt are themselves valid ---------------------------

EXAMPLE_VOCAB = Vocabulary(
    events=["paid", "reversed", "withdrawn", "approved", "submitted", "decided"],
    fields=["claim_id", "kind", "amount", "approver", "submitter"],
    numeric_fields=["amount"],
)


@pytest.mark.parametrize("text_and_wire", _examples(), ids=lambda tw: tw[0][:30])
def test_worked_example_is_valid(text_and_wire: tuple[str, WireRule]) -> None:
    text, wire = text_and_wire
    to_rule_v2(wire, rule_id="example", source=text, vocab=EXAMPLE_VOCAB)  # raises if invalid


def test_examples_do_not_use_demo_shop_names() -> None:
    """The worked examples must not teach the deployed demo's own names."""
    from web.api.config import SHOP_VOCAB

    demo = set(SHOP_VOCAB.events) | set(SHOP_VOCAB.fields)
    examples = set(EXAMPLE_VOCAB.events) | set(EXAMPLE_VOCAB.fields)
    assert examples & demo == {"amount"}  # a generic numeric field name is fine
