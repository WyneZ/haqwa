"""Spec -> runnable checker, with self-test on confirmed examples. No AI here."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .errors import COMPILE_FAILED, PATTERN_NOT_IMPLEMENTED, UNKNOWN_EVENT, HaqwaError
from .events import EventMap, group_by, sort_events, synthetic_timeline
from .patterns import REGISTRY, Evaluator, Finding
from .spec import ConfirmedExample, Rule, RuleException, Spec, TimelineEvent


@dataclass(frozen=True)
class CompiledRule:
    rule: Rule
    evaluate: Evaluator


@dataclass(frozen=True)
class CompiledSpec:
    spec: Spec
    rules: tuple[CompiledRule, ...]


@dataclass(frozen=True)
class SelfTestFailure:
    """A confirmed example where the checker disagrees with the human answer."""

    rule_id: str
    example_index: int
    example: ConfirmedExample
    expected_violation: bool
    got_violation: bool

    def to_dict(self) -> dict[str, Any]:
        """JSON shape used by the web API (C3 seal 422)."""
        return {
            "rule_id": self.rule_id,
            "example_index": self.example_index,
            "timeline": [
                t.model_dump(mode="json", exclude_defaults=True) for t in self.example.timeline
            ],
            "expected": self.expected_violation,
            "got": self.got_violation,
        }

    def __str__(self) -> str:
        names = " -> ".join(e.event for e in self.example.timeline)
        return (
            f"rule {self.rule_id!r}, example #{self.example_index} [{names}]: "
            f"human said violation={self.expected_violation}, "
            f"checker said violation={self.got_violation}"
        )


class CompileError(HaqwaError):
    """Spec can't be compiled. `problems` lists every reason, not just the first.

    Code `compile_failed`. `to_problem()` adds `problems` and `failures` (C3 seal 422 shape).
    """

    def __init__(self, problems: list[str], failures: list[SelfTestFailure] | None = None):
        self.problems = problems
        self.failures = failures or []
        lines = problems + [str(f) for f in self.failures]
        super().__init__(
            COMPILE_FAILED,
            "\n".join(lines),
            problems=list(problems),
            failures=[f.to_dict() for f in self.failures],
        )


def rule_event_names(rule: Rule) -> set[str]:
    """Every event name a rule refers to (pattern fields + reset_after)."""
    names = {rule.event}
    for attr in ("after", "requires", "start"):
        if hasattr(rule, attr):
            names.add(getattr(rule, attr))
    names |= {x.reset_after for x in rule.exceptions if hasattr(x, "reset_after")}
    return names


def run_timeline(
    rule: Rule, timeline: Sequence[TimelineEvent], evaluate: Evaluator | None = None
) -> list[Finding]:
    """Run one rule on a C1 example timeline (one synthetic entity, increasing timestamps)."""
    if evaluate is None:
        evaluate = REGISTRY.get(rule.pattern)
        if evaluate is None:
            raise HaqwaError(
                PATTERN_NOT_IMPLEMENTED, f"pattern {rule.pattern!r} is not implemented yet"
            )
    events = synthetic_timeline(((t.event, t.data, t.at) for t in timeline), per=rule.per)
    # Items may name another entity via data[per]; evaluate each entity like check() does.
    events = sort_events(events)
    trace_end = events[-1].ts if events else None
    findings: list[Finding] = []
    for stream in group_by(events, rule.per).values():
        findings += evaluate(rule, stream, trace_end)
    return findings


def violates(rule: Rule, timeline: Sequence[TimelineEvent]) -> bool:
    """True if the rule reports a violation on this example timeline.

    Shared by the compile self-test, canonical examples and question checks.
    """
    return bool(run_timeline(rule, timeline))


def distinguishes(rule: Rule, exception: RuleException, timeline: Sequence[TimelineEvent]) -> bool:
    """True if adding `exception` to `rule` changes the verdict on `timeline`.

    A Yes/No decision question ("Yes" adds `exception`, "No" keeps the rule) is only
    testable if this is True: otherwise both answers give the same verdict, and the
    owner's answer could not be checked by the compile self-test. Exceptions only relax
    a rule, so a testable timeline violates the rule without the exception and passes
    with it.
    """
    relaxed = rule.model_copy(update={"exceptions": [*rule.exceptions, exception]})
    return violates(rule, timeline) != violates(relaxed, timeline)


def validate_rule_events(rule: Rule, event_map: EventMap) -> None:
    """Raise `unknown_event` if a rule references a name absent from the event map."""
    unknown = sorted(rule_event_names(rule) - event_map.vocabulary)
    if unknown:
        raise HaqwaError(UNKNOWN_EVENT, f"rule {rule.id!r}: events not in event map: {unknown}")


def self_test(rule: Rule, evaluate: Evaluator) -> list[SelfTestFailure]:
    """Run each confirmed example as a synthetic event list; compare with the human answer."""
    failures: list[SelfTestFailure] = []
    for i, ex in enumerate(rule.confirmed_examples):
        got = bool(run_timeline(rule, ex.timeline, evaluate))
        if got != ex.violation:
            failures.append(SelfTestFailure(rule.id, i, ex, ex.violation, got))
    return failures


def compile_spec(spec: Spec, event_map: EventMap | None = None) -> CompiledSpec:
    """Compile a validated spec. Raises CompileError on any problem.

    Checks: pattern implemented, event names exist in the event map (if given),
    and every confirmed example gives the human's answer.
    """
    problems: list[str] = []
    failures: list[SelfTestFailure] = []
    compiled: list[CompiledRule] = []
    vocab = event_map.vocabulary if event_map else None

    for rule in spec.rules:
        evaluate = REGISTRY.get(rule.pattern)
        if evaluate is None:
            problems.append(f"rule {rule.id!r}: pattern {rule.pattern!r} is not implemented yet")
            continue
        if vocab is not None:
            unknown = sorted(rule_event_names(rule) - vocab)
            if unknown:
                problems.append(f"rule {rule.id!r}: events not in event map: {unknown}")
                continue
        failures += self_test(rule, evaluate)
        compiled.append(CompiledRule(rule, evaluate))

    if problems or failures:
        raise CompileError(problems, failures)
    return CompiledSpec(spec, tuple(compiled))
