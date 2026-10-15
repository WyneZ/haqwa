"""Static v2 model tests; no interpreter or v1 wiring."""

import re
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from haqwa.core.rules_v2 import RuleV2, validate_rule_v2

SELECT = {"id": "a", "type": "select", "event": "charged", "where": [], "exclude": []}
SELECT_B = {"id": "b", "type": "select", "event": "refunded", "where": [], "exclude": []}
COUNT = {"id": "check", "type": "count", "of": "a", "op": "le", "value": 1, "since": []}
EVENTS = {"charged", "refunded", "reset"}
FIELDS = {"order_id", "amount", "approver", "requester", "payment_type"}
NUMERIC = {"amount"}


def rule(nodes, root="check"):
    return {
        "id": "sample",
        "source": "Sample policy",
        "per": "order_id",
        "version": 2,
        "nodes": nodes,
        "root": root,
    }


def problems(data, *, events=EVENTS, fields=FIELDS, numeric=NUMERIC):
    return validate_rule_v2(data, events, fields, numeric)


@pytest.mark.parametrize(
    ("node", "extras"),
    [
        (SELECT, [COUNT]),
        (COUNT, [SELECT]),
        ({"id": "check", "type": "none_after", "of": "a", "after": "b"}, [SELECT, SELECT_B]),
        (
            {"id": "check", "type": "every_preceded_by", "of": "a", "by": "b"},
            [SELECT, SELECT_B],
        ),
        (
            {
                "id": "check",
                "type": "every_followed_within",
                "start": "a",
                "by": "b",
                "within": "PT48H",
            },
            [SELECT, SELECT_B],
        ),
        (
            {
                "id": "check",
                "type": "sum_compare",
                "left": {"of": "a", "field": "amount"},
                "op": "le",
                "right": {"of": "b", "field": "amount"},
            },
            [SELECT, SELECT_B],
        ),
        (
            {
                "id": "check",
                "type": "field_compare",
                "of": "a",
                "a": "approver",
                "op": "ne",
                "b": "requester",
            },
            [SELECT],
        ),
        (
            {"id": "check", "type": "all_of", "children": ["limit"]},
            [SELECT, {**COUNT, "id": "limit"}],
        ),
    ],
)
def test_each_node_type_valid(node, extras):
    nodes = [node, *extras] if node.get("id") != "a" else [*extras, node]
    root = node["id"] if node["id"] != "a" else "check"
    assert problems(rule(nodes, root)) == []


@pytest.mark.parametrize(
    ("node", "fragment"),
    [
        ({**SELECT, "exclude": [{"field": "amount", "op": "gt", "value": 1}]}, "exclude"),
        ({**COUNT, "op": "gt"}, "op"),
        ({"id": "check", "type": "none_after", "of": "a", "after": 3}, "after"),
        ({"id": "check", "type": "every_preceded_by", "of": "a"}, "by"),
        (
            {
                "id": "check",
                "type": "every_followed_within",
                "start": "a",
                "by": "b",
                "within": "PT0S",
            },
            "within",
        ),
        (
            {
                "id": "check",
                "type": "sum_compare",
                "left": {"of": "a", "field": "amount"},
                "op": "le",
            },
            "right",
        ),
        (
            {
                "id": "check",
                "type": "field_compare",
                "of": "a",
                "a": "approver",
                "op": "lt",
                "b": "requester",
            },
            "op",
        ),
        ({"id": "check", "type": "all_of", "children": []}, "all_of"),
    ],
)
def test_each_node_type_rejects_bad_input(node, fragment):
    nodes = [node, COUNT] if node["type"] == "select" else [SELECT, SELECT_B, node]
    assert any(fragment in problem for problem in problems(rule(nodes)))


