"""Interpreter behavior before v1 preset expansion is wired in."""

from datetime import timedelta

import pytest

from haqwa.core.rules_v2 import RuleV2, validate_rule_v2
from haqwa.core.rules_v2_eval import evaluate_v2

from .helpers import T0, H, ev

CHARGE = {"id": "charge", "type": "select", "event": "charged"}
REFUND = {"id": "refund", "type": "select", "event": "refunded"}
RESET = ["reset"]


def run(checker, events, *, selects=(CHARGE,), trace_end=None, root="check", extra=()):
    rule = RuleV2.model_validate(
        {
            "id": "sample",
            "source": "Sample policy",
            "per": "order_id",
            "version": 2,
            "nodes": [*selects, checker, *extra],
            "root": root,
        }
    )
    vocabulary = (
        {event.event for event in events} | {node["event"] for node in selects} | set(RESET)
    )
    assert (
        validate_rule_v2(
            rule, vocabulary, {"order_id", "amount", "payment_type", "a", "b"}, {"amount"}
        )
        == []
    )
    return evaluate_v2(rule, events, trace_end)


def pairs(findings):
    return [(finding.index, finding.message) for finding in findings]


def test_select_where_numeric_and_exclude_v1_semantics():
    selected = {
        **CHARGE,
        "where": [{"field": "amount", "op": "gt", "value": 10}],
        "exclude": [{"field": "payment_type", "op": "eq", "value": "i"}],
    }
    checker = {"id": "check", "type": "count", "of": "charge", "op": "le", "value": 0}
    events = [
        ev("charged", 0, amount=9),
        ev("charged", 1, amount="large"),
        ev("charged", 2, amount=20, payment_type="i"),
        ev("charged", 3, amount=20),
    ]
    assert pairs(run(checker, events, selects=(selected,))) == [(3, "'charged' happened 1 times")]


@pytest.mark.parametrize(
    ("op", "value", "expected"),
    [
        ("eq", "i", [1]),
        ("ne", "i", [2, 3]),
        ("in", ["i", "h"], [1, 2]),
    ],
)
def test_where_keeps_v1_condition_and_missing_field_semantics(op, value, expected):
    selected = {**CHARGE, "where": [{"field": "payment_type", "op": op, "value": value}]}
    checker = {"id": "check", "type": "count", "of": "charge", "op": "le", "value": 0}
    events = [
        ev("charged", 0),
        ev("charged", 1, payment_type="i"),
        ev("charged", 2, payment_type="h"),
        ev("charged", 3, payment_type="c"),
    ]
    assert [finding.index for finding in run(checker, events, selects=(selected,))] == expected


@pytest.mark.parametrize("op", ["gt", "ge", "lt", "le"])
def test_numeric_where_operators(op):
    selected = {**CHARGE, "where": [{"field": "amount", "op": op, "value": 10}]}
    checker = {"id": "check", "type": "count", "of": "charge", "op": "le", "value": 0}
    events = [
        ev("charged", 0, amount=9),
        ev("charged", 1, amount=10),
        ev("charged", 2, amount=11),
        ev("charged", 3),
    ]
    expected = {
        "gt": [2],
        "ge": [1, 2],
        "lt": [0],
        "le": [0, 1],
    }[op]
    assert [finding.index for finding in run(checker, events, selects=(selected,))] == expected


def test_exclude_missing_field_in_and_two_conditions():
    checker = {"id": "check", "type": "count", "of": "charge", "op": "le", "value": 0}
    events = [
        ev("charged", 0),
        ev("charged", 1, payment_type="i"),
        ev("charged", 2, payment_type="h"),
        ev("charged", 3, payment_type="c", amount=50),
        ev("charged", 4, payment_type="c", amount=5),
    ]
    with_in = {
        **CHARGE,
        "exclude": [
            {"field": "payment_type", "op": "in", "value": ["i", "h"]},
        ],
    }
    assert [finding.index for finding in run(checker, events, selects=(with_in,))] == [0, 3, 4]
    with_two = {
        **CHARGE,
        "exclude": [
            {"field": "payment_type", "op": "eq", "value": "i"},
            {"field": "amount", "op": "in", "value": [0, 50]},
        ],
    }
    assert [finding.index for finding in run(checker, events, selects=(with_two,))] == [0, 2, 4]
    with_ne = {
        **CHARGE,
        "exclude": [
            {"field": "payment_type", "op": "ne", "value": "i"},
        ],
    }
    assert [finding.index for finding in run(checker, events, selects=(with_ne,))] == [0, 1]


def test_count_le_and_lt_find_every_excess_event():
    events = [ev("charged", i) for i in range(3)]
    le = {"id": "check", "type": "count", "of": "charge", "op": "le", "value": 1}
    lt = {**le, "op": "lt"}
    assert pairs(run(le, events)) == [
        (1, "'charged' happened 2 times"),
        (2, "'charged' happened 3 times"),
    ]
    assert [finding.index for finding in run(lt, events)] == [0, 1, 2]
    assert run(le, [ev("charged", 0)]) == []


def test_count_eq_and_ge_at_end_and_eq_excess_not_duplicated():
    eq = {"id": "check", "type": "count", "of": "charge", "op": "eq", "value": 2}
    ge = {**eq, "op": "ge"}
    events = [ev("charged", 0), ev("note", 1)]
    assert pairs(run(eq, events)) == [(1, "'charged' count 1 is not eq 2")]
    assert pairs(run(ge, events)) == [(1, "'charged' count 1 is not ge 2")]
    assert run(eq, [ev("charged", 0), ev("charged", 1)]) == []
    assert run(ge, [ev("charged", 0), ev("charged", 1)]) == []
    exceeded = [ev("charged", i) for i in range(4)]
    assert [finding.index for finding in run(eq, exceeded)] == [2, 3]


