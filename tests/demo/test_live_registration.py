"""Shared MCP tool registration keeps separate shop worlds and call histories."""

from __future__ import annotations

import asyncio
from datetime import UTC

from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session

from haqwa.live.server import ShopState, register_tools


async def _exercise_separate_shops() -> None:
    first = ShopState("timeout_after_commit")
    second = ShopState("timeout_after_commit")
    active = first
    mcp = FastMCP("shop registration test", json_response=True)
    register_tools(mcp, "timeout_after_commit", lambda _ctx: active)

    async with create_connected_server_and_client_session(mcp) as session:
        tools = {tool.name: tool for tool in (await session.list_tools()).tools}
        assert set(tools) == {"create_order", "charge_payment"}
        assert set(tools["create_order"].inputSchema["properties"]) == {"order_id", "amount"}
        assert set(tools["charge_payment"].inputSchema["properties"]) == {
            "order_id",
            "amount",
            "idempotency_key",
        }
        await session.call_tool("create_order", {"order_id": "A-1", "amount": 50})
        failed = await session.call_tool("charge_payment", {"order_id": "A-1", "amount": 50})
        assert failed.isError
        assert "Request timed out" in str(failed.content)

        active = second
        await session.call_tool("create_order", {"order_id": "B-1", "amount": 20})

    assert [call["tool"] for call in first.calls] == ["create_order", "charge_payment"]
    assert first.calls[0]["ok"] is True
    assert first.calls[1]["ok"] is False
    assert first.calls[1]["error"] == "Request timed out"
    assert first.calls[1]["at"].tzinfo is UTC
    assert [call["tool"] for call in second.calls] == ["create_order"]
    assert first.effects() != second.effects()
    first.reset()
    assert first.calls == []
    assert second.calls != []


def test_shared_tools_resolve_separate_shops() -> None:
    asyncio.run(_exercise_separate_shops())
