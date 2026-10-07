"""Run a compiled spec over events. Deterministic; the only place pass/fail is decided."""

from __future__ import annotations

from collections.abc import Iterable

from .compiler import CompiledSpec, pattern_event_names
from .events import Event, EventMap, group_by, sort_events
from .report import Report, RuleResult, Violation


def check(
    compiled: CompiledSpec, events: Iterable[Event], event_map: EventMap | None = None
) -> Report:
    """Translate (optional) -> sort by time -> group by entity -> evaluate each rule."""
    evs = event_map.translate(events) if event_map else list(events)
    evs = sort_events(evs)
    trace_end = evs[-1].ts if evs else None

    results: list[RuleResult] = []
    for cr in compiled.rules:
        names = pattern_event_names(cr.rule)
        checked = sum(1 for e in evs if e.event in names)
        violations: list[Violation] = []
        for entity, stream in group_by(evs, cr.rule.per).items():
            for f in cr.evaluate(cr.rule, stream, trace_end):
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
                checked_events=checked,
            )
        )
    return Report(results=results)
