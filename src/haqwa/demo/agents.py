"""Deterministic native agents (AgentProof native adapter: agent(user_input, tools)).

naive_* agents contain the classic bugs; fixed_* agents are the corrected versions.
"""

from __future__ import annotations

from typing import Any

ORDER_ID, AMOUNT = "A-1", 50


async def naive_checkout(user_input: str, tools: Any) -> str:
    """Retries the charge on any error without an idempotency key -> double charge."""
    await tools.call("create_order", order_id=ORDER_ID, amount=AMOUNT)
    for _ in range(2):
        try:
            await tools.call("charge_payment", order_id=ORDER_ID, amount=AMOUNT)
            return "paid"
        except Exception:
            continue
    return "failed"


async def fixed_checkout(user_input: str, tools: Any) -> str:
    """Same retry, but every attempt uses one idempotency key -> charged once."""
    await tools.call("create_order", order_id=ORDER_ID, amount=AMOUNT)
    key = f"charge-{ORDER_ID}"
    for _ in range(2):
        try:
            await tools.call(
                "charge_payment", order_id=ORDER_ID, amount=AMOUNT, idempotency_key=key
            )
            return "paid"
        except Exception:
            continue
    return "failed"


async def naive_queue_checkout(user_input: str, tools: Any) -> str:
    """Charges through a queue; the consumer does not dedupe re-delivered messages."""
    await tools.call("create_order", order_id=ORDER_ID, amount=AMOUNT)
    await tools.call("request_charge", order_id=ORDER_ID, amount=AMOUNT)
    await tools.call("process_queue")
    return "paid"


async def fixed_queue_checkout(user_input: str, tools: Any) -> str:
    """Same flow; the consumer dedupes by message id."""
    await tools.call("create_order", order_id=ORDER_ID, amount=AMOUNT)
    await tools.call("request_charge", order_id=ORDER_ID, amount=AMOUNT)
    await tools.call("process_queue", dedupe=True)
    return "paid"
