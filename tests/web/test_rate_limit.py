"""Rate limits on Gemini routes, using a fake clock and isolated app."""

from __future__ import annotations

from fastapi.testclient import TestClient

from web.api.config import get_settings
from web.api.main import create_app
from web.api.rate_limit import RateLimiter


def test_per_ip_and_unlimited_other_routes() -> None:
    now = [1000.0]
    app = create_app()
    app.state.rate_limiter = RateLimiter(per_minute=2, per_day=20, clock=lambda: now[0])
    client = TestClient(app, raise_server_exceptions=False)
    for _ in range(2):
        response = client.post("/api/v1/clarify", json={}, headers={"X-Forwarded-For": "a, proxy"})
        assert response.status_code == 422
    limited = client.post("/api/v1/explain", json={}, headers={"X-Forwarded-For": "a, proxy"})
    assert limited.status_code == 429
    assert limited.headers["content-type"].startswith("application/problem+json")
    assert limited.json()["code"] == "rate_limited"
    assert "60 seconds" in limited.json()["detail"]
    response = client.post("/api/v1/clarify", json={}, headers={"X-Forwarded-For": "b"})
    assert response.status_code == 422
    assert client.get("/api/v1/scenarios").status_code == 200
    assert client.post("/api/v1/answers", json={}).status_code == 422
    assert client.post("/api/v1/runs", json={}).status_code == 422
    now[0] += 60
    response = client.post("/api/v1/clarify", json={}, headers={"X-Forwarded-For": "a"})
    assert response.status_code == 422


def test_global_daily_limit() -> None:
    now = [0.0]
    app = create_app()
    app.state.rate_limiter = RateLimiter(per_minute=10, per_day=2, clock=lambda: now[0])
    client = TestClient(app, raise_server_exceptions=False)
    for ip in ("a", "b"):
        response = client.post("/api/v1/explain", json={}, headers={"X-Forwarded-For": ip})
        assert response.status_code == 422
    response = client.post("/api/v1/clarify", json={}, headers={"X-Forwarded-For": "c"})
    assert response.json()["code"] == "rate_limited"
    assert "86400 seconds" in response.json()["detail"]
    now[0] += 86400
    response = client.post("/api/v1/clarify", json={}, headers={"X-Forwarded-For": "c"})
    assert response.status_code == 422


def test_limits_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("HAQWA_RATE_PER_MIN", "4")
    monkeypatch.setenv("HAQWA_RATE_PER_DAY", "40")
    settings = get_settings()
    assert (settings.rate_per_min, settings.rate_per_day) == (4, 40)
