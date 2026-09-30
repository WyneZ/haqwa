"""Scenario catalogue + runner for the terminal demo and web screen 2.

run_scenario(id, spec) runs one agent under one AgentProof fault, converts the effect
ledger to events and checks them with Haqwa. Deterministic, no Gemini, milliseconds.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agentproof import AgentTest
from agentproof.mutations.base import Mutation
from agentproof.mutations.duplication import DuplicateEvent
from agentproof.mutations.tool_faults import TimeoutAfterCommit

from ..adapters.agentproof import effects_to_events
from ..core.checker import check
from ..core.compiler import compile_spec
from ..core.events import Event, EventMap
from ..core.report import Report
from ..core.spec import Spec
from . import agents
from .shop import setup_shop


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    fault: str  # AgentProof mutation type
    agent: str  # "naive" | "fixed"
    description: str
    expected: str  # "violation" | "pass" (with examples/shop/rules.spec.yaml)
    _agent_fn: Callable[[str, Any], Any]
    _mutation: Callable[[], Mutation]

    def to_dict(self) -> dict[str, str]:
        """Public fields only (JSON-ready for the web API)."""
        keys = ("id", "title", "fault", "agent", "description", "expected")
        return {k: getattr(self, k) for k in keys}


_SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "payment_timeout_naive",
        "Payment timeout — naive agent",
        "timeout_after_commit",
        "naive",
        "The charge succeeds, then the API times out; the agent retries without an "
        "idempotency key.",
        "violation",
        agents.naive_checkout,
        lambda: TimeoutAfterCommit(target="charge_payment"),
    ),
    Scenario(
        "payment_timeout_fixed",
        "Payment timeout — fixed agent",
        "timeout_after_commit",
        "fixed",
        "Same timeout; the agent retries with one idempotency key.",
        "pass",
        agents.fixed_checkout,
        lambda: TimeoutAfterCommit(target="charge_payment"),
    ),
    Scenario(
        "duplicate_webhook_naive",
        "Duplicate webhook — naive consumer",
        "duplicate_event",
        "naive",
        "The charge request message is delivered twice; the consumer charges twice.",
        "violation",
        agents.naive_queue_checkout,
        lambda: DuplicateEvent(target="charge_requested"),
    ),
    Scenario(
        "duplicate_webhook_fixed",
        "Duplicate webhook — fixed consumer",
        "duplicate_event",
        "fixed",
        "Same duplicate delivery; the consumer dedupes by message id.",
        "pass",
        agents.fixed_queue_checkout,
        lambda: DuplicateEvent(target="charge_requested"),
    ),
)


def list_scenarios() -> list[dict[str, str]]:
    """All demo scenarios, JSON-ready."""
    return [s.to_dict() for s in _SCENARIOS]


def _get(scenario_id: str) -> Scenario:
    for s in _SCENARIOS:
        if s.id == scenario_id:
            return s
    raise KeyError(f"unknown scenario: {scenario_id!r}")


def run_scenario(
    scenario_id: str, spec: Spec, event_map: EventMap | None = None
) -> tuple[list[Event], Report]:
    """Run the scenario's agent under its fault, then check the effects against `spec`.

    Raises KeyError (unknown id) or CompileError (bad spec). The effects use the rule
    vocabulary of examples/shop (order_created, charged, refunded); pass `event_map`
    only if the spec uses other names.
    """
    scenario = _get(scenario_id)
    compiled = compile_spec(spec, event_map)
    suite = AgentTest(agent=scenario._agent_fn, name=scenario.id)

    @suite.scenario(name=scenario.id)
    def _world(world: Any) -> None:
        setup_shop(world)
        world.input("Buy order A-1.")

    result = suite.run_sync(mutations=[scenario._mutation()], store_artifacts=False)
    faulted = [r for r in result.results if r.mutation is not None]
    if not faulted:
        raise RuntimeError(f"scenario {scenario.id!r}: fault run did not happen")
    run = faulted[-1]
    if run.error_message:
        raise RuntimeError(f"scenario {scenario.id!r}: agent failed: {run.error_message}")
    events = effects_to_events(run.effects)
    return events, check(compiled, events, event_map)
