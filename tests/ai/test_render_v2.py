"""RuleV2 -> plain English. Exact strings: the owner confirms this text, so wording
changes must be deliberate and visible in review."""

from __future__ import annotations

import pytest

from haqwa.ai.render_v2 import render_rule
from haqwa.ai.rule_wire import WireCondition, WireNode, to_rule_v2
from haqwa.core.presets_v2 import expand_v1
from haqwa.core.rules_v2 import RuleV2

from .test_rule_wire import PRESETS, SHOP, rule, sel


def v2(*nodes: WireNode, root: str = "check") -> RuleV2:
    result = to_rule_v2(rule(*nodes, root=root), rule_id="r1", source="text", vocab=SHOP)
    assert isinstance(result, RuleV2)
    return result


PRESET_TEXT = {
    "at_most_once": (
        "For each order: there must be at most 1 charged event (charged events where payment "
        "type is installment are ignored; it starts again after each refunded event)."
    ),
    "never_after": (
        "For each order: once a cancelled event has happened, a shipped event must never happen."
    ),
    "must_precede": (
        "For each order: every shipped event must come after an earlier charged event "
        "(events where payment type is one of card, installment are ignored)."
    ),
    "within_time": (
        "For each order: every refund requested event must be followed by a refund completed "
        "event within 48 hours."
    ),
}


@pytest.mark.parametrize("v1", PRESETS, ids=lambda r: r.pattern)
def test_presets(v1: object) -> None:
    assert render_rule(expand_v1(v1)) == PRESET_TEXT[v1.pattern]  # type: ignore[attr-defined]


def test_all_of_numbers_each_part() -> None:
    rule_ = v2(
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
    assert render_rule(rule_) == (
        "For each order: all of these must hold: (1) every refunded event must come after an "
        "earlier charged event; (2) the total amount of refunded events must be at most the "
        "total amount of charged events."
    )


def test_count_with_where_filter_and_plural() -> None:
    rule_ = v2(
        sel("big", "charged", where=[WireCondition(field="amount", op="gt", value="1000")]),
        WireNode(id="check", type="count", of="big", op="le", value=3),
    )
    assert render_rule(rule_) == (
        "For each order: there must be at most 3 charged events where amount is more than 1000."
    )


@pytest.mark.parametrize(
    ("op", "words"),
    [("le", "at most"), ("lt", "fewer than"), ("eq", "exactly"), ("ge", "at least")],
)
def test_count_ops(op: str, words: str) -> None:
    rule_ = v2(sel("c", "charged"), WireNode(id="check", type="count", of="c", op=op, value=2))
    assert f"there must be {words} 2 charged events" in render_rule(rule_)


def test_field_compare() -> None:
    rule_ = v2(
        sel("a", "approved"),
        WireNode(id="check", type="field_compare", of="a", a="approver", op="ne", b="requester"),
    )
    assert render_rule(rule_) == (
        "For each order: on every approved event, approver must be different from requester."
    )


def test_exemption_on_one_event_names_it() -> None:
    rule_ = v2(
        sel("s", "shipped", exclude=[WireCondition(field="payment_type", op="eq", value="card")]),
        sel("c", "cancelled"),
        WireNode(id="check", type="none_after", of="s", after="c"),
    )
    assert "(shipped events where payment type is card are ignored)" in render_rule(rule_)


def test_odd_duration_falls_back_to_short_form() -> None:
    rule_ = v2(
        sel("s", "refund_requested"),
        sel("d", "refund_completed"),
        WireNode(id="check", type="every_followed_within", start="s", by="d", within="PT90M"),
    )
    assert "within 1h30m" in render_rule(rule_)


def test_same_rule_same_text() -> None:
    core_rule = expand_v1(PRESETS[0])
    assert render_rule(core_rule) == render_rule(core_rule)
