"""Whole-trace checking for one validated v2 rule."""

from haqwa import Spec, check, compile_spec, load_event_map, load_events, load_spec
from haqwa.core.events import EventMap
from haqwa.core.presets_v2 import expand_v1
from haqwa.core.rules_v2 import RuleV2, validate_rule_v2
from haqwa.core.rules_v2_eval import check_v2

from .helpers import H, amo, ev


def findings(violations):
    return [
        (violation.entity, violation.offending_index, violation.message)
        for violation in violations
    ]


def count_rule() -> RuleV2:
    rule = expand_v1(amo())
    assert validate_rule_v2(rule, {"charged"}, {"order_id"}, set()) == []
    return rule


def test_interleaved_unsorted_entities_have_separate_timelines():
    events = [
        ev("charged", 3, "other"),
        ev("charged", 2, "target"),
        ev("charged", 0, "target"),
        ev("note", 4, "target"),
        ev("note", 1, "other"),
    ]

    (violation,) = check_v2(count_rule(), iter(events))

    assert violation.rule_id == "r"
    assert violation.entity == "target"
    assert violation.message == "'charged' happened 2 times"
    assert violation.offending_index == 1
    assert violation.timeline == [events[2], events[1]]


def test_event_map_translates_before_evaluation():
    event_map = EventMap(events={"charged": ["PAYMENT_CAPTURED"]})
    events = [ev("PAYMENT_CAPTURED", 0), ev("PAYMENT_CAPTURED", 1)]

    (violation,) = check_v2(count_rule(), events, event_map)

    assert [event.event for event in violation.timeline] == ["charged", "charged"]
    assert violation.timeline[-1].ts == events[-1].ts


def test_time_rule_uses_whole_trace_end():
    rule = RuleV2.model_validate(
        {
            "id": "refund-window",
            "source": "Refund within 48 hours",
            "per": "order_id",
            "version": 2,
            "nodes": [
                {"id": "start", "type": "select", "event": "charged"},
                {"id": "finish", "type": "select", "event": "refunded"},
                {
                    "id": "window",
                    "type": "every_followed_within",
                    "start": "start",
                    "by": "finish",
                    "within": "PT48H",
                },
            ],
            "root": "window",
        }
    )
    assert validate_rule_v2(rule, {"charged", "refunded"}, {"order_id"}, set()) == []
    start = ev("charged", 0, "early")
    other_end = ev("note", 49 * H, "later")

    (violation,) = check_v2(rule, [other_end, start])

    assert violation.entity == "early"
    assert violation.message == "'refunded' did not happen within 48h after 'charged'"
    assert violation.offending_index == 0
    assert violation.timeline == [start]


def test_three_v1_presets_match_check_on_shop_trace(shop_dir):
    shop = load_spec(shop_dir / "rules.spec.yaml")
    prerequisite = Spec.model_validate(
        {
            "rules": [
                {
                    "id": "refund-before-charge",
                    "source": "Refund before charge",
                    "pattern": "must_precede",
                    "event": "charged",
                    "requires": "refunded",
                    "per": "order_id",
                }
            ]
        }
    ).rules[0]
    rules = [*shop.rules, prerequisite]
    event_map = load_event_map(shop_dir / "events.map.yaml")
    events = load_events(shop_dir / "events.json")
    report = check(compile_spec(Spec(rules=rules)), events, event_map)

    for rule, result in zip(rules, report.results, strict=True):
        expanded = expand_v1(rule)
        assert validate_rule_v2(
            expanded,
            event_map.vocabulary,
            {"order_id", "amount", "payment_type"},
            {"amount"},
        ) == []
        actual = check_v2(expanded, events, event_map)
        assert findings(actual) == findings(result.violations)


def test_empty_trace_has_no_violations():
    assert check_v2(count_rule(), iter(())) == []