@pytest.mark.parametrize(
    ("data", "fragment"),
    [
        (rule([SELECT, {**COUNT, "of": "missing"}]), "unknown node id"),
        (rule([SELECT, SELECT, COUNT]), "duplicate node ids"),
        (rule([SELECT, COUNT], root="missing"), "root 'missing' is missing"),
        (rule([SELECT, COUNT], root="a"), "root must be a checking node"),
        (
            rule([SELECT, COUNT, {"id": "extra", "type": "all_of", "children": ["check"]}]),
            "unreachable nodes",
        ),
        (rule([SELECT, {"id": "check", "type": "all_of", "children": ["check"]}]), "cycle"),
        (
            rule(
                [
                    SELECT,
                    COUNT,
                    {"id": "middle", "type": "all_of", "children": ["check"]},
                    {"id": "top", "type": "all_of", "children": ["middle"]},
                ],
                root="top",
            ),
            "depth exceeds 3",
        ),
        (rule([{**SELECT, "event": "unknown"}, COUNT]), "unknown event"),
        (
            rule([{**SELECT, "where": [{"field": "missing", "op": "eq", "value": "x"}]}, COUNT]),
            "unknown field",
        ),
        (
            rule([{**SELECT, "where": [{"field": "payment_type", "op": "gt", "value": 1}]}, COUNT]),
            "not numeric",
        ),
        (
            rule([{**SELECT, "where": [{"field": "amount", "op": "gt", "value": "1"}]}, COUNT]),
            "numeric value",
        ),
        (rule([SELECT, {**COUNT, "since": ["missing"]}]), "unknown reset event"),
        (rule([SELECT, {**COUNT, "of": "check"}]), "not a select node"),
        (
            rule([SELECT, {"id": "check", "type": "all_of", "children": ["a"]}]),
            "not a checking node",
        ),
        (rule([SELECT, COUNT]) | {"per": "missing"}, "unknown entity field"),
        (
            rule(
                [
                    SELECT,
                    {
                        "id": "check",
                        "type": "sum_compare",
                        "left": {"of": "a", "field": "payment_type"},
                        "op": "le",
                        "right": {"of": "a", "field": "amount"},
                    },
                ]
            ),
            "not numeric",
        ),
        (
            rule(
                [
                    SELECT,
                    {
                        "id": "check",
                        "type": "field_compare",
                        "of": "a",
                        "a": "missing",
                        "op": "ne",
                        "b": "requester",
                    },
                ]
            ),
            "unknown field",
        ),
        (rule([SELECT, {"id": "check", "type": "all_of", "children": []}]), "all_of"),
    ],
)
def test_validator_rejects_invalid_graph_or_vocabulary(data, fragment):
    assert any(fragment in problem for problem in problems(data))


def test_rule_model_rejects_unknown_node_and_wrong_version():
    with pytest.raises(ValidationError):
        RuleV2.model_validate(rule([{"id": "x", "type": "python", "code": "pass"}], "x"))
    with pytest.raises(ValidationError):
        RuleV2.model_validate(rule([SELECT, COUNT]) | {"version": 1})


def test_select_accepts_v1_exclusions_including_two_conditions():
    selected = {
        **SELECT,
        "exclude": [
            {"field": "payment_type", "op": "ne", "value": "i"},
            {"field": "payment_type", "op": "in", "value": ["i", "h"]},
            {"field": "amount", "op": "in", "value": [0, 50]},
        ],
    }
    assert problems(rule([selected, COUNT])) == []


def test_depth_checks_each_path_to_a_shared_node():
    data = rule(
        [
            SELECT,
            {**COUNT, "id": "limit"},
            {"id": "middle", "type": "all_of", "children": ["limit"]},
            {"id": "check", "type": "all_of", "children": ["limit", "middle"]},
        ]
    )
    assert any("depth exceeds 3" in problem for problem in problems(data))


def test_count_rejects_negative_limit():
    assert any(
        "greater than or equal to 0" in problem
        for problem in problems(rule([SELECT, {**COUNT, "value": -1}]))
    )


def test_four_deep_all_of_chain_has_no_false_unreachable_nodes():
    nodes = [SELECT, COUNT]
    child = "check"
    for index in range(4):
        node_id = f"chain-{index}"
        nodes.append({"id": node_id, "type": "all_of", "children": [child]})
        child = node_id
    assert problems(rule(nodes, root=child)) == ["node depth exceeds 3"]


def test_four_design_doc_presets_round_trip_through_yaml():
    design = Path(__file__).resolve().parents[2] / "docs/design/composable-rules.md"
    blocks = re.findall(
        r"```yaml\n# (at_most_once|never_after|must_precede|within_time)\([^\n]*\)\n(.*?)\n```",
        design.read_text(encoding="utf-8"),
        flags=re.DOTALL,
    )
    assert len(blocks) == 4
    for pattern, body in blocks:
        data = {
            "id": pattern.replace("_", "-"),
            "source": pattern,
            "per": "order_id",
            "version": 2,
            **yaml.safe_load(body),
        }
        original = RuleV2.model_validate(data)
        events = {node.event for node in original.nodes if node.type == "select"}
        assert problems(original, events=events, fields={"order_id"}, numeric=set()) == []
        dumped = yaml.safe_dump(original.model_dump(mode="json"), sort_keys=False)
        restored = RuleV2.model_validate(yaml.safe_load(dumped))
        assert restored == original
