"""Expose only business operations from an AgentProof shop over MCP."""

from __future__ import annotations

import logging
from typing import Literal

from agentproof import World
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from haqwa.demo.shop import setup_shop

Fault = Literal["timeout_after_commit", "stale_state"]
logger = logging.getLogger(__name__)


class LiveShop:
    """One MCP server with a private, replaceable AgentProof world."""

    def __init__(self, fault: Fault, port: int = 8765) -> None:
        self.fault = fault
        self.mcp = FastMCP("Haqwa live shop", host="127.0.0.1", port=port, json_response=True)
        self.reset()
        self._register_tools()

    def reset(self) -> None:
        """Start a fresh run and prepare the fault before any client connects."""
        self.world = World()
        setup_shop(self.world)
        self.fault_pending = True
        if self.fault == "stale_state":
            self.world.state["order_status"] = {"A-1": "cancelled"}
            for index, (kind, data) in enumerate(
                (
                    ("order_created", {"order_id": "A-1", "amount": 50}),
                    ("charged", {"order_id": "A-1", "amount": 50}),
                    ("cancelled", {"order_id": "A-1"}),
                )
            ):
                self.world.effects.commit(
                    {"type": kind, "data": data},
                    tool_name="setup_shop",
                    invocation_id=f"setup_{index}",
                    committed_at=float(index),
                )
            self.world.clock.set(3.0)

    def effects(self) -> list:
        """Return committed effects without exposing the ledger over MCP."""
        return self.world.effects.all()

    def _register_tools(self) -> None:
        if self.fault == "timeout_after_commit":

            @self.mcp.tool()
            async def create_order(order_id: str, amount: int) -> dict:
                """Create a shop order for the given amount."""
                return await self.world.tools.invoke(
                    "create_order", {"order_id": order_id, "amount": amount}
                )

            @self.mcp.tool()
            async def charge_payment(
                order_id: str, amount: int, idempotency_key: str | None = None
            ) -> dict:
                """Charge an order; an optional idempotency_key may be supplied."""
                arguments = {"order_id": order_id, "amount": amount}
                if idempotency_key is not None:
                    arguments["idempotency_key"] = idempotency_key
                result = await self.world.tools.invoke("charge_payment", arguments)
                if self.fault_pending:
                    self.fault_pending = False
                    logger.warning("[fault] timeout_after_commit injected after commit")
                    raise ToolError("Request timed out")
                return result

        else:

            @self.mcp.tool()
            async def get_order(order_id: str) -> dict:
                """Read an order's status."""
                if order_id == "A-1":
                    return {"order_id": order_id, "status": "paid"}
                return await self.world.tools.invoke("get_order", {"order_id": order_id})

            @self.mcp.tool()
            async def ship_order(order_id: str, if_status: str | None = None) -> dict:
                """Ship an order, with an optional status condition."""
                arguments = {"order_id": order_id}
                if if_status is not None:
                    arguments["if_status"] = if_status
                return await self.world.tools.invoke("ship_order", arguments)


def build_server(fault: Fault, port: int = 8765) -> LiveShop:
    """Build a faulted shop and its MCP server."""
    if fault not in ("timeout_after_commit", "stale_state"):
        raise ValueError(f"Unknown live fault: {fault}")
    return LiveShop(fault, port)
