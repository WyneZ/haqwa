"""Shared spike helpers: a tiny virtual shop inside an AgentProof world + effect -> Haqwa events."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from agentproof import Effect
from agentproof.tools.definition import ToolOutcome

from haqwa import Event, check, compile_spec, format_text, load_spec

ROOT = Path(__file__).resolve().parents[2]
ORDER_SCHEMA = {
    "type": "object",
    "properties": {"order_id": {"type": "string"}, "amount": {"type": "integer"}},
    "required": ["order_id", "amount"],
}
EMPTY_SCHEMA = {"type": "object", "properties": {}}


def setup_shop(world) -> None:
    """Register shop tools. Every side effect is committed to the AgentProof effect ledger."""

    def create_order(order_id: str, amount: int):
        return ToolOutcome(
            value={"order_id": order_id},
            effects=[{"type": "order_created", "data": {"order_id": order_id, "amount": amount}}],
        )

    def charge_payment(order_id: str, amount: int):
        return ToolOutcome(
            value={"status": "captured"},
            effects=[{"type": "charged", "data": {"order_id": order_id, "amount": amount}}],
        )

    def request_charge(order_id: str, amount: int):
        """Async flow: put a charge request on a queue (like a payment webhook/message)."""
        world.events.schedule(
            name="charge_requested", payload={"order_id": order_id, "amount": amount}
        )
        return {"status": "queued"}

    def process_queue():
        """Naive consumer: charges once per delivered message, no dedupe by message id."""
        effects = [
            {"type": "charged", "data": dict(ev.payload)}
            for ev in world.events.deliver_due()
            if ev.name == "charge_requested"
        ]
        return ToolOutcome(value={"processed": len(effects)}, effects=effects)

    reg = world.tools.register
    reg(
        name="create_order",
        description="Create an order",
        input_schema=ORDER_SCHEMA,
        handler=create_order,
        effect="write",
    )
    reg(
        name="charge_payment",
        description="Charge the customer's card for an order",
        input_schema=ORDER_SCHEMA,
        handler=charge_payment,
        effect="financial",
        idempotent=False,
    )
    reg(
        name="request_charge",
        description="Queue a charge request",
        input_schema=ORDER_SCHEMA,
        handler=request_charge,
        effect="external",
    )
    reg(
        name="process_queue",
        description="Process queued charge requests",
        input_schema=EMPTY_SCHEMA,
        handler=process_queue,
        effect="financial",
    )


def effects_to_events(effects: list[Effect]) -> list[Event]:
    """Draft of adapters/agentproof.py: AgentProof effect ledger -> Haqwa events (C2)."""
    t0 = datetime(2026, 1, 1, tzinfo=UTC)  # virtual clock is float seconds; anchor it
    return [
        Event(event=e.type, ts=t0 + timedelta(seconds=e.committed_at), data=e.data, source_id=e.id)
        for e in effects
    ]


def print_haqwa_report(suite_result) -> None:
    """Check every AgentProof run against examples/shop/rules.spec.yaml."""
    compiled = compile_spec(load_spec(ROOT / "examples/shop/rules.spec.yaml"))
    for run in suite_result.results:
        label = f"{run.scenario} / {run.mutation.type if run.mutation else 'baseline'}"
        print(f"\n=== AgentProof run: {label} | effects: {[e.type for e in run.effects]}")
        report = check(compiled, effects_to_events(run.effects))
        if run.error_message:
            print(f"    agent error: {run.error_message.splitlines()[0][:160]}")
            if report.passed:
                # The agent crashed early; "no violation" here proves nothing.
                print("RESULT: INCONCLUSIVE (agent did not finish; re-run)")
                continue
            print("    (agent did not finish, but these effects really happened)")
        print(format_text(report))
