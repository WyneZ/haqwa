"""Run a compiled spec over events. Deterministic; the only place pass/fail is decided."""

from __future__ import annotations

from collections.abc import Iterable

from .compiler import CompiledSpec
from .events import Event, EventMap, sort_events
from .report import Report, RuleResult
from .rules_v2 import SelectNode
from .rules_v2_eval import check_v2


def check(
    compiled: CompiledSpec, events: Iterable[Event], event_map: EventMap | None = None
) -> Report:
    """Translate (optional) -> sort by time -> group by entity -> evaluate each rule."""
    evs = event_map.translate(events) if event_map else list(events)
    evs = sort_events(evs)
    results: list[RuleResult] = []
    for cr in compiled.rules:
        names = {node.event for node in cr.rule.nodes if isinstance(node, SelectNode)}
        checked = sum(1 for e in evs if e.event in names)
        violations = check_v2(cr.rule, evs)
        results.append(
            RuleResult(
                rule_id=cr.source_rule.id,
                source=cr.source_rule.source,
                status="violation" if violations else "pass",
                violations=violations,
                checked_events=checked,
            )
        )
    return Report(results=results)
