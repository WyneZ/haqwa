"""Agent sessions exercised through the API and in-process Streamable HTTP MCP."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from web.api.main import create_app
from web.api.rate_limit import RateLimiter

SPEC = {
    "version": 1,
    "rules": [
        {
            "id": "no-double-charge",
            "source": "Do not charge an order twice.",
            "pattern": "at_most_once",
            "event": "charged",
            "per": "order_id",
        },
        {
            "id": "never-ship-after-cancel",
            "source": "Never ship an order after cancellation.",
            "pattern": "never_after",
            "event": "shipped",
            "after": "cancelled",
            "per": "order_id",
        },
    ],
}


@asynccontextmanager
async def running_client(app, *, base_url: str = "https://cloud-run.example"):
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=base_url
        ) as client:
            yield client


@asynccontextmanager
async def mcp_session(client: httpx.AsyncClient, url: str):
    async with streamable_http_client(url, http_client=client) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def create(client: httpx.AsyncClient, fault: str) -> dict:
    response = await client.post("/api/v1/agent-sessions", json={"fault": fault})
    assert response.status_code == 200, response.text
    return response.json()


async def _journeys() -> None:
    app = create_app()
    async with running_client(app) as client:
        naive = await create(client, "timeout_after_commit")
        assert naive["mcp_url"].startswith("https://cloud-run.example/agent/timeout/mcp?session=")
        assert naive["task"]
        async with mcp_session(client, naive["mcp_url"]) as session:
            assert {tool.name for tool in (await session.list_tools()).tools} == {
                "create_order",
                "charge_payment",
            }
            await session.call_tool("create_order", {"order_id": "A-1", "amount": 50})
            failed = await session.call_tool("charge_payment", {"order_id": "A-1", "amount": 50})
            assert failed.isError
            assert "Request timed out" in str(failed.content)
            await session.call_tool("charge_payment", {"order_id": "A-1", "amount": 50})
        status = (await client.get(f"/api/v1/agent-sessions/{naive['session_id']}")).json()
        assert [call["tool"] for call in status["calls"]] == [
            "create_order",
            "charge_payment",
            "charge_payment",
        ]
        assert status["calls"][1]["ok"] is False
        assert status["calls"][1]["error"] == "Request timed out"
        assert status["calls"][1]["at"]
        verdict = await client.post(
            f"/api/v1/agent-sessions/{naive['session_id']}/check", json={"spec": SPEC}
        )
        assert verdict.status_code == 200
        results = verdict.json()["report"]["results"]
        assert [result["status"] for result in results] == ["violation", "pass"]
        assert sum(len(result["violations"]) for result in results) == 1

        safe = await create(client, "timeout_after_commit")
        assert (await client.get(f"/api/v1/agent-sessions/{safe['session_id']}")).json()[
            "calls"
        ] == []
        async with mcp_session(client, safe["mcp_url"]) as session:
            await session.call_tool("create_order", {"order_id": "A-1", "amount": 50})
            args = {"order_id": "A-1", "amount": 50, "idempotency_key": "charge-A-1"}
            assert (await session.call_tool("charge_payment", args)).isError
            assert not (await session.call_tool("charge_payment", args)).isError
        verdict = await client.post(
            f"/api/v1/agent-sessions/{safe['session_id']}/check", json={"spec": SPEC}
        )
        assert all(result["status"] == "pass" for result in verdict.json()["report"]["results"])
        assert len(verdict.json()["events"]) == 2
        assert (
            len((await client.get(f"/api/v1/agent-sessions/{naive['session_id']}")).json()["calls"])
            == 3
        )

        stale = await create(client, "stale_state")
        async with mcp_session(client, stale["mcp_url"]) as session:
            assert {tool.name for tool in (await session.list_tools()).tools} == {
                "get_order",
                "ship_order",
            }
            read = await session.call_tool("get_order", {"order_id": "A-1"})
            assert "paid" in str(read.content)
            await session.call_tool("ship_order", {"order_id": "A-1"})
        verdict = await client.post(
            f"/api/v1/agent-sessions/{stale['session_id']}/check", json={"spec": SPEC}
        )
        results = verdict.json()["report"]["results"]
        assert [result["status"] for result in results] == ["pass", "violation"]
        assert sum(len(result["violations"]) for result in results) == 1
        deleted = await client.delete(f"/api/v1/agent-sessions/{stale['session_id']}")
        assert deleted.status_code == 204
        missing = await client.get(f"/api/v1/agent-sessions/{stale['session_id']}")
        assert missing.status_code == 404
        assert missing.json()["code"] == "session_not_found"


def test_agent_journeys_and_isolation() -> None:
    asyncio.run(_journeys())


async def _unknown_expired_and_cap() -> None:
    app = create_app()
    now = [datetime(2026, 1, 1, tzinfo=UTC)]
    app.state.agent_sessions.clock = lambda: now[0]
    async with running_client(app) as client:
        unknown = await client.get("/api/v1/agent-sessions/unknown")
        assert unknown.status_code == 404
        assert unknown.json()["code"] == "session_not_found"
        assert (
            await client.post("/api/v1/agent-sessions/unknown/check", json={"spec": SPEC})
        ).json()["code"] == "session_not_found"
        async with mcp_session(
            client, "https://cloud-run.example/agent/timeout/mcp?session=unknown"
        ) as session:
            result = await session.call_tool("create_order", {"order_id": "A-1", "amount": 50})
            assert result.isError
            assert "Session not found or expired" in str(result.content)
        async with mcp_session(client, "https://cloud-run.example/agent/timeout/mcp") as session:
            result = await session.call_tool("create_order", {"order_id": "A-1", "amount": 50})
            assert result.isError
            assert "Session not found or expired" in str(result.content)

        active = await create(client, "timeout_after_commit")
        wrong_mount = "https://cloud-run.example/agent/stale/mcp?session=" + active["session_id"]
        async with mcp_session(client, wrong_mount) as session:
            result = await session.call_tool("get_order", {"order_id": "A-1"})
            assert result.isError
            assert "Session not found or expired" in str(result.content)
        async with mcp_session(client, active["mcp_url"]) as session:
            await session.call_tool("create_order", {"order_id": "A-1", "amount": 50})
            over_cap = await session.call_tool("create_order", {"order_id": "B-1", "amount": 20})
            assert over_cap.isError
            assert "Too many requests" in str(over_cap.content)
        assert (
            len(
                (await client.get(f"/api/v1/agent-sessions/{active['session_id']}")).json()["calls"]
            )
            == 1
        )
        other = await create(client, "timeout_after_commit")
        async with mcp_session(client, other["mcp_url"]) as session:
            result = await session.call_tool("create_order", {"order_id": "B-1", "amount": 20})
            assert not result.isError

        now[0] += timedelta(seconds=1801)
        expired = await client.get(f"/api/v1/agent-sessions/{active['session_id']}")
        assert expired.status_code == 404
        assert expired.json()["code"] == "session_not_found"
        async with mcp_session(client, active["mcp_url"]) as session:
            result = await session.call_tool("create_order", {"order_id": "A-1", "amount": 50})
            assert result.isError
            assert "Session not found or expired" in str(result.content)


def test_unknown_expired_and_tool_call_cap(monkeypatch) -> None:
    monkeypatch.setenv("HAQWA_AGENT_MAX_CALLS", "1")
    asyncio.run(_unknown_expired_and_cap())


async def _creation_limits_and_https() -> None:
    app = create_app()
    app.state.agent_sessions.max_sessions = 1
    async with running_client(app, base_url="http://cloud-run.example") as client:
        created = await client.post(
            "/api/v1/agent-sessions",
            json={"fault": "stale_state"},
            headers={"X-Forwarded-Proto": "https"},
        )
        assert created.status_code == 200
        assert created.json()["mcp_url"].startswith("https://cloud-run.example/")
        limited = await client.post(
            "/api/v1/agent-sessions", json={"fault": "timeout_after_commit"}
        )
        assert limited.status_code == 429
        assert limited.json()["code"] == "session_limit"
        assert (
            await client.delete(f"/api/v1/agent-sessions/{created.json()['session_id']}")
        ).status_code == 204

    app = create_app()
    app.state.agent_create_limiter = RateLimiter(per_minute=1, per_day=10)
    async with running_client(app) as client:
        assert (
            await client.post("/api/v1/agent-sessions", json={"fault": "stale_state"})
        ).status_code == 200
        limited = await client.post("/api/v1/agent-sessions", json={"fault": "stale_state"})
        assert limited.status_code == 429
        assert limited.json()["code"] == "rate_limited"


def test_creation_limits_and_forwarded_https() -> None:
    asyncio.run(_creation_limits_and_https())
