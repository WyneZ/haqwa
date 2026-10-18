"""HTTP contract for live event sessions."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from web.api.main import create_app
from web.api.rate_limit import RateLimiter

VOCABULARY = {
    "events": ["order_approved", "order_packed"],
    "fields": ["order_id"],
}
SPEC = {
    "version": 2,
    "rules": [
        {
            "id": "approval-before-packing",
            "source": "Pack an order only after approval.",
            "version": 2,
            "per": "order_id",
            "root": "check",
            "nodes": [
                {"id": "packed", "type": "select", "event": "order_packed"},
                {"id": "approved", "type": "select", "event": "order_approved"},
                {"id": "check", "type": "every_preceded_by", "of": "packed", "by": "approved"},
            ],
        }
    ],
}


def problem(response, code: str, status: int) -> None:
    assert response.status_code == status
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == code


def create(client: TestClient, vocabulary: dict | None = None) -> dict:
    body = {"kind": "events"}
    if vocabulary is not None:
        body["vocabulary"] = vocabulary
    response = client.post("/api/v1/agent-sessions", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_create_ingest_status_and_unknown_event() -> None:
    with TestClient(create_app(), base_url="http://cloud-run.example") as client:
        created = client.post(
            "/api/v1/agent-sessions",
            json={"kind": "events", "vocabulary": VOCABULARY},
            headers={"X-Forwarded-Proto": "https"},
        )
        assert created.status_code == 200, created.text
        data = created.json()
        assert set(data) == {"session_id", "kind", "ingest_url", "expires_at", "snippet"}
        assert data["kind"] == "events"
        url = data["ingest_url"]
        assert url == (
            f"https://cloud-run.example/api/v1/agent-sessions/{data['session_id']}/events"
        )
        assert len(data["snippet"].splitlines()) == 3
        assert url in data["snippet"]

        response = client.post(url, json={"event": "order_approved", "data": {"order_id": "A-1"}})
        assert response.json() == {"accepted": 1, "total": 1, "unknown_events": []}
        batch = [
            {"event": "order_packed", "ts": "2026-01-01T00:00:02Z", "data": {"order_id": "A-1"}},
            {"event": "custom_signal", "data": {"order_id": "A-1"}},
        ]
        response = client.post(url, json=batch)
        assert response.json() == {"accepted": 2, "total": 3, "unknown_events": ["custom_signal"]}
        status = client.get(f"/api/v1/agent-sessions/{data['session_id']}")
        assert status.status_code == 200
        body = status.json()
        assert body["kind"] == "events" and body["calls"] == []
        assert [event["event"] for event in body["events"]] == [
            "order_approved",
            "order_packed",
            "custom_signal",
        ]
        assert body["events"][0]["ts"].endswith("Z")


def test_invalid_large_and_shop_token_rejected_without_storing() -> None:
    with TestClient(create_app()) as client:
        data = create(client)
        url = data["ingest_url"]
        problem(client.post(url, json={"event": "x", "ts": None}), "invalid_events", 422)
        problem(client.post(url, json={"data": {}}), "invalid_events", 422)
        problem(client.post(url, content=b"not json"), "invalid_events", 422)
        problem(
            client.post(url, content=b" " * (256 * 1024 + 1)),
            "invalid_request",
            422,
        )
        assert client.get(f"/api/v1/agent-sessions/{data['session_id']}").json()["events"] == []

        shop = client.post("/api/v1/agent-sessions", json={"fault": "stale_state"}).json()
        problem(
            client.post(f"/api/v1/agent-sessions/{shop['session_id']}/events", json={"event": "x"}),
            "session_not_found",
            404,
        )


def test_event_creation_uses_existing_create_limiter() -> None:
    app = create_app()
    app.state.agent_create_limiter = RateLimiter(per_minute=1, per_day=10)
    with TestClient(app) as client:
        create(client)
        problem(
            client.post("/api/v1/agent-sessions", json={"fault": "stale_state"}),
            "rate_limited",
            429,
        )


def test_event_cap_is_atomic_and_rate_limit_is_per_session() -> None:
    with TestClient(create_app()) as client:
        first = create(client)
        second = create(client)
        event = {"event": "order_approved"}
        url = first["ingest_url"]
        response = client.post(url, json=[event] * 999)
        assert response.json() == {"accepted": 999, "total": 999}
        problem(client.post(url, json=[event, event]), "invalid_request", 422)
        status = client.get(f"/api/v1/agent-sessions/{first['session_id']}").json()
        assert len(status["events"]) == 999
        assert client.post(url, json=event).json()["total"] == 1000

        for _ in range(117):
            problem(client.post(url, json=event), "invalid_request", 422)
        problem(client.post(url, json=event), "rate_limited", 429)
        assert client.post(second["ingest_url"], json=event).json()["total"] == 1


def test_check_v2_uses_stored_events_and_core_ordering() -> None:
    with TestClient(create_app()) as client:
        bad = create(client, VOCABULARY)
        good = create(client, VOCABULARY)
        for session, events in (
            (bad, [("order_packed", 1), ("order_approved", 2)]),
            (good, [("order_packed", 2), ("order_approved", 1)]),
        ):
            payload = [
                {"event": name, "ts": f"2026-01-01T00:00:0{second}Z", "data": {"order_id": "A-1"}}
                for name, second in events
            ]
            assert client.post(session["ingest_url"], json=payload).status_code == 200
        bad_result = client.post(
            f"/api/v1/agent-sessions/{bad['session_id']}/check", json={"spec": SPEC}
        )
        good_result = client.post(
            f"/api/v1/agent-sessions/{good['session_id']}/check", json={"spec": SPEC}
        )
        assert bad_result.status_code == good_result.status_code == 200
        assert bad_result.json()["report"]["results"][0]["status"] == "violation"
        assert good_result.json()["report"]["results"][0]["status"] == "pass"


def test_expired_event_session_and_event_token_on_both_shop_mounts() -> None:
    app = create_app()
    now = [datetime(2026, 1, 1, tzinfo=UTC)]
    app.state.agent_sessions.clock = lambda: now[0]
    with TestClient(app, raise_server_exceptions=False) as client:
        data = create(client)
        token = data["session_id"]
        for mount in ("timeout", "stale"):
            url = f"/agent/{mount}/mcp?session={token}"
            problem(client.get(url), "session_not_found", 404)
            problem(
                client.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}),
                "session_not_found",
                404,
            )
        now[0] += timedelta(seconds=1800)
        problem(client.get(f"/api/v1/agent-sessions/{token}"), "session_not_found", 404)
        problem(client.post(data["ingest_url"], json={"event": "x"}), "session_not_found", 404)
        problem(
            client.post(f"/api/v1/agent-sessions/{token}/check", json={"spec": SPEC}),
            "session_not_found",
            404,
        )
