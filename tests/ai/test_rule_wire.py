"""Wire (Gemini) -> core RuleV2. Pure functions: no Gemini, no quota."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from haqwa.ai.parse import ParseError
from haqwa.ai.rule_wire import (
    WireCondition,
    WireNode,
    WireRule,
    from_rule_v2,
    to_rule_v2,
)
from haqwa.ai.vocab import Vocabulary
from haqwa.core.presets_v2 import expand_v1
from haqwa.core.rules_v2 import RuleV2
from haqwa.core.spec import (
    AllowIf,
    AtMostOnce,
    Condition,
    MustPrecede,
    NeverAfter,
    ResetAfter,
    UnsupportedRule,
    WithinTime,
)

SHOP = Vocabulary(
    events=["order_created", "charged", "refunded", "cancelled", "shipped",
            "refund_requested", "refund_completed", "approved"],
    fields=["order_id", "customer_id", "payment_type", "amount", "approver", "requester"],
    field_values={"payment_type": ["card", "installment"]},
    numeric_fields=["amount"],
)  # fmt: skip


def convert(wire: WireRule) -> RuleV2 | UnsupportedRule:
    return to_rule_v2(wire, rule_id="r1", source="rule text", vocab=SHOP)


def problems_of(wire: WireRule) -> list[str]:
    with pytest.raises(ParseError) as info:
        convert(wire)
    return info.value.problems


def sel(node_id: str, event: str, **kw: Any) -> WireNode:
    return WireNode(id=node_id, type="select", event=event, **kw)


def rule(*nodes: WireNode, root: str = "check", per: str = "order_id") -> WireRule:
    return WireRule(per=per, root=root, nodes=list(nodes))


# ---- positive: the four v1 presets round-trip through the wire format -------------------

COMMON: dict[str, Any] = {"id": "r1", "source": "rule text", "per": "order_id"}
PRESETS = [
    AtMostOnce(
        **COMMON,
        pattern="at_most_once",
        event="charged",
        exceptions=[
            ResetAfter(reset_after="refunded"),
            AllowIf(allow_if=Condition(field="payment_type", op="eq", value="installment")),
        ],
    ),
    NeverAfter(**COMMON, pattern="never_after", event="shipped", after="cancelled"),
    MustPrecede(
        **COMMON,
        pattern="must_precede",
        event="shipped",
        requires="charged",
        exceptions=[
            AllowIf(
                allow_if=Condition(field="payment_type", op="in", value=["card", "installment"])
            )
        ],
    ),
    WithinTime(
        **COMMON,
        pattern="within_time",
        start="refund_requested",
        event="refund_completed",
        within=timedelta(hours=48),
    ),
]


@pytest.mark.parametrize("v1", PRESETS, ids=lambda r: r.pattern)
def test_preset_round_trip(v1: Any) -> None:
    core_rule = expand_v1(v1)
    assert convert(from_rule_v2(core_rule)) == core_rule


# ---- positive: composed rules beyond the four presets -----------------------------------


def test_sum_compare_refunds_not_above_charges() -> None:
    wire = rule(
        sel("refunds", "refunded"),
        sel("charges", "charged"),
        WireNode(
            id="check",
            type="sum_compare",
            left_of="refunds",
            left_field="amount",
            op="le",
            right_of="charges",
            right_field="amount",
        ),
    )
    result = convert(wire)
    assert isinstance(result, RuleV2)
    node = {n.id: n for n in result.nodes}["check"]
    assert (node.left.of, node.op, node.right.field) == ("refunds", "le", "amount")


def test_field_compare_four_eyes() -> None:
    wire = rule(
        sel("approvals", "approved"),
        WireNode(
            id="check", type="field_compare", of="approvals", a="approver", op="ne", b="requester"
        ),
    )
    assert isinstance(convert(wire), RuleV2)


def test_all_of_refund_needs_charge_and_amount_cap() -> None:
    """The spike's r4 rule, written with nodes that exist (depth 2)."""
    wire = rule(
        sel("refunds", "refunded"),
        sel("charges", "charged"),
        WireNode(id="prior", type="every_preceded_by", of="refunds", by="charges"),
        WireNode(
            id="cap",
            type="sum_compare",
            left_of="refunds",
            left_field="amount",
            op="le",
            right_of="charges",
            right_field="amount",
        ),
        WireNode(id="check", type="all_of", children=["prior", "cap"]),
    )
    assert isinstance(convert(wire), RuleV2)


def test_numeric_where_value_becomes_number() -> None:
    wire = rule(
        sel("big", "charged", where=[WireCondition(field="amount", op="gt", value="1000")]),
        WireNode(id="check", type="count", of="big", op="le", value=1),
    )
    result = convert(wire)
    assert isinstance(result, RuleV2)
    select = {n.id: n for n in result.nodes}["big"]
    assert select.where[0].value == 1000
    assert isinstance(select.where[0].value, int)


def test_decimal_value_becomes_float() -> None:
    wire = rule(
        sel("big", "charged", where=[WireCondition(field="amount", op="ge", value="99.5")]),
        WireNode(id="check", type="count", of="big", op="le", value=1),
    )
    select = {n.id: n for n in convert(wire).nodes}["big"]  # type: ignore[union-attr]
    assert select.where[0].value == 99.5


def test_unsupported() -> None:
    result = convert(WireRule(unsupported_reason="needs a running average"))
    assert result == UnsupportedRule(source="rule text", reason="needs a running average")


