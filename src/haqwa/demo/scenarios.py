"""Scenario catalogue + runner for the terminal demo and web screen 2.

run_scenario(id, spec) runs one agent under one AgentProof fault, converts the effect
ledger to events and checks them with Haqwa. Deterministic, no Gemini, milliseconds.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from agentproof import AgentTest
from agentproof.mutations.base import Mutation
from agentproof.mutations.duplication import DuplicateEvent
from agentproof.mutations.state import StaleState
from agentproof.mutations.tool_faults import TimeoutAfterCommit

from ..adapters.agentproof import effects_to_events
from ..core.checker import check
from ..core.compiler import compile_spec
from ..core.errors import UNKNOWN_SCENARIO, HaqwaError
from ..core.events import Event, EventMap
from ..core.report import Report
from ..core.spec import Spec
from . import agents
from .recording import RECORDINGS_DIR, load_effects
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
    Scenario(
        "stale_status_naive",
        "Stale order status — naive agent",
        "stale_state",
        "naive",
        "A cancelled order looks paid in a stale read; the agent ships it.",
        "violation",
        agents.naive_fulfilment,
        lambda: StaleState(
            target="get_order", params={"value": {"order_id": agents.ORDER_ID, "status": "paid"}}
        ),
    ),
    Scenario(
        "stale_status_fixed",
        "Stale order status — fixed agent",
        "stale_state",
        "fixed",
        "The same stale read; shipping checks the real order status.",
        "pass",
        agents.fixed_fulfilment,
        lambda: StaleState(
            target="get_order", params={"value": {"order_id": agents.ORDER_ID, "status": "paid"}}
        ),
    ),
)

_RECORDING_NAME = re.compile(
    r"gemini_(?:(?P<scenario>[a-z][a-z0-9_]*?)_)?(?P<date>\d{4}_\d{2}_\d{2})"
)


def _recording_title(stem: str) -> str | None:
    match = _RECORDING_NAME.fullmatch(stem)
    if match is None:
        return None
    date = match.group("date").replace("_", "-")
    scenario = match.group("scenario")
    if scenario is None:
        return f"Recorded Gemini agent run ({date})"
    run_number = re.search(r"_run_?(\d+)$", scenario)
    scenario_id = scenario[: run_number.start()] if run_number else scenario
    known = next((s.title for s in _SCENARIOS if s.id == scenario_id), None)
    scenario_title = known or scenario_id.replace("_", " ").capitalize()
    if run_number:
        scenario_title += f" — run {run_number.group(1)}"
    return f"Recorded Gemini agent — {scenario_title} ({date})"


def list_scenarios(
    spec: Spec | None = None, event_map: EventMap | None = None
) -> list[dict[str, str]]:
    """All scenarios; recorded verdicts are known only when checked against a spec."""
    scenarios = [s.to_dict() for s in _SCENARIOS]
    for path in sorted(RECORDINGS_DIR.glob("gemini_*.json")):
        title = _recording_title(path.stem)
        if title is None:
            continue
        expected = "unknown"
        if spec is not None:
            compiled = compile_spec(spec, event_map)
            expected = (
                "pass" if check(compiled, load_effects(path), event_map).passed else "violation"
            )
        scenarios.append(
            {
                "id": f"recorded_{path.stem}",
                "title": title,
                "fault": "recorded",
                "agent": "gemini",
                "description": "Saved AgentProof effects; replay makes no Gemini request.",
                "expected": expected,
            }
        )
    return scenarios


def _get(scenario_id: str) -> Scenario:
    for s in _SCENARIOS:
        if s.id == scenario_id:
            return s
    known = ", ".join(s.id for s in _SCENARIOS)
    raise HaqwaError(UNKNOWN_SCENARIO, f"unknown scenario {scenario_id!r} (known: {known})")


def run_scenario(
    scenario_id: str, spec: Spec, event_map: EventMap | None = None
) -> tuple[list[Event], Report]:
    """Run the scenario's agent under its fault, then check the effects against `spec`.

    Raises HaqwaError: `unknown_scenario`, or `compile_failed` (CompileError) for a bad spec.
    The effects use the vocabulary of examples/shop (order_created, charged, refunded,
    cancelled, shipped);
    pass `event_map`
    only if the spec uses other names.
    """
    stream = iter_scenario(scenario_id, spec, event_map)
    events: list[Event] = []
    report: Report | None = None
    for kind, value in stream:
        if kind == "event":
            assert isinstance(value, Event)
            events.append(value)
        else:
            assert isinstance(value, Report)
            report = value
    assert report is not None
    return events, report


def iter_scenario(
    scenario_id: str, spec: Spec, event_map: EventMap | None = None
) -> Iterator[tuple[str, Event | Report]]:
    """Yield each effect as an event, then the final deterministic report."""
    stem = scenario_id.removeprefix("recorded_")
    if scenario_id.startswith("recorded_") and _recording_title(stem) is not None:
        path = RECORDINGS_DIR / f"{stem}.json"
        if path.is_file():
            compiled = compile_spec(spec, event_map)
            events = load_effects(path)
            for event in events:
                yield "event", event
            yield "report", check(compiled, events, event_map)
            return
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
    for event in events:
        yield "event", event
    yield "report", check(compiled, events, event_map)
