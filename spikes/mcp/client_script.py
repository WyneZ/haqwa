"""No LLM/key required. Prove MCP tools, fault, effects, and both Haqwa verdicts.

Start server.py in another terminal, then run this script.
"""

from __future__ import annotations

import asyncio

from common import URL, value, verdict
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def call(session: ClientSession, name: str, **arguments):
    result = value(await session.call_tool(name, arguments))
    print(f"  {name}({arguments}) -> {result}")
    return result


async def scenario(session: ClientSession, *, key: str | None) -> None:
    label = "with key" if key else "naive"
    print(f"\n=== {label}")
    await call(session, "reset_shop")
    await call(session, "create_order", order_id="A-1", amount=50)
    args = {"order_id": "A-1", "amount": 50}
    if key:
        args["idempotency_key"] = key
    first = await call(session, "charge_payment", **args)
    assert "timeout_after_commit" in first.get("error", ""), first
    second = await call(session, "charge_payment", **args)
    assert second.get("status") == "captured", second
    effects = await call(session, "list_effects")
    events, report = verdict(effects)
    charged = [event for event in events if event.event == "charged"]
    rule = next(rule for rule in report.results if rule.rule_id == "no-double-charge")
    expected = "pass" if key else "violation"
    assert rule.status == expected, rule
    assert len(charged) == (1 if key else 2), charged
    print(f"  charged effects: {len(charged)}; no-double-charge: {rule.status}")


async def main() -> None:
    async with streamable_http_client(URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = sorted(tool.name for tool in tools.tools)
            print("MCP tools:", names)
            assert {"create_order", "charge_payment"} <= set(names)
            await scenario(session, key=None)
            await scenario(session, key="payment-A-1")


if __name__ == "__main__":
    asyncio.run(main())
