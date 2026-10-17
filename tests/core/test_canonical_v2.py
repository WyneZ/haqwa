"""V2 boundary cards, separating witnesses and restart-on-start behavior."""

from datetime import timedelta

import pytest

from haqwa.core import apply_patch_v2, canonical_examples_v2, make_example_v2
from haqwa.core.events import synthetic_timeline
from haqwa.core.rules_v2 import RuleV2
from haqwa.core.rules_v2_eval import check_v2


def _rule(check, selects, *, root="check"):
    return RuleV2.model_validate(
        {
            "id": "example-rule",
            "source": "Example policy",
            "per": "order_id",
            "version": 2,
            "nodes": [*selects, check],
            "root": root,
        }
    )


def _select(node_id, event, **extra):
    return {"id": node_id, "type": "select", "event": event, **extra}


def _verdict(rule, example):
    events = synthetic_timeline(
        ((item.event, item.data, item.at) for item in example.timeline), per=rule.per
    )
    return bool(check_v2(rule, events))


COUNT = {"id": "check", "type": "count", "of": "target", "op": "le", "value": 1}
NONE_AFTER = {"id": "check", "type": "none_after", "of": "target", "after": "other"}
PRECEDED = {"id": "check", "type": "every_preceded_by", "of": "target", "by": "other"}
FOLLOWED = {
    "id": "check",
    "type": "every_followed_within",
    "start": "target",
    "by": "other",
    "within": "PT1H",
}
SUM = {
    "id": "check",
    "type": "sum_compare",
    "left": {"of": "target", "field": "amount"},
    "op": "le",
    "right": {"of": "other", "field": "amount"},
}
FIELD = {"id": "check", "type": "field_compare", "of": "target", "a": "a", "op": "eq", "b": "b"}


@pytest.mark.parametrize("check", (COUNT, NONE_AFTER, PRECEDED, FOLLOWED, SUM, FIELD))
def test_each_node_type_has_allowed_and_violation_cards(check):
    rule = _rule(check, [_select("target", "charged"), _select("other", "refunded")])
    examples = canonical_examples_v2(rule)
    assert 1 <= len(examples) <= 3
    assert {example.violation for example in examples} == {False, True}
    assert all(example.violation == _verdict(rule, example) for example in examples)
    assert all(example.label and example.label[0].isupper() for example in examples)


@pytest.mark.parametrize(
    ("op", "value"),
    (("le", 0), ("le", 2), ("lt", 2), ("eq", 2), ("ge", 2)),
)
def test_count_boundaries_respect_operator(op, value):
    rule = _rule({**COUNT, "op": op, "value": value}, [_select("target", "charged")])
    examples = canonical_examples_v2(rule)
    assert {example.violation for example in examples} == {False, True}
    assert all(example.violation == _verdict(rule, example) for example in examples)


@pytest.mark.parametrize("op", ("eq", "ne", "lt", "le", "gt", "ge"))
def test_sum_comparison_boundaries_respect_operator(op):
    rule = _rule({**SUM, "op": op}, [_select("target", "charged"), _select("other", "refunded")])
    assert {example.violation for example in canonical_examples_v2(rule)} == {False, True}


def test_where_and_exclude_are_satisfied_in_example_data():
    target = _select(
        "target",
        "charged",
        where=[
            {"field": "kind", "op": "eq", "value": "charge"},
            {"field": "amount", "op": "gt", "value": 10},
        ],
        exclude=[{"field": "channel", "op": "in", "value": ["internal"]}],
    )
    rule = _rule(COUNT, [target])
    examples = canonical_examples_v2(rule)
    assert {example.violation for example in examples} == {False, True}
    for example in examples:
        for item in example.timeline:
            assert item.data["order_id"] == "example-1"
            assert item.data["kind"] == "charge"
            assert item.data["amount"] > 10
            assert item.data["channel"] != "internal"


@pytest.mark.parametrize(
    ("op", "value"),
    (
        ("eq", "approved"),
        ("ne", "blocked"),
        ("in", ["approved", "ready"]),
        ("gt", 10),
        ("ge", 10),
        ("lt", 10),
        ("le", 10),
    ),
)
def test_all_where_operators_generate_selected_events(op, value):
    rule = _rule(
        COUNT,
        [_select("target", "charged", where=[{"field": "status", "op": op, "value": value}])],
    )
    examples = canonical_examples_v2(rule)
    assert {example.violation for example in examples} == {False, True}
    assert all(example.violation == _verdict(rule, example) for example in examples)


