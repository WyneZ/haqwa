"""GeminiClient tests. A fake SDK stands in for Gemini: no network, no quota used."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from google.genai import errors as genai_errors
from pydantic import BaseModel

from haqwa.ai.client import (
    DEFAULT_MODEL,
    GeminiBadOutput,
    GeminiClient,
    GeminiQuotaError,
    GeminiUnavailable,
)


class Answer(BaseModel):
    text: str


class OtherAnswer(BaseModel):
    text: str
    score: int = 0


class _Response:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeSDK:
    """Mimics `google.genai.Client`: each call pops the next scripted outcome."""

    def __init__(self, *outcomes: str | Exception) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []
        self.models = self

    def generate_content(self, **kwargs: Any) -> _Response:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return _Response(outcome)


def quota_429(quota_id: str, retry_delay: str | None = None) -> genai_errors.ClientError:
    details: list[dict[str, Any]] = [
        {
            "@type": "type.googleapis.com/google.rpc.QuotaFailure",
            "violations": [{"quotaId": quota_id}],
        }
    ]
    if retry_delay:
        details.append(
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": retry_delay}
        )
    body = {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "details": details}}
    return genai_errors.ClientError(429, body)


PER_DAY = "GenerateRequestsPerDayPerProjectPerModel-FreeTier"
PER_MINUTE = "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"
OK = '{"text": "hi"}'


def unavailable_503() -> genai_errors.ServerError:
    return genai_errors.ServerError(503, {"error": {"code": 503, "status": "UNAVAILABLE"}})


def make_client(sdk: FakeSDK, tmp_path: Path, **kwargs: Any) -> tuple[GeminiClient, list[float]]:
    waits: list[float] = []
    client = GeminiClient(
        model="test-model", cache_dir=tmp_path / "cache", sdk=sdk, sleep=waits.append, **kwargs
    )
    return client, waits


# ---- success and cache ----------------------------------------------------------------


def test_returns_validated_value_and_sends_schema(tmp_path: Path) -> None:
    sdk = FakeSDK(OK)
    client, _ = make_client(sdk, tmp_path)

    result = client.generate("say hi", Answer)

    assert result.value == Answer(text="hi")
    assert result.cached is False
    assert result.model == "test-model"
    config = sdk.calls[0]["config"]
    assert config["response_mime_type"] == "application/json"
    assert config["response_schema"] is Answer
    assert config["automatic_function_calling"] == {"disable": True}


def test_second_identical_call_uses_cache_without_calling_gemini(tmp_path: Path) -> None:
    sdk = FakeSDK(OK)
    client, _ = make_client(sdk, tmp_path)

    client.generate("say hi", Answer)
    second = client.generate("say hi", Answer)

    assert second.cached is True
    assert second.value == Answer(text="hi")
    assert len(sdk.calls) == 1


def test_cache_misses_when_prompt_or_schema_changes(tmp_path: Path) -> None:
    sdk = FakeSDK(OK, OK, '{"text": "hi", "score": 1}')
    client, _ = make_client(sdk, tmp_path)

    client.generate("say hi", Answer)
    changed_prompt = client.generate("say hi!", Answer)
    changed_schema = client.generate("say hi", OtherAnswer)

    assert changed_prompt.cached is False
    assert changed_schema.cached is False
    assert len(sdk.calls) == 3


def test_cache_misses_when_model_changes(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    GeminiClient(model="model-a", cache_dir=cache, sdk=FakeSDK(OK)).generate("p", Answer)
    other = GeminiClient(model="model-b", cache_dir=cache, sdk=FakeSDK(OK))

    assert other.generate("p", Answer).cached is False


def test_corrupt_cache_entry_is_treated_as_a_miss(tmp_path: Path) -> None:
    sdk = FakeSDK(OK, OK)
    client, _ = make_client(sdk, tmp_path)
    client.generate("p", Answer)
    for entry in (tmp_path / "cache").glob("*.json"):
        entry.write_text("not json", encoding="utf-8")

    result = client.generate("p", Answer)

    assert result.cached is False
    assert len(sdk.calls) == 2


def test_cache_can_be_turned_off(tmp_path: Path) -> None:
    sdk = FakeSDK(OK, OK)
    client = GeminiClient(model="m", cache_dir=None, sdk=sdk)

    client.generate("p", Answer)
    client.generate("p", Answer)

    assert len(sdk.calls) == 2


def test_model_comes_from_env_then_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAQWA_MODEL", "env-model")
    assert GeminiClient(sdk=FakeSDK()).model == "env-model"
    monkeypatch.delenv("HAQWA_MODEL")
    assert GeminiClient(sdk=FakeSDK()).model == DEFAULT_MODEL


# ---- bad output -----------------------------------------------------------------------


def test_invalid_json_raises_bad_output_and_is_not_cached(tmp_path: Path) -> None:
    sdk = FakeSDK('{"wrong": 1}', OK)
    client, _ = make_client(sdk, tmp_path)

    with pytest.raises(GeminiBadOutput):
        client.generate("p", Answer)

    assert client.generate("p", Answer).cached is False  # the bad answer was not stored


# ---- server errors --------------------------------------------------------------------


def test_503_is_retried_with_backoff_then_succeeds(tmp_path: Path) -> None:
    sdk = FakeSDK(unavailable_503(), httpx.ConnectError("drop"), OK)
    client, waits = make_client(sdk, tmp_path)

    assert client.generate("p", Answer).value.text == "hi"
    assert waits == [2.0, 4.0]


def test_503_after_all_retries_raises_unavailable(tmp_path: Path) -> None:
    sdk = FakeSDK(*[unavailable_503() for _ in range(4)])
    client, waits = make_client(sdk, tmp_path)

    with pytest.raises(GeminiUnavailable):
        client.generate("p", Answer)
    assert len(sdk.calls) == 4
    assert waits == [2.0, 4.0, 8.0]


# ---- quota ----------------------------------------------------------------------------


def test_per_day_quota_stops_at_once(tmp_path: Path) -> None:
    sdk = FakeSDK(quota_429(PER_DAY), OK)
    client, waits = make_client(sdk, tmp_path)

    with pytest.raises(GeminiQuotaError) as info:
        client.generate("p", Answer)

    assert info.value.per_day is True
    assert len(sdk.calls) == 1  # no retry: it would only burn more quota
    assert waits == []


def test_per_minute_quota_waits_the_requested_delay_then_succeeds(tmp_path: Path) -> None:
    sdk = FakeSDK(quota_429(PER_MINUTE, retry_delay="34s"), OK)
    client, waits = make_client(sdk, tmp_path)

    assert client.generate("p", Answer).value.text == "hi"
    assert waits == [35.0]  # requested delay + 1s margin


def test_per_minute_quota_without_delay_uses_fallback(tmp_path: Path) -> None:
    sdk = FakeSDK(quota_429(PER_MINUTE), OK)
    client, waits = make_client(sdk, tmp_path)

    client.generate("p", Answer)
    assert waits == [16.0]


def test_per_minute_quota_that_persists_raises_quota_error(tmp_path: Path) -> None:
    sdk = FakeSDK(*[quota_429(PER_MINUTE, retry_delay="5s") for _ in range(3)])
    client, _ = make_client(sdk, tmp_path)

    with pytest.raises(GeminiQuotaError) as info:
        client.generate("p", Answer)

    assert info.value.per_day is False
    assert len(sdk.calls) == 3


def test_other_client_errors_are_not_retried(tmp_path: Path) -> None:
    bad_request = genai_errors.ClientError(400, {"error": {"code": 400, "status": "INVALID"}})
    sdk = FakeSDK(bad_request)
    client, waits = make_client(sdk, tmp_path)

    with pytest.raises(genai_errors.ClientError):
        client.generate("p", Answer)
    assert waits == []
