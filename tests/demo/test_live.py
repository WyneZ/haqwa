"""Live MCP behavior with an in-process client, without Gemini or network."""

from __future__ import annotations

import asyncio
from pathlib import Path

from mcp.shared.memory import create_connected_server_and_client_session
from typer.testing import CliRunner

from haqwa.cli import app
from haqwa.demo.scenarios import _recording_title
from haqwa.live.cli import next_recording_path
from haqwa.live.report import verdict
from haqwa.live.server import build_server


async def _timeout_session(safe: bool) -> None:
    shop = build_server("timeout_after_commit")
    async with create_connected_server_and_client_session(shop.mcp) as session:
        names = {tool.name for tool in (await session.list_tools()).tools}
        assert names == {"create_order", "charge_payment"}
        await session.call_tool("create_order", {"order_id": "A-1", "amount": 50})
        args = {"order_id": "A-1", "amount": 50}
        if safe:
            args["idempotency_key"] = "charge-A-1"
        first = await session.call_tool("charge_payment", args)
        assert first.isError
        assert "Request timed out" in str(first.content)
        await session.call_tool("charge_payment", args)
    assert verdict(shop.effects())[1].passed is safe


async def _stale_session(safe: bool) -> None:
    shop = build_server("stale_state")
    async with create_connected_server_and_client_session(shop.mcp) as session:
        names = {tool.name for tool in (await session.list_tools()).tools}
        assert names == {"get_order", "ship_order"}
        read = await session.call_tool("get_order", {"order_id": "A-1"})
        assert "paid" in str(read.content)
        args = {"order_id": "A-1"}
        if safe:
            args["if_status"] = "paid"
        await session.call_tool("ship_order", args)
    assert verdict(shop.effects())[1].passed is safe


def test_timeout_naive_and_safe() -> None:
    asyncio.run(_timeout_session(False))
    asyncio.run(_timeout_session(True))


def test_stale_naive_and_safe() -> None:
    asyncio.run(_stale_session(False))
    asyncio.run(_stale_session(True))


def test_missing_key_exits_without_recording(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["live", "run", "--fault", "stale_state"])
    assert result.exit_code == 4
    assert "Set GEMINI_API_KEY" in result.output
    assert list(tmp_path.iterdir()) == []


def test_bad_live_options_exit_three() -> None:
    runner = CliRunner()
    assert runner.invoke(app, ["live", "run", "--fault", "unknown"]).exit_code == 3
    assert (
        runner.invoke(app, ["live", "run", "--fault", "stale_state", "--runs", "0"]).exit_code == 3
    )
    assert (
        runner.invoke(app, ["live", "serve", "--fault", "stale_state", "--port", "0"]).exit_code
        == 3
    )


def test_recording_names_and_titles(tmp_path: Path) -> None:
    first = next_recording_path("timeout_after_commit", tmp_path)
    assert "gemini_live_timeout_run_1_" in first.name
    first.touch()
    second = next_recording_path("timeout_after_commit", tmp_path)
    assert "gemini_live_timeout_run_2_" in second.name
    assert _recording_title("gemini_live_timeout_run_2_2026_10_11") == (
        "Live Gemini agent over MCP — payment timeout — run 2 (2026-10-11)"
    )
    assert _recording_title("gemini_live_stale_run_1_2026_10_11") == (
        "Live Gemini agent over MCP — stale order status — run 1 (2026-10-11)"
    )