def test_all_of_cards_are_capped_and_use_root_verdict():
    rule = RuleV2.model_validate(
        {
            "id": "joined",
            "source": "Two checks",
            "per": "order_id",
            "version": 2,
            "nodes": [
                _select("target", "charged"),
                _select("other", "refunded"),
                {**COUNT, "id": "limit"},
                {**FIELD, "id": "fields"},
                {"id": "check", "type": "all_of", "children": ["limit", "fields"]},
            ],
            "root": "check",
        }
    )
    examples = canonical_examples_v2(rule)
    assert len(examples) <= 3
    assert all(example.violation == _verdict(rule, example) for example in examples)


def test_start_event_that_is_a_reset_restarts_deadline():
    base = _rule(FOLLOWED, [_select("target", "started"), _select("other", "finished")])
    restart = base.model_copy(
        update={
            "nodes": [
                *base.nodes[:-1],
                base.nodes[-1].model_copy(update={"since": ["started"]}),
            ]
        }
    )
    timeline = [
        ("started", {}, timedelta(0)),
        ("started", {}, timedelta(minutes=30)),
        ("finished", {}, timedelta(minutes=90)),
    ]
    assert check_v2(base, synthetic_timeline(timeline, per=base.per))
    assert not check_v2(restart, synthetic_timeline(timeline, per=restart.per))
    late = [*timeline[:-1], ("finished", {}, timedelta(minutes=91))]
    assert check_v2(restart, synthetic_timeline(late, per=restart.per))


@pytest.mark.parametrize("check", (COUNT, NONE_AFTER, PRECEDED, FOLLOWED))
def test_reset_witness_changes_verdict(check):
    rule = _rule(check, [_select("target", "charged"), _select("other", "refunded")])
    patch = {"op": "add_reset", "node_id": "check", "event": "cancelled"}
    witness = make_example_v2(rule, patch)
    assert witness is not None
    assert witness.violation == _verdict(rule, witness)
    assert witness.violation != _verdict(apply_patch_v2(rule, patch), witness)


@pytest.mark.parametrize(
    "condition",
    (
        {"field": "channel", "op": "eq", "value": "manual"},
        {"field": "channel", "op": "ne", "value": "manual"},
        {"field": "channel", "op": "in", "values": ["manual", "batch"]},
    ),
)
def test_exclusion_witness_changes_verdict(condition):
    rule = _rule(COUNT, [_select("target", "charged")])
    patch = {"op": "add_exclude", "select_ids": ["target"], "condition": condition}
    witness = make_example_v2(rule, patch)
    assert witness is not None
    assert witness.violation
    assert not _verdict(apply_patch_v2(rule, patch), witness)


def test_excluding_follow_up_has_a_separating_witness():
    rule = _rule(FOLLOWED, [_select("target", "started"), _select("other", "finished")])
    patch = {
        "op": "add_exclude",
        "select_ids": ["other"],
        "condition": {"field": "channel", "op": "eq", "value": "manual"},
    }
    witness = make_example_v2(rule, patch)
    assert witness is not None
    assert not witness.violation
    assert _verdict(apply_patch_v2(rule, patch), witness)


def test_sum_boundary_respects_numeric_where():
    rule = _rule(
        SUM,
        [
            _select("target", "charged", where=[{"field": "amount", "op": "gt", "value": 1000}]),
            _select("other", "refunded", where=[{"field": "amount", "op": "gt", "value": 1000}]),
        ],
    )
    assert {example.violation for example in canonical_examples_v2(rule)} == {False, True}


def test_field_comparison_boundary_respects_numeric_where():
    rule = _rule(
        FIELD,
        [_select("target", "charged", where=[{"field": "a", "op": "gt", "value": 1000}])],
    )
    assert {example.violation for example in canonical_examples_v2(rule)} == {False, True}


def test_no_op_patch_has_no_witness():
    rule = _rule(COUNT, [_select("target", "charged")])
    patch = {"op": "add_reset", "node_id": "check", "event": "cancelled"}
    assert make_example_v2(apply_patch_v2(rule, patch), patch) is None
    exclude = {
        "op": "add_exclude",
        "select_ids": ["target"],
        "condition": {"field": "channel", "op": "eq", "value": "manual"},
    }
    assert make_example_v2(apply_patch_v2(rule, exclude), exclude) is None
