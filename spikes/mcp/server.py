"""Haqwa shop over MCP. Run from the repository root:

    .venv/bin/python spikes/mcp/server.py

The first charge in each fresh shop commits, then reports a simulated timeout.
The fault lives in this MCP layer, after AgentProof records the effect.
"""

from __future__ import annotations

from agentproof import World
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from haqwa.demo.shop import setup_shop

HOST = "127.0.0.1"
PORT = 8765
mcp = FastMCP("Haqwa shop spike", host=HOST, port=PORT, json_response=True)
world: World
fault_pending: bool


def fresh_shop() -> None:
    global world, fault_pending
    world = World()
    setup_shop(world)
    fault_pending = True


fresh_shop()


@mcp.tool()
async def create_order(order_id: str, amount: int) -> dict:
    """Create a shop order for the given amount."""
    return await world.tools.invoke("create_order", {"order_id": order_id, "amount": amount})


@mcp.tool()
async def charge_payment(order_id: str, amount: int, idempotency_key: str | None = None) -> dict:
    """Charge an order. An idempotency key makes a retry safe."""
    global fault_pending
    arguments = {"order_id": order_id, "amount": amount}
    if idempotency_key is not None:
        arguments["idempotency_key"] = idempotency_key
    result = await world.tools.invoke("charge_payment", arguments)
    if fault_pending:
        fault_pending = False
        raise ToolError("timeout_after_commit: payment committed; response timed out")
    return result


@mcp.tool()
def list_effects() -> list[dict]:
    """Read committed shop effects for the spike's verdict."""
    return [
        {"id": effect.id, "type": effect.type, "data": effect.data,
         "committed_at": effect.committed_at}
        for effect in world.effects.all()
    ]


@mcp.tool()
def reset_shop() -> dict:
    """Start a fresh shop and rearm the first-charge timeout."""
    fresh_shop()
    return {"status": "reset", "fault": "timeout_after_commit on first charge"}


if __name__ == "__main__":
    print(f"Haqwa MCP shop: http://{HOST}:{PORT}/mcp", flush=True)
    mcp.run(transport="streamable-http")
