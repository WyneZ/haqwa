"""explain_violation(): advisory text for one violation. Gemini is faked: no quota used."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from google.genai import errors as genai_errors

from haqwa.ai.client import GeminiClient, GeminiQuotaError
from haqwa.ai.explain import WireExplanation, build_prompt, explain_violation
from haqwa.core.events import Event
from haqwa.core.report import Violation
from haqwa.core.spec import AllowIf, AtMostOnce, Condition, ResetAfter

RULE = AtMostOnce(
    id="no-double-charge",
    source="A customer must not be charged twice for the same order.",
    pattern="at_most_once",
    event="charged",
    per="order_id",
    exceptions=[
        ResetAfter(reset_after="refunded"),
        AllowIf(allow_if=Condition(field="payment_type", op="eq", value="installment")),
    ],
)
T0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
VIOLATION = Violation(
    rule_id="no-double-charge",
    entity="A-2",
    message="'charged' happened 2 times with no refunded in between",
    timeline=[
        Event(event="order_created", ts=T0, data={"order_id": "A-2"}),
        Event(event="charged", ts=T0 + timedelta(minutes=1),
              data={"order_id": "A-2", "amount": 120}),
        Event(event="charged", ts=T0 + timedelta(minutes=1, seconds=30),
              data={"order_id": "A-2", "amount": 120}),
    ],
    offending_index=2,
)  # fmt: skip

ANSWER = {"text": "  Order A-2 was charged twice, 30 seconds apart. Likely a retry.  "}


class _Response:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeSDK:
    def __init__(self, *outcomes: dict[str, Any] | Exception) -> None:
        self.outcomes = list(outcomes)
        self.prompts: list[str] = []
        self.models = self

    def generate_content(self, **kwargs: Any) -> _Response:
        self.prompts.append(kwargs["contents"])
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return _Response(json.dumps(outcome))


def client_for(sdk: FakeSDK, cache_dir: Path | None = None) -> GeminiClient:
    return GeminiClient(model="test", cache_dir=cache_dir, sdk=sdk, sleep=lambda _: None)


def test_returns_advisory_text() -> None:
    result = explain_violation(RULE, VIOLATION, client=client_for(FakeSDK(ANSWER)))
    assert result.text == "Order A-2 was charged twice, 30 seconds apart. Likely a retry."
    assert result.advisory is True
    assert result.cached is False


def test_prompt_has_rule_decisions_entity_and_marked_timeline() -> None:
    prompt = build_prompt(RULE, VIOLATION)
    assert '"A customer must not be charged twice for the same order."' in prompt
    assert "After 'refunded', the order_id starts fresh." in prompt
    assert "payment_type eq 'installment'" in prompt
    assert "order_id A-2" in prompt
    assert ">> 2026-10-01T09:01:30+00:00  charged  (amount=120)" in prompt
    assert "ALREADY decided this is a violation" in prompt
    assert "Do not add currencies, units" in prompt  # live run once invented "$50"


def test_entity_key_is_not_repeated_in_event_lines() -> None:
    assert "order_id=A-2" not in build_prompt(RULE, VIOLATION)


def test_rule_without_exceptions_says_none() -> None:
    plain = RULE.model_copy(update={"exceptions": []})
    assert "- (none)" in build_prompt(plain, VIOLATION)


def test_second_call_is_cached(tmp_path: Path) -> None:
    sdk = FakeSDK(ANSWER)
    client = client_for(sdk, cache_dir=tmp_path)
    explain_violation(RULE, VIOLATION, client=client)
    again = explain_violation(RULE, VIOLATION, client=client)
    assert again.cached is True and again.advisory is True
    assert len(sdk.prompts) == 1


def test_quota_error_reaches_the_caller() -> None:
    per_day = genai_errors.ClientError(
        429, {"error": {"details": [{"violations": [{"quotaId": "PerDayPerProject"}]}]}}
    )
    with pytest.raises(GeminiQuotaError):
        explain_violation(RULE, VIOLATION, client=client_for(FakeSDK(per_day)))


def test_wire_schema_is_accepted_by_gemini() -> None:
    schema = json.dumps(WireExplanation.model_json_schema())
    for rejected in ("oneOf", "discriminator", "additionalProperties"):
        assert rejected not in schema
