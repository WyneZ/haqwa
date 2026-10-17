"""C3 API contract checks without Gemini or network access."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from haqwa.ai.clarify_v2 import ClarifyV2Outcome, Decision
from haqwa.ai.client import GeminiBadOutput, GeminiClient, GeminiQuotaError, GeminiUnavailable
from haqwa.ai.core_v2_ports import CoreV2Ports
from haqwa.ai.explain import Explanation
from haqwa.ai.parse_v2 import ParseV2Outcome
from haqwa.ai.render_v2 import render_rule
from haqwa.core.canonical import CanonicalExample
from haqwa.core.report import Violation
from haqwa.core.rules_v2 import RuleV2
from haqwa.core.spec import TimelineEvent
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
V2_RULE = {
    "id": "no-double-charge",
    "source": RULE["source"],
    "version": 2,
    "per": "order_id",
    "root": "check",
    "nodes": [
        {"id": "charges", "type": "select", "event": "charged"},
        {"id": "check", "type": "count", "of": "charges", "op": "le", "value": 1},
    ],
}
RESET_PATCH = {"op": "add_reset", "node_id": "check", "event": "refunded"}
DECISION = {
    "id": "d1",
    "kind": "decision",
    "text": "Is a new charge allowed after a refund?",
    "why": "Refunding can allow charging again.",
    "patch": RESET_PATCH,
    "timeline": [{"event": "charged"}, {"event": "refunded"}, {"event": "charged"}],
}


def fake_ports() -> CoreV2Ports:
    """Supply deterministic test ports without importing future Track B functions."""
    example = CanonicalExample(
        label="Two charges",
        timeline=(TimelineEvent(event="charged"),) * 2,
        violation=True,
    )

    def apply_patch(rule, patch):
        rule.nodes[-1].since.append(patch.event)
        return rule

    return CoreV2Ports(
        apply_patch=apply_patch,
        canonical_examples=lambda _: [example],
        make_example=lambda *_: example,
    )


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

    def fake_parse(source, *, rule_id, vocab, client):
        ids.append(rule_id)
        if source == "unsupported":
            from haqwa.ai.parse import ParseError

            raise ParseError(["outside vocabulary"])
        rule = RuleV2.model_validate({**V2_RULE, "id": rule_id, "source": source})
        return ParseV2Outcome(source=source, status="supported", rule=rule, cached=True)

    def fake_propose(rule, *, vocab, client, make_example):
        return ClarifyV2Outcome(
            rule=rule,
            meaning=render_rule(rule),
            decisions=[
                Decision(
                    id="d1",
                    question=DECISION["text"],
                    why=DECISION["why"],
                    patch=RESET_PATCH,
                    example=make_example(rule, RESET_PATCH),
                )
            ],
            dropped=[],
            cached=True,
        )

    client.app.dependency_overrides[routes.get_core_v2_ports] = fake_ports
    monkeypatch.setattr(routes, "parse_v2", fake_parse)
    monkeypatch.setattr(routes, "propose_decisions", fake_propose)
    response = client.post(
        "/api/v1/clarify", json={"rules": ["Charge once", "Charge once", "unsupported"]}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["results"][0]["status"] == "supported"
    assert body["results"][0]["rule"]["id"] == ids[0]
    assert "dropped" not in body["results"][0]
    assert body["results"][1]["rule"]["id"] != ids[0]
    assert body["results"][0]["rule"]["version"] == 2
    assert body["results"][0]["meaning"]
    assert [q["id"] for q in body["results"][0]["questions"]] == ["c1", "d1"]
    assert body["results"][0]["questions"][1]["patch"] == RESET_PATCH
    assert body["results"][2]["status"] == "unsupported"
    assert body["results"][2]["rule"] is body["results"][2]["questions"] is None
    assert body["cached"] is False


def test_clarify_uses_optional_vocabulary_in_fake_client(client: TestClient) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        def generate(self, prompt, schema):
            self.prompts.append(prompt)
            return SimpleNamespace(
                value=schema.model_validate({"unsupported_reason": "outside the supported AST"}),
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
    assert "charged" not in fake.prompts[-1].split("This system:", 1)[1]
    assert client.post("/api/v1/clarify", json={"rules": payload["rules"]}).status_code == 200
    assert "charged" in fake.prompts[-1].split("This system:", 1)[1]


def test_clarify_rejects_invalid_vocabulary(client: TestClient) -> None:
    vocabulary = {"events": ["leave_requested"], "fields": ["leave_id"]}
    invalid = (
        {**vocabulary, "field_values": {"unknown": ["x"]}},
        {**vocabulary, "events": []},
        {**vocabulary, "events": ["leave requested"]},
        {**vocabulary, "field_values": {"leave_id": ["x"] * 51}},
        {**vocabulary, "numeric_fields": ["unknown"]},
        {**vocabulary, "numeric_fields": ["leave_id"], "field_values": {"leave_id": ["x"]}},
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
        json={"rule": V2_RULE, "answers": [{"question": question, "allowed": False}]},
    )
    assert response.status_code == 200
    assert response.json()["confirmed_examples"][0]["violation"] is True
    # B2: the rule carries the same confirmed examples that seal will self-test.
    assert response.json()["rule"]["confirmed_examples"] == response.json()["confirmed_examples"]
    assert response.json()["mismatches"] == []
    bad = client.post("/api/v1/answers", json={"rule": {"pattern": "wrong"}, "answers": []})
    assert_problem(bad, "invalid_spec", 422)


def test_answers_yes_uses_injected_port(client: TestClient) -> None:
    client.app.dependency_overrides[routes.get_core_v2_ports] = fake_ports
    response = client.post(
        "/api/v1/answers",
        json={
            "rule": V2_RULE,
            "answers": [{"question": DECISION, "allowed": True}],
        },
    )
    assert response.status_code == 200
    assert response.json()["rule"]["nodes"][-1]["since"] == ["refunded"]
    assert response.json()["confirmed_examples"][0]["violation"] is False
    # The owner sees what will really be enforced after the Yes patch.
    assert "starts again after each refunded event" in response.json()["meaning"]


def test_answers_yes_uses_real_core_patch(client: TestClient) -> None:
    # No port override: the app's default ports are Track B's core functions.
    response = client.post(
        "/api/v1/answers",
        json={
            "rule": V2_RULE,
            "answers": [{"question": DECISION, "allowed": True}],
        },
    )
    assert response.status_code == 200
    assert response.json()["rule"]["nodes"][-1]["since"] == ["refunded"]
    assert "starts again after each refunded event" in response.json()["meaning"]
    response = client.post(
        "/api/v1/answers",
        json={
            "rule": V2_RULE,
            "answers": [{"question": DECISION, "allowed": False}],
        },
    )
    assert response.status_code == 200
    assert response.json()["confirmed_examples"][0]["violation"] is True


@pytest.mark.parametrize(
    "question",
    [
        {**DECISION, "patch": None},
        {**DECISION, "expected_violation": True},
        {
            "id": "c1",
            "kind": "confirmation",
            "text": "Is this allowed?",
            "timeline": [{"event": "charged"}],
        },
    ],
)
def test_answers_rejects_bad_question_body(client: TestClient, question) -> None:
    response = client.post(
        "/api/v1/answers",
        json={
            "rule": V2_RULE,
            "answers": [{"question": question, "allowed": False}],
        },
    )
    assert_problem(response, "invalid_request", 422)


def test_answers_invalid_patched_rule_is_422(client: TestClient) -> None:
    ports = fake_ports()
    client.app.dependency_overrides[routes.get_core_v2_ports] = lambda: CoreV2Ports(
        apply_patch=lambda r, p: r.model_copy(update={"root": "missing"}),
        canonical_examples=ports.canonical_examples,
        make_example=ports.make_example,
    )
    response = client.post(
        "/api/v1/answers",
        json={
            "rule": V2_RULE,
            "answers": [{"question": DECISION, "allowed": True}],
        },
    )
    assert_problem(response, "invalid_spec", 422)


def test_answers_rejects_client_patch_outside_closed_values(client: TestClient) -> None:
    calls = []
    ports = fake_ports()

    def apply_patch(rule, patch):
        calls.append(patch)
        return rule

    client.app.dependency_overrides[routes.get_core_v2_ports] = lambda: CoreV2Ports(
        apply_patch=apply_patch,
        canonical_examples=ports.canonical_examples,
        make_example=ports.make_example,
    )
    forged = {
        **DECISION,
        "patch": {
            "op": "add_exclude",
            "select_ids": ["charges"],
            "condition": {"field": "order_id", "op": "eq", "value": "o-1"},
        },
    }
    response = client.post(
        "/api/v1/answers",
        json={"rule": V2_RULE, "answers": [{"question": forged, "allowed": True}]},
    )
    assert_problem(response, "invalid_spec", 422)
    assert calls == []


def test_answers_accepts_custom_vocabulary(client: TestClient) -> None:
    custom_rule = {
        **V2_RULE,
        "per": "employee_id",
        "nodes": [
            {"id": "charges", "type": "select", "event": "payroll_run"},
            V2_RULE["nodes"][-1],
        ],
    }
    payload = {
        "rule": custom_rule,
        "answers": [],
        "vocabulary": {
            "events": ["payroll_run"],
            "fields": ["employee_id"],
            "numeric_fields": [],
        },
    }
    response = client.post("/api/v1/answers", json=payload)
    assert response.status_code == 200
    assert response.json()["rule"]["per"] == "employee_id"
    payload["vocabulary"]["numeric_fields"] = ["missing"]
    assert_problem(client.post("/api/v1/answers", json=payload), "invalid_request", 422)


def test_answers_returns_confirmation_mismatch_without_recording(client: TestClient) -> None:
    question = {
        "id": "c1",
        "kind": "confirmation",
        "text": "Is this allowed?",
        "timeline": [{"event": "charged"}, {"event": "charged"}],
        "expected_violation": True,
    }
    response = client.post(
        "/api/v1/answers",
        json={
            "rule": V2_RULE,
            "answers": [{"question": question, "allowed": True}],
        },
    )
    assert response.status_code == 200
    assert response.json()["confirmed_examples"] == []
    assert response.json()["mismatches"] == ["c1: owner answered the opposite of 'not allowed'"]


def test_cached_unsupported_parse_does_not_call_clarify(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        routes,
        "parse_v2",
        lambda source, **_: ParseV2Outcome(
            source=source,
            status="unsupported",
            reason="No exact AST",
            cached=True,
        ),
    )

    def forbidden(*args, **kwargs):
        pytest.fail("An unsupported parse must not ask for decision proposals")

    monkeypatch.setattr(routes, "propose_decisions", forbidden)
    response = client.post("/api/v1/clarify", json={"rules": ["Unsupported"]})
    assert response.status_code == 200
    assert response.json()["cached"] is True
    result = response.json()["results"][0]
    assert result["rule"] is result["meaning"] is result["questions"] is None
    assert result["reason"] == "No exact AST"


@pytest.mark.parametrize(
    "parse_cached,clarify_cached",
    [
        (False, False),
        (False, True),
        (True, False),
        (True, True),
    ],
)
def test_clarify_cache_flag_requires_both_stages(
    client: TestClient, monkeypatch, parse_cached, clarify_cached
) -> None:
    original = RuleV2.model_validate(V2_RULE)
    monkeypatch.setattr(
        routes,
        "parse_v2",
        lambda source, **kwargs: ParseV2Outcome(
            source=source,
            status="supported",
            rule=original,
            cached=parse_cached,
        ),
    )
    monkeypatch.setattr(
        routes,
        "propose_decisions",
        lambda rule, **kwargs: ClarifyV2Outcome(
            rule=rule,
            meaning=render_rule(rule),
            decisions=[],
            dropped=[],
            cached=clarify_cached,
        ),
    )
    response = client.post("/api/v1/clarify", json={"rules": ["One charge"]})
    assert response.status_code == 200
    assert response.json()["cached"] is (parse_cached and clarify_cached)


@pytest.mark.parametrize("stage", ["parse_v2", "propose_decisions"])
def test_clarify_bad_gemini_output_is_item_unsupported(
    client: TestClient, monkeypatch, stage
) -> None:
    monkeypatch.setattr(
        routes,
        "parse_v2",
        lambda source, **_: ParseV2Outcome(
            source=source,
            status="supported",
            rule=RuleV2.model_validate(V2_RULE),
            cached=True,
        ),
    )

    def fail(*args, **kwargs):
        raise GeminiBadOutput("bad structured output")

    monkeypatch.setattr(routes, stage, fail)
    response = client.post("/api/v1/clarify", json={"rules": ["One charge"]})
    assert response.status_code == 200
    assert response.json()["results"][0]["status"] == "unsupported"
    assert response.json()["cached"] is False


def test_clarify_numeric_fields_and_real_fake_sdk_flow(client: TestClient, tmp_path) -> None:
    import json

    class FakeSDK:
        def __init__(self):
            self.models = self
            self.calls = 0

        def generate_content(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                answer = {
                    "per": "order_id",
                    "root": "check",
                    "nodes": [
                        {
                            "id": "charges",
                            "type": "select",
                            "event": "charged",
                            "where": [{"field": "amount", "op": "gt", "value": "1000"}],
                        },
                        V2_RULE["nodes"][-1],
                    ],
                }
            else:
                answer = {"decisions": []}
            return SimpleNamespace(text=json.dumps(answer))

    sdk = FakeSDK()
    gemini = GeminiClient(model="test", sdk=sdk, cache_dir=tmp_path)
    client.app.dependency_overrides[routes.get_client] = lambda: gemini
    payload = {
        "rules": ["At most one charge above 1000"],
        "vocabulary": {
            "events": ["charged"],
            "fields": ["order_id", "amount"],
            "numeric_fields": ["amount"],
        },
    }
    first = client.post("/api/v1/clarify", json=payload)
    assert first.status_code == 200
    assert first.json()["results"][0]["status"] == "supported"
    assert first.json()["cached"] is False
    assert client.post("/api/v1/clarify", json=payload).json()["cached"] is True
    # Parse only: with one event and no closed values no change can matter, so code
    # finds no candidate decisions and clarify does not call Gemini at all.
    assert sdk.calls == 1


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


V2_SPEC_RULE = {
    **V2_RULE,
    "source": "A customer must not be charged twice for the same order.",
    "nodes": [
        {"id": "charges", "type": "select", "event": "charged"},
        {"id": "check", "type": "count", "of": "charges", "op": "le", "value": 1,
         "since": ["refunded"]},
    ],
    "confirmed_examples": [
        {"timeline": [{"event": "charged"}, {"event": "charged"}], "violation": True},
        {
            "timeline": [{"event": "charged"}, {"event": "refunded"}, {"event": "charged"}],
            "violation": False,
        },
    ],
}  # fmt: skip


def test_seal_v2_spec_self_tests_confirmed_examples(client: TestClient) -> None:
    # What the v2 UI sends after the interview: version 2, examples inside each rule.
    response = client.post("/api/v1/seal", json={"spec": {"version": 2, "rules": [V2_SPEC_RULE]}})
    assert response.status_code == 200
    assert response.json()["spec_yaml"].startswith("version: 2")
    wrong = {**V2_SPEC_RULE, "confirmed_examples": [{**V2_SPEC_RULE["confirmed_examples"][0],
                                                     "violation": False}]}  # fmt: skip
    response = client.post("/api/v1/seal", json={"spec": {"version": 2, "rules": [wrong]}})
    assert_problem(response, "compile_failed", 422)
    assert response.json()["failures"][0]["rule_id"] == V2_SPEC_RULE["id"]


def test_runs_v2_spec_on_demo_scenario(client: TestClient) -> None:
    spec = {"version": 2, "rules": [V2_SPEC_RULE]}
    for scenario_id, expected in (
        ("payment_timeout_naive", "violation"),
        ("payment_timeout_fixed", "pass"),
    ):
        response = client.post("/api/v1/runs", json={"spec": spec, "scenario_id": scenario_id})
        assert response.status_code == 200
        assert response.json()["report"]["results"][0]["status"] == expected


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
        "/api/v1/explain", json={"rule": V2_RULE, "violation": violation.model_dump(mode="json")}
    )
    assert response.status_code == 200
    assert response.json() == {"text": "Two charges.", "advisory": True, "cached": True}


def test_errors_and_internal_redaction(client: TestClient, monkeypatch) -> None:
    assert_problem(client.post("/api/v1/clarify", json={"rules": [" "]}), "invalid_request", 422)

    def quota(*args, **kwargs):
        raise GeminiQuotaError("quota reached", per_day=True)

    monkeypatch.setattr(routes, "parse_v2", quota)
    assert_problem(client.post("/api/v1/clarify", json={"rules": ["one"]}), "gemini_quota", 429)

    def unavailable(*args, **kwargs):
        raise GeminiUnavailable("service down")

    monkeypatch.setattr(routes, "parse_v2", unavailable)
    assert_problem(
        client.post("/api/v1/clarify", json={"rules": ["one"]}), "gemini_unavailable", 503
    )

    def unexpected(*args, **kwargs):
        raise RuntimeError("secret stack detail")

    monkeypatch.setattr(routes, "parse_v2", unexpected)
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
