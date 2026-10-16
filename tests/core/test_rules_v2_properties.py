"""Differential v1/v2 preset checks and the phase 2 interpreter timing gate."""

from datetime import UTC, datetime, timedelta
from time import perf_counter

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from haqwa.core.checker import check
from haqwa.core.compiler import compile_spec
from haqwa.core.events import Event, group_by, sort_events
from haqwa.core.presets_v2 import expand_v1
from haqwa.core.rules_v2_eval import evaluate_v2
from haqwa.core.spec import Spec

PATTERNS = ("at_most_once", "never_after", "must_precede", "within_time")
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _rule_data(
    pattern, reset=None, allow_if=(), *, event_name="a", related_name="b", window="PT48H"
):
    data = {
        "id": "property-rule",
        "source": "Property rule",
        "pattern": pattern,
        "per": "entity_id",
        "event": event_name,
    }
    if pattern == "never_after":
        data["after"] = related_name
    elif pattern == "must_precede":
        data["requires"] = related_name
    elif pattern == "within_time":
        data.update(start=related_name, within=window)
    exceptions = ([{"reset_after": reset}] if reset is not None else []) + [
        {"allow_if": condition} for condition in allow_if
    ]
    if exceptions:
        data["except"] = exceptions
    return data


@st.composite
def _condition(draw):
    field = draw(st.sampled_from(("payment_type", "amount")))
    op = draw(st.sampled_from(("eq", "ne", "in")))
    choices = ("i", "c", "h") if field == "payment_type" else (0, 10, 50, 100)
    if op == "in":
        value = draw(st.lists(st.sampled_from(choices), min_size=1, max_size=2, unique=True))
    else:
        value = draw(st.sampled_from(choices))
    return {"field": field, "op": op, "value": value}


@st.composite
def _case(draw, pattern):
    entity_count = draw(st.integers(min_value=1, max_value=3))
    event_name = draw(st.sampled_from(("a", "b")))
    related_name = draw(st.sampled_from(("a", "b")))
    window = draw(st.sampled_from(("PT1H", "PT24H", "PT48H", "PT72H")))
    reset = draw(st.one_of(st.none(), st.sampled_from(("a", "b", "r"))))
    allow_if = draw(st.lists(_condition(), min_size=0, max_size=2))
    rule = Spec.model_validate(
        {
            "rules": [
                _rule_data(
                    pattern,
                    reset,
                    allow_if,
                    event_name=event_name,
                    related_name=related_name,
                    window=window,
                )
            ]
        }
    ).rules[0]
    record = st.tuples(
        st.integers(min_value=0, max_value=entity_count - 1),
        st.sampled_from(("a", "b", "r", "z")),
        st.integers(min_value=0, max_value=72),
        st.one_of(st.none(), st.sampled_from((0, 10, 50, 100))),
        st.one_of(st.none(), st.sampled_from(("i", "c", "h"))),
    )
    records = draw(st.lists(record, min_size=0, max_size=12))
    events = []
    timestamp = T0
    for entity, name, gap, amount, payment_type in records:
        timestamp += timedelta(hours=gap)
        data = {"entity_id": f"e{entity}"}
        if amount is not None:
            data["amount"] = amount
        if payment_type is not None:
            data["payment_type"] = payment_type
        events.append(Event(event=name, ts=timestamp, data=data))
    return rule, events


def _findings_from_report(rule, events):
    report = check(compile_spec(Spec(rules=[rule])), events)
    findings = {str(entity): [] for entity in group_by(sort_events(events), rule.per)}
    for violation in report.results[0].violations:
        findings[violation.entity].append((violation.offending_index, violation.message))
    return findings


def _findings_from_v2(rule, events):
    expanded = expand_v1(rule)
    ordered = sort_events(events)
    trace_end = ordered[-1].ts if ordered else None
    return {
        str(entity): [
            (finding.index, finding.message) for finding in evaluate_v2(expanded, stream, trace_end)
        ]
        for entity, stream in group_by(ordered, rule.per).items()
    }


@pytest.mark.parametrize("pattern", PATTERNS)
@settings(max_examples=300, deadline=None, derandomize=True)
@given(st.data())
def test_random_v1_rules_and_traces_match_expanded_v2(pattern, data):
    rule, events = data.draw(_case(pattern))
    assert _findings_from_v2(rule, events) == _findings_from_report(rule, events)


@pytest.fixture(scope="module")
def performance_streams():
    names = ("a", "b", "z", "a", "b", "r", "a", "z", "b", "a")
    events = [
        Event(
            event=names[step],
            ts=T0 + timedelta(seconds=entity * 10 + step),
            data={
                "entity_id": f"e{entity}",
                "amount": 50,
                "payment_type": "i" if step % 3 == 0 else "c",
            },
        )
        for entity in range(1000)
        for step in range(10)
    ]
    assert len(events) == 10_000
    return list(group_by(events, "entity_id").values()), events[-1].ts


@pytest.mark.parametrize("pattern", PATTERNS)
def test_performance_budget_for_preset(pattern, performance_streams):
    streams, trace_end = performance_streams
    base = _rule_data(
        pattern, reset="r", allow_if=({"field": "payment_type", "op": "eq", "value": "i"},)
    )
    rule = Spec.model_validate({"rules": [base]}).rules[0]
    expanded = expand_v1(rule)
    started = perf_counter()
    for stream in streams:
        evaluate_v2(expanded, stream, trace_end)
    elapsed = perf_counter() - started
    print(f"{pattern}: {elapsed:.6f} s for 10,000 events / 1,000 entities")
    assert elapsed < 1.0