def test_rule_id_and_source_come_from_caller_not_gemini() -> None:
    wire = rule(sel("c", "charged"), WireNode(id="check", type="count", of="c", op="le", value=1))
    result = to_rule_v2(wire, rule_id="no-double-charge", source="Owner text", vocab=SHOP)
    assert isinstance(result, RuleV2)
    assert (result.id, result.source, result.version) == ("no-double-charge", "Owner text", 2)


# ---- negative: wire-level problems (this module) ----------------------------------------


def test_missing_required_field() -> None:
    wire = rule(sel("c", "charged"), WireNode(id="check", type="count", of="c", op="le"))
    assert "check (count): missing 'value'" in problems_of(wire)


def test_stray_field_is_a_problem_not_dropped() -> None:
    wire = rule(
        sel("c", "charged", since=["refunded"]),  # resets belong on the checking node
        WireNode(id="check", type="count", of="c", op="le", value=1),
    )
    assert any("['since'] do not belong to a select node" in p for p in problems_of(wire))


def test_missing_per_root_nodes() -> None:
    probs = problems_of(WireRule())
    assert {"per: missing", "root: missing", "nodes: empty"} <= set(probs)


def test_unsupported_with_nodes_is_contradictory() -> None:
    wire = rule(sel("c", "charged"), WireNode(id="check", type="count", of="c", op="le", value=1))
    wire.unsupported_reason = "not sure"
    assert "unsupported_reason is set" in problems_of(wire)[0]


def test_non_numeric_value_for_numeric_field() -> None:
    wire = rule(
        sel("big", "charged", where=[WireCondition(field="amount", op="gt", value="a lot")]),
        WireNode(id="check", type="count", of="big", op="le", value=1),
    )
    assert any("needs a number, got 'a lot'" in p for p in problems_of(wire))


def test_closed_value_outside_vocabulary() -> None:
    wire = rule(
        sel("c", "charged", exclude=[WireCondition(field="payment_type", op="eq", value="crypto")]),
        WireNode(id="check", type="count", of="c", op="le", value=1),
    )
    assert any("crypto" in p for p in problems_of(wire))


def test_in_needs_values_list() -> None:
    wire = rule(
        sel("c", "charged", exclude=[WireCondition(field="payment_type", op="in", value="card")]),
        WireNode(id="check", type="count", of="c", op="le", value=1),
    )
    assert any("op 'in' needs 'values'" in p for p in problems_of(wire))


def test_eq_with_values_list_is_a_problem() -> None:
    wire = rule(
        sel(
            "c", "charged", exclude=[WireCondition(field="payment_type", op="eq", values=["card"])]
        ),
        WireNode(id="check", type="count", of="c", op="le", value=1),
    )
    assert any("op 'eq' needs 'value'" in p for p in problems_of(wire))


# ---- negative: core validator problems surface unchanged --------------------------------


def test_duplicate_ids() -> None:
    wire = rule(
        sel("c", "charged"),
        sel("c", "refunded"),
        WireNode(id="check", type="count", of="c", op="le", value=1),
    )
    assert any("duplicate node ids" in p for p in problems_of(wire))


def test_unknown_reference() -> None:
    wire = rule(
        sel("c", "charged"), WireNode(id="check", type="count", of="nope", op="le", value=1)
    )
    assert any("unknown node id 'nope'" in p for p in problems_of(wire))


def test_cycle() -> None:
    wire = rule(
        WireNode(id="check", type="all_of", children=["other"]),
        WireNode(id="other", type="all_of", children=["check"]),
    )
    assert any("cycle" in p for p in problems_of(wire))


def test_unreachable_node() -> None:
    wire = rule(
        sel("c", "charged"),
        sel("unused", "refunded"),
        WireNode(id="check", type="count", of="c", op="le", value=1),
    )
    assert any("unreachable nodes: ['unused']" in p for p in problems_of(wire))


def test_event_outside_vocabulary() -> None:
    wire = rule(sel("c", "paid"), WireNode(id="check", type="count", of="c", op="le", value=1))
    assert any("unknown event 'paid'" in p for p in problems_of(wire))


def test_sum_of_non_numeric_field() -> None:
    wire = rule(
        sel("a", "refunded"),
        sel("b", "charged"),
        WireNode(
            id="check",
            type="sum_compare",
            left_of="a",
            left_field="customer_id",
            op="le",
            right_of="b",
            right_field="amount",
        ),
    )
    assert any("'customer_id' is not numeric" in p for p in problems_of(wire))


def test_depth_over_three() -> None:
    wire = rule(
        sel("c", "charged"),
        WireNode(id="leaf", type="count", of="c", op="le", value=1),
        WireNode(id="mid", type="all_of", children=["leaf"]),
        WireNode(id="top", type="all_of", children=["mid"]),
        WireNode(id="check", type="all_of", children=["top"]),
    )
    assert any("depth exceeds 3" in p for p in problems_of(wire))


def test_count_with_gt_rejected_by_core() -> None:
    wire = rule(sel("c", "charged"), WireNode(id="check", type="count", of="c", op="gt", value=1))
    assert problems_of(wire)  # core's CountNode allows only le/lt/eq/ge


def test_root_is_select() -> None:
    wire = rule(sel("check", "charged"))
    assert any("root must be a checking node" in p for p in problems_of(wire))


def test_per_outside_vocabulary() -> None:
    wire = rule(
        sel("c", "charged"),
        WireNode(id="check", type="count", of="c", op="le", value=1),
        per="invoice_id",
    )
    assert any("unknown entity field 'invoice_id'" in p for p in problems_of(wire))