def test_reset_is_processed_before_matching_same_named_event():
    checker = {
        "id": "check",
        "type": "count",
        "of": "charge",
        "op": "le",
        "value": 1,
        "since": ["charged"],
    }
    assert run(checker, [ev("charged", 0), ev("charged", 1)]) == []


def test_none_after_passes_then_flags_each_target_including_same_event_case():
    checker = {"id": "check", "type": "none_after", "of": "charge", "after": "refund"}
    events = [ev("charged", 0), ev("refunded", 1), ev("charged", 2), ev("charged", 3)]
    assert pairs(run(checker, events, selects=(CHARGE, REFUND))) == [
        (2, "'charged' happened after 'refunded'"),
        (3, "'charged' happened after 'refunded'"),
    ]
    same = {**checker, "after": "charge"}
    assert [finding.index for finding in run(same, [ev("charged", 0), ev("charged", 1)])] == [1]


def test_none_after_reset_disarms_before_target():
    checker = {
        "id": "check",
        "type": "none_after",
        "of": "charge",
        "after": "refund",
        "since": RESET,
    }
    events = [ev("refunded", 0), ev("reset", 1), ev("charged", 2)]
    assert run(checker, events, selects=(CHARGE, REFUND)) == []


def test_every_preceded_by_passes_or_flags_each_unenabled_target():
    checker = {
        "id": "check",
        "type": "every_preceded_by",
        "of": "charge",
        "by": "refund",
        "since": RESET,
    }
    events = [
        ev("charged", 0),
        ev("refunded", 1),
        ev("charged", 2),
        ev("reset", 3),
        ev("charged", 4),
    ]
    assert pairs(run(checker, events, selects=(CHARGE, REFUND))) == [
        (0, "'charged' happened without an earlier 'refunded' (since the last 'reset')"),
        (4, "'charged' happened without an earlier 'refunded' (since the last 'reset')"),
    ]


def test_every_followed_within_deadline_late_and_open_trace_end():
    checker = {
        "id": "check",
        "type": "every_followed_within",
        "start": "charge",
        "by": "refund",
        "within": "PT48H",
    }
    assert run(checker, [ev("charged", 0), ev("refunded", 48 * H)], selects=(CHARGE, REFUND)) == []
    assert pairs(
        run(checker, [ev("charged", 0), ev("refunded", 49 * H)], selects=(CHARGE, REFUND))
    ) == [
        (1, "'refunded' happened 49h after 'charged' (limit 48h)"),
    ]
    open_events = [ev("charged", 0), ev("note", H)]
    assert (
        run(checker, open_events, selects=(CHARGE, REFUND), trace_end=T0 + timedelta(hours=48))
        == []
    )
    assert pairs(
        run(checker, open_events, selects=(CHARGE, REFUND), trace_end=T0 + timedelta(hours=49))
    ) == [
        (1, "'refunded' did not happen within 48h after 'charged'"),
    ]


def test_every_followed_within_one_completion_closes_all_and_reset_cancels():
    checker = {
        "id": "check",
        "type": "every_followed_within",
        "start": "charge",
        "by": "refund",
        "within": "PT48H",
        "since": RESET,
    }
    events = [ev("charged", 0), ev("charged", H), ev("refunded", 50 * H)]
    assert [finding.index for finding in run(checker, events, selects=(CHARGE, REFUND))] == [2]
    assert (
        run(
            checker,
            [ev("charged", 0), ev("reset", H), ev("note", 60 * H)],
            selects=(CHARGE, REFUND),
        )
        == []
    )


def test_sum_compare_final_totals_and_missing_or_non_numeric_values():
    checker = {
        "id": "check",
        "type": "sum_compare",
        "left": {"of": "refund", "field": "amount"},
        "op": "le",
        "right": {"of": "charge", "field": "amount"},
    }
    events = [ev("refunded", 0, amount=10), ev("charged", 1, amount=10)]
    assert run(checker, events, selects=(CHARGE, REFUND)) == []  # final totals, not prefixes
    failed = [ev("refunded", 0, amount=11), ev("charged", 1, amount=10)]
    assert pairs(run(checker, failed, selects=(CHARGE, REFUND))) == [
        (1, "sum of refund.amount (11) is not le sum of charge.amount (10)"),
    ]
    missing = [ev("refunded", 0, amount=5), ev("charged", 1), ev("charged", 2, amount="bad")]
    assert pairs(run(checker, missing, selects=(CHARGE, REFUND))) == [
        (2, "sum of refund.amount (5) is not le sum of charge.amount (0)"),
    ]


def test_field_compare_checks_each_selected_event_with_both_fields():
    checker = {
        "id": "check",
        "type": "field_compare",
        "of": "charge",
        "a": "a",
        "op": "ne",
        "b": "b",
    }
    events = [
        ev("charged", 0, a="alice", b="bob"),
        ev("charged", 1, a="alice", b="alice"),
        ev("charged", 2, a="alice"),
    ]
    assert pairs(run(checker, events)) == [(1, "'a' is not ne 'b'")]
    assert run(checker, [events[0]]) == []


def test_all_of_prefixes_sorts_and_deduplicates_child_findings():
    count = {"id": "limit", "type": "count", "of": "charge", "op": "le", "value": 0}
    all_of = {"id": "check", "type": "all_of", "children": ["limit", "limit"]}
    findings = run(all_of, [ev("charged", 0), ev("charged", 1)], extra=(count,))
    assert pairs(findings) == [
        (0, "[limit] 'charged' happened 1 times"),
        (1, "[limit] 'charged' happened 2 times"),
    ]
    assert run(all_of, [ev("note", 0)], extra=(count,)) == []
