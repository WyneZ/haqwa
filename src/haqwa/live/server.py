"""Expose only business operations from an AgentProof shop over MCP."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Literal, TypedDict

from agentproof import World
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from haqwa.demo.shop import setup_shop

Fault = Literal["timeout_after_commit", "stale_state"]
logger = logging.getLogger(__name__)


class ToolCall(TypedDict):
    """One attempted shop operation, including its client-visible error if it failed."""

    tool: str
    arguments: dict
    ok: bool
    error: str | None
    at: datetime


class ShopState:
    """A private, replaceable AgentProof world for one shop session."""

    def __init__(self, fault: Fault) -> None:
        self.fault = fault
        self.calls: list[ToolCall] = []
        self.reset()

    def reset(self) -> None:
        """Start a fresh run and prepare the fault before any client connects."""
        self.calls.clear()
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

    def record_call(
        self, tool: str, arguments: dict, *, ok: bool, error: str | None = None
    ) -> None:
        """Keep a server-side record of an attempted tool call."""
        self.calls.append(
            {
                "tool": tool,
                "arguments": dict(arguments),
                "ok": ok,
                "error": error,
                "at": datetime.now(UTC),
            }
        )


async def _recorded(
    shop: ShopState, tool: str, arguments: dict, operation: Callable[[], Awaitable[dict]]
) -> dict:
    try:
        result = await operation()
    except Exception as exc:
        shop.record_call(tool, arguments, ok=False, error=str(exc))
        raise
    shop.record_call(tool, arguments, ok=True)
    return result


def register_tools(mcp: FastMCP, fault: Fault, resolve: Callable[[Context], ShopState]) -> None:
    """Register the same shop tools on an MCP server with a per-call shop resolver."""
    if fault == "timeout_after_commit":

        @mcp.tool()
        async def create_order(order_id: str, amount: int, ctx: Context) -> dict:
            """Create a shop order for the given amount."""
            shop = resolve(ctx)
            arguments = {"order_id": order_id, "amount": amount}
            return await _recorded(
                shop,
                "create_order",
                arguments,
                lambda: shop.world.tools.invoke("create_order", arguments),
            )

        @mcp.tool()
        async def charge_payment(
            order_id: str, amount: int, ctx: Context, idempotency_key: str | None = None
        ) -> dict:
            """Charge an order; an optional idempotency_key may be supplied."""
            shop = resolve(ctx)
            arguments = {"order_id": order_id, "amount": amount}
            if idempotency_key is not None:
                arguments["idempotency_key"] = idempotency_key

            async def charge() -> dict:
                result = await shop.world.tools.invoke("charge_payment", arguments)
                if shop.fault_pending:
                    shop.fault_pending = False
                    logger.warning("[fault] timeout_after_commit injected after commit")
                    raise ToolError("Request timed out")
                return result

            return await _recorded(shop, "charge_payment", arguments, charge)

    else:

        @mcp.tool()
        async def get_order(order_id: str, ctx: Context) -> dict:
            """Read an order's status."""
            shop = resolve(ctx)
            arguments = {"order_id": order_id}

            async def read() -> dict:
                if order_id == "A-1":
                    return {"order_id": order_id, "status": "paid"}
                return await shop.world.tools.invoke("get_order", arguments)

            return await _recorded(shop, "get_order", arguments, read)

        @mcp.tool()
        async def ship_order(order_id: str, ctx: Context, if_status: str | None = None) -> dict:
            """Ship an order, with an optional status condition."""
            shop = resolve(ctx)
            arguments = {"order_id": order_id}
            if if_status is not None:
                arguments["if_status"] = if_status
            return await _recorded(
                shop,
                "ship_order",
                arguments,
                lambda: shop.world.tools.invoke("ship_order", arguments),
            )


class LiveShop(ShopState):
    """One CLI MCP server with a private, replaceable AgentProof world."""

    def __init__(self, fault: Fault, port: int = 8765) -> None:
        super().__init__(fault)
        self.mcp = FastMCP("Haqwa live shop", host="127.0.0.1", port=port, json_response=True)
        register_tools(self.mcp, fault, lambda _ctx: self)


def build_server(fault: Fault, port: int = 8765) -> LiveShop:
    """Build a faulted shop and its MCP server."""
    if fault not in ("timeout_after_commit", "stale_state"):
        raise ValueError(f"Unknown live fault: {fault}")
    return LiveShop(fault, port)
