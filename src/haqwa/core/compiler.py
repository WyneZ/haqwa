"""Spec -> runnable checker, with self-test on confirmed examples. No AI here."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .errors import COMPILE_FAILED, PATTERN_NOT_IMPLEMENTED, UNKNOWN_EVENT, HaqwaError
from .events import EventMap, group_by, sort_events, synthetic_timeline
from .patterns import REGISTRY, Finding
from .presets_v2 import expand_v1
from .rules_v2 import RuleV2, validate_rule_v2
from .rules_v2_eval import check_v2, evaluate_v2
from .spec import ConfirmedExample, Rule, Spec, TimelineEvent
from .trace import TraceVocabulary


@dataclass(frozen=True)
class CompiledRule:
    source_rule: Rule | RuleV2
    rule: RuleV2


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


def pattern_event_names(rule: Rule) -> set[str]:
    """The event names the rule's pattern is about (event, after, requires, start).

    Exception events (`reset_after`) are left out: a trace with only a reset event says
    nothing about whether the rule holds.
    """
    names = {rule.event}
    for attr in ("after", "requires", "start"):
        if hasattr(rule, attr):
            names.add(getattr(rule, attr))
    return names


def rule_event_names(rule: Rule) -> set[str]:
    """Every event name a rule refers to (pattern fields + reset_after)."""
    names = pattern_event_names(rule)
    names |= {x.reset_after for x in rule.exceptions if hasattr(x, "reset_after")}
    return names


def run_timeline(rule: Rule | RuleV2, timeline: Sequence[TimelineEvent]) -> list[Finding]:
    """Run one rule on a C1 example timeline (one synthetic entity, increasing timestamps)."""
    legacy = not isinstance(rule, RuleV2)
    if legacy:
        evaluate = REGISTRY.get(rule.pattern)
        if evaluate is None:
            raise HaqwaError(
                PATTERN_NOT_IMPLEMENTED, f"pattern {rule.pattern!r} is not implemented yet"
            )
    runnable = rule if isinstance(rule, RuleV2) else expand_v1(rule)
    events = synthetic_timeline(((t.event, t.data, t.at) for t in timeline), per=rule.per)
    # Items may name another entity via data[per]; evaluate each entity like check() does.
    events = sort_events(events)
    trace_end = events[-1].ts if events else None
    findings: list[Finding] = []
    for stream in group_by(events, rule.per).values():
        findings += evaluate_v2(runnable, stream, trace_end, legacy_reset_start=legacy)
    return findings


def violates(rule: Rule | RuleV2, timeline: Sequence[TimelineEvent]) -> bool:
    """True if the rule reports a violation on this example timeline.

    Shared by the compile self-test, canonical examples and (later) question checks.
    """
    return bool(run_timeline(rule, timeline))


def validate_rule_events(rule: Rule, event_map: EventMap) -> None:
    """Raise `unknown_event` if a rule references a name absent from the event map."""
    unknown = sorted(rule_event_names(rule) - event_map.vocabulary)
    if unknown:
        raise HaqwaError(UNKNOWN_EVENT, f"rule {rule.id!r}: events not in event map: {unknown}")


def self_test_v2(rule: RuleV2, *, legacy_reset_start: bool = False) -> list[SelfTestFailure]:
    """Check every confirmed timeline through v2 and retain the C3 failure shape."""
    failures: list[SelfTestFailure] = []
    for i, ex in enumerate(rule.confirmed_examples):
        events = synthetic_timeline(((t.event, t.data, t.at) for t in ex.timeline), per=rule.per)
        got = bool(check_v2(rule, events, legacy_reset_start=legacy_reset_start))
        if got != ex.violation:
            failures.append(SelfTestFailure(rule.id, i, ex, ex.violation, got))
    return failures


def compile_spec(
    spec: Spec,
    event_map: EventMap | None = None,
    *,
    vocabulary: TraceVocabulary | None = None,
) -> CompiledSpec:
    """Compile a validated spec. Raises CompileError on any problem.

    Checks v1 patterns and mapped events, validates v2 vocabulary and graphs, then
    runs every confirmed example through the v2 checker.
    """
    problems: list[str] = []
    failures: list[SelfTestFailure] = []
    compiled: list[CompiledRule] = []
    vocab = event_map.vocabulary if event_map else None

    for source in spec.rules:
        if isinstance(source, RuleV2):
            rule = source
            rule_problems = validate_rule_v2(
                rule,
                vocabulary.events if vocabulary is not None else vocab,
                vocabulary.fields if vocabulary is not None else None,
                vocabulary.numeric_fields if vocabulary is not None else None,
            )
            if rule_problems:
                problems.extend(f"rule {rule.id!r}: {problem}" for problem in rule_problems)
                continue
        else:
            if source.pattern not in REGISTRY:
                problems.append(
                    f"rule {source.id!r}: pattern {source.pattern!r} is not implemented yet"
                )
                continue
            if vocab is not None:
                unknown = sorted(rule_event_names(source) - vocab)
                if unknown:
                    problems.append(f"rule {source.id!r}: events not in event map: {unknown}")
                    continue
            rule = expand_v1(source).model_copy(
                update={"confirmed_examples": list(source.confirmed_examples)}
            )
        failures += self_test_v2(rule, legacy_reset_start=not isinstance(source, RuleV2))
        compiled.append(CompiledRule(source, rule))

    if problems or failures:
        raise CompileError(problems, failures)
    return CompiledSpec(spec, tuple(compiled))
