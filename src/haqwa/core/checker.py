"""Run a compiled spec over events. Deterministic; the only place pass/fail is decided."""

from __future__ import annotations

from collections.abc import Iterable

from .compiler import CompiledSpec
from .events import Event, EventMap, group_by, sort_events
from .report import Report, RuleResult, Violation


def check(
    compiled: CompiledSpec, events: Iterable[Event], event_map: EventMap | None = None
) -> Report:
    """Translate (optional) -> sort by time -> group by entity -> evaluate each rule."""
    evs = event_map.translate(events) if event_map else list(events)
    evs = sort_events(evs)

    results: list[RuleResult] = []
    for cr in compiled.rules:
        violations: list[Violation] = []
        for entity, stream in group_by(evs, cr.rule.per).items():
            for f in cr.evaluate(cr.rule, stream):
                violations.append(
                    Violation(
                        rule_id=cr.rule.id,
                        entity=str(entity),
                        message=f.message,
                        timeline=stream[: f.index + 1],
                        offending_index=f.index,
                    )
                )
        results.append(
            RuleResult(
                rule_id=cr.rule.id,
                source=cr.rule.source,
                status="violation" if violations else "pass",
                violations=violations,
            )
        )
    return Report(results=results)
