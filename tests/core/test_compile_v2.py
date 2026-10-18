"""Compilation, self-test, and reporting for mixed v1/v2 specs."""

from datetime import timedelta

import pytest

from haqwa.core.checker import check
from haqwa.core.compiler import CompileError, compile_spec, run_timeline, violates
from haqwa.core.errors import to_problem
from haqwa.core.events import EventMap
from haqwa.core.rules_v2 import RuleV2
from haqwa.core.spec import Spec, TimelineEvent
from haqwa.core.trace import TraceVocabulary

from .helpers import ev


def _composed_rule():
    return {
        "id": "composed",
        "source": "Refunds cannot exceed charges, and approval is separate.",
        "per": "order_id",
        "version": 2,
        "nodes": [
            {
                "id": "charges",
                "type": "select",
                "event": "charged",
                "where": [{"field": "amount", "op": "gt", "value": 10}],
            },
            {"id": "refunds", "type": "select", "event": "refunded"},
            {
                "id": "refund-limit",
                "type": "sum_compare",
                "left": {"of": "refunds", "field": "amount"},
                "op": "le",
                "right": {"of": "charges", "field": "amount"},
            },
            {
                "id": "separation",
                "type": "field_compare",
                "of": "charges",
                "a": "approver",
                "op": "ne",
                "b": "requester",
            },
            {"id": "all", "type": "all_of", "children": ["refund-limit", "separation"]},
        ],
        "root": "all",
    }


def _vocab(**overrides):
    data = {
        "events": ["charged", "refunded"],
        "fields": ["order_id", "amount", "approver", "requester"],
        "numeric_fields": ["amount"],
        "field_values": {},
    }
    return TraceVocabulary.model_validate(data | overrides)


def test_numeric_vocabulary_serializes_when_populated():
    assert _vocab().model_dump()["numeric_fields"] == ["amount"]
    assert "numeric_fields" not in _vocab(numeric_fields=[]).model_dump()


def test_composed_v2_rule_compiles_and_catches_two_violations():
    spec = Spec.model_validate({"version": 2, "rules": [_composed_rule()]})
    compiled = compile_spec(spec, vocabulary=_vocab())
    assert compiled.rules[0].source_rule is spec.rules[0]
    assert compiled.rules[0].rule is spec.rules[0]
    events = [
        ev("charged", 0, amount=20, approver="same", requester="same"),
        ev("refunded", 1, amount=21),
        ev("cancelled", 2),
    ]
    (result,) = check(compiled, events).results
    assert result.status == "violation"
    assert result.checked_events == 2
    assert len(result.violations) == 2
    assert {v.message.split("]", 1)[0] for v in result.violations} == {
        "[refund-limit",
        "[separation",
    }


def test_v2_rule_without_vocabulary_skips_name_checks_but_checks_structure():
    spec = Spec.model_validate({"version": 2, "rules": [_composed_rule()]})
    assert compile_spec(spec).rules[0].rule == spec.rules[0]
    broken = _composed_rule()
    broken["nodes"][-1]["children"] = ["missing"]
    with pytest.raises(CompileError, match="unknown node id"):
        compile_spec(Spec.model_validate({"version": 2, "rules": [broken]}))


def test_vocabulary_reports_all_unknown_and_nonnumeric_problems():
    spec = Spec.model_validate({"version": 2, "rules": [_composed_rule()]})
    vocab = _vocab(events=["charged"], fields=["order_id", "requester"], numeric_fields=[])
    with pytest.raises(CompileError) as exc:
        compile_spec(spec, vocabulary=vocab)
    problems = exc.value.problems
    assert any("unknown event 'refunded'" in problem for problem in problems)
    assert any("unknown field 'amount'" in problem for problem in problems)
    assert any("'amount' is not numeric" in problem for problem in problems)
    assert any("unknown field 'approver'" in problem for problem in problems)
    assert len(problems) >= 5


def test_event_map_alone_rejects_unknown_v2_event():
    spec = Spec.model_validate({"version": 2, "rules": [_composed_rule()]})
    event_map = EventMap(events={"charged": ["PAY"]})
    with pytest.raises(CompileError, match="unknown event 'refunded'"):
        compile_spec(spec, event_map)
    assert compile_spec(spec, event_map, vocabulary=_vocab()).rules[0].rule == spec.rules[0]


def test_v2_wrong_confirmed_example_keeps_self_test_failure_shape():
    data = _composed_rule()
    data["confirmed_examples"] = [
        {
            "timeline": [
                {"event": "charged", "data": {"amount": 20, "approver": "x", "requester": "x"}}
            ],
            "violation": False,
        }
    ]
    spec = Spec.model_validate({"version": 2, "rules": [data]})
    with pytest.raises(CompileError) as exc:
        compile_spec(spec, vocabulary=_vocab())
    assert len(exc.value.failures) == 1
    assert exc.value.failures[0].expected_violation is False
    assert exc.value.failures[0].got_violation is True
    problem = to_problem(exc.value)
    assert problem["status"] == 422
    assert problem["failures"][0]["rule_id"] == "composed"


def test_v2_run_timeline_and_violates_accept_rule():
    rule = RuleV2.model_validate(_composed_rule())
    timeline = [
        TimelineEvent(event="charged", data={"amount": 20, "approver": "x", "requester": "x"})
    ]
    assert run_timeline(rule, timeline)
    assert violates(rule, timeline)


def test_v2_checked_events_ignore_reset_only_events():
    rule = {
        "id": "charge-once",
        "source": "Charge once between refunds",
        "per": "order_id",
        "version": 2,
        "nodes": [
            {"id": "target", "type": "select", "event": "charged"},
            {
                "id": "limit",
                "type": "count",
                "of": "target",
                "op": "le",
                "value": 1,
                "since": ["refunded"],
            },
        ],
        "root": "limit",
    }
    spec = Spec.model_validate({"version": 2, "rules": [rule]})
    (result,) = check(compile_spec(spec), [ev("refunded", 0), ev("charged", 1)]).results
    assert result.checked_events == 1
    assert result.status == "pass"


def test_mixed_spec_uses_restart_semantics_for_v1_too():
    v1 = {
        "id": "v1-window",
        "source": "Finish within an hour",
        "per": "order_id",
        "pattern": "within_time",
        "start": "started",
        "event": "finished",
        "within": "PT1H",
        "except": [{"reset_after": "started"}],
        "confirmed_examples": [
            {
                "timeline": [
                    {"event": "started", "at": "PT0S"},
                    {"event": "started", "at": "PT30M"},
                    {"event": "finished", "at": "PT1H31M"},
                ],
                "violation": True,
            }
        ],
    }
    spec = Spec.model_validate({"version": 2, "rules": [v1, _composed_rule()]})
    compiled = compile_spec(spec)
    assert compiled.rules[0].source_rule is spec.rules[0]
    assert isinstance(compiled.rules[0].rule, RuleV2)
    assert compiled.rules[1].source_rule is spec.rules[1]
    events = [ev("started", 0), ev("started", 1800), ev("finished", 5460)]
    assert check(compiled, events).results[0].status == "violation"
    assert violates(
        spec.rules[0],
        [
            TimelineEvent(event="started", at=timedelta(0)),
            TimelineEvent(event="started", at=timedelta(minutes=30)),
            TimelineEvent(event="finished", at=timedelta(minutes=91)),
        ],
    )
