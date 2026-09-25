"""Spike: AgentProof faults produce double charges; Haqwa catches them. No LLM.

Faults:
- timeout_after_commit: charge commits, agent sees a timeout, naive agent retries.
- duplicate_event: a queued charge request is delivered twice, naive consumer charges twice.

Run: python spikes/agentproof/spike_double_charge.py   (needs agentproof-sim==0.1.1 + haqwa)
"""

from __future__ import annotations

from agentproof import AgentTest
from agentproof.mutations.duplication import DuplicateEvent
from agentproof.mutations.tool_faults import TimeoutAfterCommit
from shop import print_haqwa_report, setup_shop


async def naive_sync_agent(user_input: str, tools) -> str:
    """Retries the charge on any error: the classic double-charge bug."""
    await tools.call("create_order", order_id="A-1", amount=50)
    for _ in range(2):
        try:
            await tools.call("charge_payment", order_id="A-1", amount=50)
            return "paid"
        except Exception:
            continue
    return "failed"


async def naive_queue_agent(user_input: str, tools) -> str:
    """Charges through a queue; the consumer doesn't dedupe messages."""
    await tools.call("create_order", order_id="B-2", amount=20)
    await tools.call("request_charge", order_id="B-2", amount=20)
    await tools.call("process_queue")
    return "paid"


def run(agent, mutation, label: str) -> None:
    suite = AgentTest(agent=agent, mutations=[mutation], name=label)

    @suite.scenario(name=label)
    def scenario(world):
        setup_shop(world)
        world.input("buy the order")

    print_haqwa_report(suite.run_sync(store_artifacts=False))


if __name__ == "__main__":
    run(naive_sync_agent, TimeoutAfterCommit(target="charge_payment"), "payment_timeout")
    run(naive_queue_agent, DuplicateEvent(target="charge_requested"), "duplicate_webhook")
