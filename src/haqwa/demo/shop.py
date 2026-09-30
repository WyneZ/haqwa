"""A tiny virtual shop inside an AgentProof world. Every side effect goes to the effect ledger.

Tools: create_order, charge_payment (optional idempotency_key), request_charge (queue),
process_queue (consumer, optional dedupe by message id), refund.
"""

from __future__ import annotations

from typing import Any

from agentproof.tools.definition import ToolOutcome

ORDER = {
    "type": "object",
    "properties": {
        "order_id": {"type": "string"},
        "amount": {"type": "integer"},
        "idempotency_key": {"type": "string"},
    },
    "required": ["order_id", "amount"],
}
QUEUE = {"type": "object", "properties": {"dedupe": {"type": "boolean"}}}
REFUND = {
    "type": "object",
    "properties": {"order_id": {"type": "string"}},
    "required": ["order_id"],
}


def setup_shop(world: Any) -> None:
    """Register the shop tools on an AgentProof world."""
    state = world.state

    def create_order(order_id: str, amount: int, idempotency_key: str | None = None):
        return ToolOutcome(
            value={"order_id": order_id},
            effects=[{"type": "order_created", "data": {"order_id": order_id, "amount": amount}}],
        )

    def charge_payment(order_id: str, amount: int, idempotency_key: str | None = None):
        # Like a real payment API: a repeated idempotency key returns the first result
        # and does not charge again.
        seen = state.get("idempotency_keys", {})
        if idempotency_key and idempotency_key in seen:
            return seen[idempotency_key]
        result = ToolOutcome(
            value={"status": "captured"},
            effects=[{"type": "charged", "data": {"order_id": order_id, "amount": amount}}],
        )
        if idempotency_key:
            state["idempotency_keys"] = {**seen, idempotency_key: {"status": "captured"}}
        return result

    def request_charge(order_id: str, amount: int, idempotency_key: str | None = None):
        world.events.schedule(
            name="charge_requested", payload={"order_id": order_id, "amount": amount}
        )
        return {"status": "queued"}

    def process_queue(dedupe: bool = False):
        done = set(state.get("processed_messages", []))
        effects = []
        for msg in world.events.deliver_due():
            if msg.name != "charge_requested":
                continue
            # DuplicateEvent re-delivers with ids like "event_001_dup_1".
            original_id = msg.id.split("_dup_")[0]
            if dedupe and original_id in done:
                continue
            done.add(original_id)
            effects.append({"type": "charged", "data": dict(msg.payload)})
        state["processed_messages"] = sorted(done)
        return ToolOutcome(value={"processed": len(effects)}, effects=effects)

    def refund(order_id: str):
        return ToolOutcome(
            value={"status": "refunded"},
            effects=[{"type": "refunded", "data": {"order_id": order_id}}],
        )

    reg = world.tools.register
    reg(
        name="create_order",
        description="Create an order",
        input_schema=ORDER,
        handler=create_order,
        effect="write",
    )
    reg(
        name="charge_payment",
        description="Charge the customer's card for an order",
        input_schema=ORDER,
        handler=charge_payment,
        effect="financial",
        idempotent=False,
    )
    reg(
        name="request_charge",
        description="Queue a charge request",
        input_schema=ORDER,
        handler=request_charge,
        effect="external",
    )
    reg(
        name="process_queue",
        description="Process queued charge requests",
        input_schema=QUEUE,
        handler=process_queue,
        effect="financial",
    )
    reg(
        name="refund",
        description="Refund an order",
        input_schema=REFUND,
        handler=refund,
        effect="financial",
    )
