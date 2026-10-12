"""C3 API contract checks without Gemini or network access."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from haqwa.ai.clarify import ClarifyOutcome, Question, WireClarify
from haqwa.ai.client import GeminiQuotaError, GeminiUnavailable
from haqwa.ai.explain import Explanation
from haqwa.core.report import Violation
from haqwa.core.spec import AtMostOnce, TimelineEvent
from web.api import main as api_main
from web.api import routes
from web.api.main import create_app

RULE = {
    "id": "no-double-charge",
    "source": "Do not charge twice.",
    "pattern": "at_most_once",
    "event": "charged",
    "per": "order_id",
}
SPEC = {"version": 1, "rules": [RULE]}


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    app.dependency_overrides[routes.get_client] = lambda: object()
    return TestClient(app, raise_server_exceptions=False)


def assert_problem(response, code: str, status: int) -> None:
    assert response.status_code == status
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == code
    assert all(body.get(field) for field in ("type", "title", "status", "detail"))


def test_health_scenarios_and_openapi(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"ok": True}
    scenarios = client.get("/api/v1/scenarios").json()
    assert any(s["id"] == "payment_timeout_naive" for s in scenarios)
    assert all(s["expected"] == "unknown" for s in scenarios if s["agent"] == "gemini")
    assert all(s["kind"] in {"scripted", "recorded", "live"} for s in scenarios)
    assert all(s["kind"] == "scripted" for s in scenarios if s["agent"] != "gemini")
    assert any(s["kind"] == "live" for s in scenarios if "gemini_live_" in s["id"])
    assert all(
        s["kind"] == "recorded"
        for s in scenarios
        if s["agent"] == "gemini" and "gemini_live_" not in s["id"]
    )
    paths = client.get("/openapi.json").json()["paths"]
    for path in ("clarify", "answers", "seal", "scenarios", "runs", "explain"):
        assert f"/api/v1/{path}" in paths


def test_clarify_supported_and_unsupported(client: TestClient, monkeypatch) -> None:
    ids = []

    def fake_clarify(source, *, rule_id, vocab, client):
        ids.append(rule_id)
        if source == "unsupported":
            from haqwa.ai.parse import ParseError

            raise ParseError(["outside vocabulary"])
        rule = AtMostOnce.model_validate({**RULE, "id": rule_id})
        return ClarifyOutcome(
            source=source,
            status="supported",
            rule=rule,
            questions=[
                Question(
                    id="c1",
                    kind="confirmation",
                    text="Is this allowed?",
                    timeline=[TimelineEvent(event="charged")],
                )
            ],
            cached=True,
        )

    monkeypatch.setattr(routes, "clarify", fake_clarify)
    response = client.post("/api/v1/clarify", json={"rules": ["Charge once", "unsupported"]})
    assert response.status_code == 200
    body = response.json()
    assert body["results"][0]["status"] == "supported"
    assert body["results"][0]["rule"]["id"] == ids[0]
    assert "dropped" not in body["results"][0]
    assert body["results"][1]["status"] == "unsupported"
    assert body["cached"] is False


def test_clarify_uses_optional_vocabulary_in_fake_client(client: TestClient) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        def generate(self, prompt, schema):
            self.prompts.append(prompt)
            return SimpleNamespace(
                value=WireClarify.model_validate(
                    {
                        "rule_id": "rule",
                        "parse": {"pattern": "unsupported", "reason": "outside the four patterns"},
                        "ambiguities": [],
                    }
                ),
                cached=False,
            )

    fake = FakeClient()
    client.app.dependency_overrides[routes.get_client] = lambda: fake
    payload = {
        "rules": ["Decide every leave request."],
        "vocabulary": {"events": ["leave_requested", "leave_decided"], "fields": ["leave_id"]},
    }
    assert client.post("/api/v1/clarify", json=payload).status_code == 200
    assert "leave_requested" in fake.prompts[-1]
    assert "charged" not in fake.prompts[-1]
    assert client.post("/api/v1/clarify", json={"rules": payload["rules"]}).status_code == 200
    assert "charged" in fake.prompts[-1]


def test_clarify_rejects_invalid_vocabulary(client: TestClient) -> None:
    vocabulary = {"events": ["leave_requested"], "fields": ["leave_id"]}
    invalid = (
        {**vocabulary, "field_values": {"unknown": ["x"]}},
        {**vocabulary, "events": []},
        {**vocabulary, "events": ["leave requested"]},
        {**vocabulary, "field_values": {"leave_id": ["x"] * 51}},
    )
    for value in invalid:
        response = client.post("/api/v1/clarify", json={"rules": ["one"], "vocabulary": value})
        assert_problem(response, "invalid_request", 422)
        if "unknown" in value.get("field_values", {}):
            assert response.json()["detail"].startswith("Invalid vocabulary:")


def test_answers_and_invalid_rule(client: TestClient) -> None:
    question = {
        "id": "c1",
        "kind": "confirmation",
        "text": "Is this allowed?",
        "timeline": [{"event": "charged"}, {"event": "charged"}],
        "expected_violation": True,
    }
    response = client.post(
        "/api/v1/answers",
        json={"rule": RULE, "answers": [{"question": question, "allowed": False}]},
    )
    assert response.status_code == 200
    assert response.json()["rule"]["confirmed_examples"][0]["violation"] is True
    assert response.json()["mismatches"] == []
    bad = client.post("/api/v1/answers", json={"rule": {"pattern": "wrong"}, "answers": []})
    assert_problem(bad, "invalid_spec", 422)


def test_seal_and_self_test_failure(client: TestClient) -> None:
    response = client.post("/api/v1/seal", json={"spec": SPEC, "event_map": None})
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert "id: no-double-charge" in response.json()["spec_yaml"]
    failing = {
        **RULE,
        "confirmed_examples": [
            {"timeline": [{"event": "charged"}, {"event": "charged"}], "violation": False}
        ],
    }
    response = client.post("/api/v1/seal", json={"spec": {"version": 1, "rules": [failing]}})
    assert_problem(response, "compile_failed", 422)
    assert response.json()["ok"] is False
    assert response.json()["failures"][0]["rule_id"] == RULE["id"]


def test_runs_naive_fixed_and_unknown(client: TestClient) -> None:
    for scenario_id, expected in (
        ("payment_timeout_naive", "violation"),
        ("payment_timeout_fixed", "pass"),
    ):
        response = client.post("/api/v1/runs", json={"spec": SPEC, "scenario_id": scenario_id})
        assert response.status_code == 200
        body = response.json()
        assert body["events"]
        assert body["report"]["results"][0]["status"] == expected
    unknown = client.post("/api/v1/runs", json={"spec": SPEC, "scenario_id": "missing"})
    assert_problem(unknown, "unknown_scenario", 404)


def test_explain(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        routes,
        "explain_violation",
        lambda rule, violation, *, client: Explanation(text="Two charges.", cached=True),
    )
    event = {"event": "charged", "ts": datetime.now(UTC).isoformat(), "data": {"order_id": "A-1"}}
    violation = Violation(
        rule_id=RULE["id"],
        entity="A-1",
        message="charged twice",
        timeline=[event],
        offending_index=0,
    )
    response = client.post(
        "/api/v1/explain", json={"rule": RULE, "violation": violation.model_dump(mode="json")}
    )
    assert response.status_code == 200
    assert response.json() == {"text": "Two charges.", "advisory": True, "cached": True}


def test_errors_and_internal_redaction(client: TestClient, monkeypatch) -> None:
    assert_problem(client.post("/api/v1/clarify", json={"rules": [" "]}), "invalid_request", 422)

    def quota(*args, **kwargs):
        raise GeminiQuotaError("quota reached", per_day=True)

    monkeypatch.setattr(routes, "clarify", quota)
    assert_problem(client.post("/api/v1/clarify", json={"rules": ["one"]}), "gemini_quota", 429)

    def unavailable(*args, **kwargs):
        raise GeminiUnavailable("service down")

    monkeypatch.setattr(routes, "clarify", unavailable)
    assert_problem(
        client.post("/api/v1/clarify", json={"rules": ["one"]}), "gemini_unavailable", 503
    )

    def unexpected(*args, **kwargs):
        raise RuntimeError("secret stack detail")

    monkeypatch.setattr(routes, "clarify", unexpected)
    response = client.post("/api/v1/clarify", json={"rules": ["one"]})
    assert_problem(response, "internal_error", 500)
    assert "secret stack detail" not in response.text


def test_static_spa_does_not_shadow_api(tmp_path, monkeypatch) -> None:
    (tmp_path / "index.html").write_text("frontend", encoding="utf-8")
    monkeypatch.setattr(api_main, "DIST_DIR", tmp_path)
    app = create_app()
    browser = TestClient(app, raise_server_exceptions=False)
    assert browser.get("/nested/route").text == "frontend"
    assert browser.get("/api/v1/scenarios").status_code == 200
    assert browser.get("/api/v1/missing").status_code == 404


def test_traces_summary_and_invalid_upload(client: TestClient) -> None:
    events = [
        {
            "event": "charged",
            "ts": "2026-01-01T00:00:00Z",
            "data": {"order_id": "A", "kind": "card"},
        }
    ]
    response = client.post(
        "/api/v1/traces", json={"events": events, "extra_events": ["payroll_run", "charged"]}
    )
    assert response.status_code == 200
    assert response.json()["summary"]["vocabulary"] == {
        "events": ["charged", "payroll_run"],
        "fields": ["kind", "order_id"],
        "field_values": {"kind": ["card"]},
    }
    assert response.json()["summary"]["event_counts"] == {"charged": 1}
    assert_problem(client.post("/api/v1/traces", json={"events": [{}]}), "invalid_events", 422)
    oversized = client.post("/api/v1/traces", content=b" " * 5_000_001)
    assert_problem(oversized, "invalid_request", 422)


def test_runs_uploaded_events_and_exactly_one_source(client: TestClient) -> None:
    events = [
        {"event": "charged", "ts": "2026-01-01T00:00:00Z", "data": {"order_id": "A"}},
        {"event": "charged", "ts": "2026-01-01T00:00:01Z", "data": {"order_id": "A"}},
    ]
    response = client.post("/api/v1/runs", json={"spec": SPEC, "events": events})
    assert response.status_code == 200
    assert response.json()["report"]["results"][0]["status"] == "violation"
    for payload in ({"spec": SPEC}, {"spec": SPEC, "events": events, "scenario_id": "x"}):
        assert_problem(client.post("/api/v1/runs", json=payload), "invalid_request", 422)
    assert_problem(
        client.post("/api/v1/runs", json={"spec": SPEC, "events": [{}]}),
        "invalid_events",
        422,
    )
    oversized = client.post("/api/v1/runs", content=b" " * 5_000_001)
    assert_problem(oversized, "invalid_request", 422)
