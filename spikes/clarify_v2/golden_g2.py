"""G2 decision classes from spikes/clarify/golden.md; independent of Gemini wording.

The dry-run parse fixtures come from G1; the six expected business choices come
from the policy owner's existing golden list. No example proves patch semantics.
"""

from __future__ import annotations

from haqwa.ai.clarify_v2 import AddExclude, AddReset, Patch
from haqwa.core.rules_v2 import RuleV2, SelectNode
from spikes.rule_ast.golden_v2 import GOLDEN, SYSTEMS

SHOP = SYSTEMS["shop"]
RULES = {f"R{gid[1:]}": (text, wire) for gid, _, text, wire in GOLDEN if gid in {"g1", "g2", "g3"}}
EXPECTED_IDS = {
    "R1": ["G1.1", "G1.2", "G1.7"],
    "R2": ["G2.1"],
    "R3": ["G3.2", "G3.5", "G3.6"],
}


def expected_patches(rule_id: str, rule: RuleV2) -> dict[str, Patch]:
    """Resolve expected patches against parsed ids, not fixture or Gemini ids."""
    nodes = {n.id: n for n in rule.nodes}
    check = nodes[rule.root]
    expected_types = {"R1": "count", "R2": "none_after", "R3": "every_followed_within"}
    if rule.per != "order_id" or check.type != expected_types[rule_id]:
        raise ValueError("parsed rule has the wrong entity or checking shape for this golden")
    roles = {"R1": ["of"], "R2": ["of", "after"], "R3": ["start", "by"]}[rule_id]
    selectors = [nodes[getattr(check, role)] for role in roles]
    events = {
        "R1": ["charged"],
        "R2": ["shipped", "cancelled"],
        "R3": ["refund_requested", "refund_completed"],
    }[rule_id]
    if any(not isinstance(n, SelectNode) for n in selectors):
        raise ValueError("expected select nodes for the parsed checking node")
    if [n.event for n in selectors] != events:
        raise ValueError("parsed rule references the wrong events for this golden")

    def reset(event: str) -> AddReset:
        return AddReset(op="add_reset", node_id=check.id, event=event)

    def exclude() -> AddExclude:
        return AddExclude.model_validate(
            {
                "op": "add_exclude",
                "select_ids": [n.id for n in selectors],
                "condition": {"field": "payment_type", "op": "eq", "value": "installment"},
            }
        )

    if rule_id == "R1":
        return {"G1.1": reset("refunded"), "G1.2": exclude(), "G1.7": reset("cancelled")}
    if rule_id == "R2":
        return {"G2.1": reset("order_created")}
    return {"G3.2": reset("refund_requested"), "G3.5": reset("cancelled"), "G3.6": exclude()}
