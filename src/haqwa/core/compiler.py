"""Spec -> runnable checker, with self-test on confirmed examples. No AI here."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .events import EventMap, synthetic_timeline
from .patterns import REGISTRY, Evaluator, Finding
from .spec import ConfirmedExample, Rule, Spec, TimelineEvent


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

    def __str__(self) -> str:
        names = " -> ".join(e.event for e in self.example.timeline)
        return (
            f"rule {self.rule_id!r}, example #{self.example_index} [{names}]: "
            f"human said violation={self.expected_violation}, "
            f"checker said violation={self.got_violation}"
        )


class CompileError(Exception):
    """Spec can't be compiled. `problems` lists every reason, not just the first."""

    def __init__(self, problems: list[str], failures: list[SelfTestFailure] | None = None):
        self.problems = problems
        self.failures = failures or []
        super().__init__("\n".join(problems + [str(f) for f in self.failures]))


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
            raise ValueError(f"pattern {rule.pattern!r} is not implemented yet")
    events = synthetic_timeline(((t.event, t.data) for t in timeline), per=rule.per)
    return evaluate(rule, events)


def violates(rule: Rule, timeline: Sequence[TimelineEvent]) -> bool:
    """True if the rule reports a violation on this example timeline.

    Shared by the compile self-test, canonical examples and (later) question checks.
    """
    return bool(run_timeline(rule, timeline))


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
