"""Suggestion validation with a fake Gemini client; no network calls."""

import pytest

from haqwa.ai.client import GeminiBadOutput, GeminiResult
from haqwa.ai.suggest import SuggestedVocabulary, suggest_vocabulary


class FakeClient:
    def __init__(self, answer: dict) -> None:
        self.answer = answer
        self.prompt = ""

    def generate(self, prompt, schema):
        self.prompt = prompt
        assert schema is SuggestedVocabulary
        return GeminiResult(value=schema.model_validate(self.answer), cached=False, model="fake")


def test_suggest_deduplicates_names_and_fields() -> None:
    client = FakeClient({
        "events": [
            {"name": "order_charged", "description": "Charged the order"},
            {"name": "order_charged", "description": "Again"},
            {"name": "order_shipped", "description": "Shipped the order"},
        ],
        "entity_field": "order_id",
        "fields": ["order_id", "amount", "amount"],
    })
    result = suggest_vocabulary("Never charge twice.", client=client)
    assert [event.name for event in result.events] == ["order_charged", "order_shipped"]
    assert result.fields == ["order_id", "amount"]
    assert "Never charge twice." in client.prompt


@pytest.mark.parametrize("bad", ["OrderCharged", "9charged", "order-charged", "x" * 65])
def test_suggest_rejects_invalid_event_names(bad: str) -> None:
    client = FakeClient({
        "events": [{"name": bad, "description": "Charged the order"}],
        "entity_field": "order_id", "fields": ["order_id"],
    })
    with pytest.raises(GeminiBadOutput):
        suggest_vocabulary("Never charge twice.", client=client)


def test_suggest_rejects_too_many_events() -> None:
    client = FakeClient({
        "events": [{"name": f"event_{i}", "description": "Done"} for i in range(31)],
        "entity_field": "order_id", "fields": ["order_id"],
    })
    with pytest.raises(GeminiBadOutput):
        suggest_vocabulary("Policy", client=client)
