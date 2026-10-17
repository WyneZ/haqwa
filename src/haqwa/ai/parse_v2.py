"""English rule -> Gemini -> validated core `RuleV2` (+ its plain-English meaning).

One Gemini call per rule. Gemini only interprets the text; it never decides pass/fail and
never writes the owner-facing meaning: `render_v2` writes that from the validated rule.

Prompt design:
- The node catalogue is short and closed (the eight `RuleV2` node types).
- Worked examples are GENERATED from code (`expand_v1` -> `from_rule_v2`), so they can
  never drift from the real model. They use a neutral HR vocabulary and the prompt says
  not to copy their names; `to_rule_v2` rejects any name outside the caller's vocabulary.
- "Prefer the simplest shape": the four presets come first, so a plain rule gets the
  same small structure the golden corpus proved equal to v1.

No automatic retry on a bad answer: a second call costs quota and can hide a prompt
problem. `ParseError.problems` goes back to the caller (web shows it; the owner can
rephrase).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import timedelta
from typing import Literal

from pydantic import BaseModel

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
    suggest_rule_id,
)

from .client import GeminiClient
from .render_v2 import render_rule
from .rule_wire import WireCondition, WireRule, from_rule_v2, to_rule_v2, wire_node, wire_schema
from .vocab import Vocabulary


class ParseV2Outcome(BaseModel):
    """Result of `parse_v2` for one rule text."""

    source: str
    status: Literal["supported", "unsupported"]
    rule: RuleV2 | None = None
    meaning: str | None = None  # render_v2 text the owner confirms; None if unsupported
    reason: str | None = None  # why unsupported
    cached: bool = False


def parse_v2(
    rule_text: str,
    *,
    vocab: Vocabulary,
    client: GeminiClient,
    rule_id: str | None = None,
    existing_ids: Iterable[str] = (),
) -> ParseV2Outcome:
    """Turn one English rule into a validated `RuleV2`.

    Args:
        rule_text: The owner's rule in English.
        vocab: Allowed events, fields, closed values and numeric fields.
        client: Gemini client (pass a fake in tests).
        rule_id: Keep an id the owner already has. When omitted, core suggests one.
        existing_ids: Ids already used in the spec, so a suggested id is unique.

    Raises:
        ParseError: Gemini's answer breaks the wire rules or `validate_rule_v2`.
        GeminiError: quota, availability or bad JSON (see `client.py`).
    """
    if rule_id is None:
        rule_id = suggest_rule_id(rule_text, existing_ids)
    result = client.generate(build_prompt(rule_text, vocab), wire_schema(vocab))
    parsed = to_rule_v2(result.value, rule_id=rule_id, source=rule_text, vocab=vocab)
    if isinstance(parsed, UnsupportedRule):
        return ParseV2Outcome(
            source=rule_text, status="unsupported", reason=parsed.reason, cached=result.cached
        )
    return ParseV2Outcome(
        source=rule_text,
        status="supported",
        rule=parsed,
        meaning=render_rule(parsed),
        cached=result.cached,
    )


# ---- prompt ---------------------------------------------------------------------------

_NODES = """Node types (exactly these 8). Fill only the fields listed for the type.
Checking nodes reference select nodes by id.
- select(event, where, exclude): picks events by name.
    where: conditions every picked event must meet (a filter, e.g. amount gt 1000).
    exclude: exemptions; an event matching ANY of them is ignored by the rule.
- count(of, op, value, since): number of `of` events per entity; op is le, lt, eq or ge.
- none_after(of, after, since): once an `after` event happened, `of` must never happen.
- every_preceded_by(of, by, since): every `of` needs an earlier `by` (one `by` is enough
    for many later `of`).
- every_followed_within(start, by, within_seconds, since): every `start` must be followed
    by a `by` within `within_seconds` of elapsed calendar time (24 hours = 86400,
    90 minutes = 5400). Business days, calendar months or clock times ("by 5pm") are not
    elapsed time: set unsupported_reason for them.
- sum_compare(left_of, left_field, op, right_of, right_field): compares final totals of a
    numeric field, e.g. total refunded amount le total charged amount.
- field_compare(of, a, op, b): on every `of` event, field a eq/ne field b
    (e.g. approver ne requester).
- all_of(children): every child checking node must hold (use for "and").
since: events that reset the checking node for the entity (e.g. a refund resets "charged
at most once"). Conditions: {field, op, value} with op eq, ne, gt, ge, lt, le, or
{field, op: "in", values: [...]}. Values are text; numbers as digits."""

_SHAPE_RULES = """Rules for the answer:
1. Prefer the SIMPLEST shape. If one of the first four example shapes fits, use it.
2. Flat list: every node has a unique id; references use ids; `root` is the checking node
   that decides pass/fail (never a select node). Every node must be reachable from root.
3. At most 3 levels from root to the deepest node. There is no "or" and no "not":
   if the rule needs them, set unsupported_reason instead of approximating.
4. Use ONLY the event names, fields and values listed for this system. Never invent names.
   `per` is the field that identifies the entity the rule is about (e.g. an order id).
5. If no combination of nodes expresses the rule exactly, set unsupported_reason and leave
   per, root and nodes empty. Do not drop parts of the rule to make it fit."""


def build_prompt(rule_text: str, vocab: Vocabulary) -> str:
    """The parse_v2 prompt for one rule (deterministic: same inputs, same text)."""
    values = vocab.values_text() or "(none)"
    numeric = ", ".join(vocab.numeric_fields) or "(none)"
    return f"""Translate one English business rule into a checkable rule.

{_NODES}

{_SHAPE_RULES}

Worked examples (they use a DIFFERENT system's names; never copy those names):
{_examples_text()}

This system:
Events: {", ".join(vocab.events)}
Fields: {", ".join(vocab.fields)}
Fields with a fixed value list (use only these values): {values}
Numeric fields (only these can be summed or compared with gt/ge/lt/le): {numeric}

Rule: "{rule_text}"
"""


# Neutral example vocabulary (HR expenses), unlike the shop demo.
_EX_COMMON = {"id": "example", "source": "example", "per": "claim_id"}


def _examples() -> list[tuple[str, WireRule]]:
    presets = [
        (
            "A claim can be paid at most once (a reversal allows paying again; "
            "test claims are ignored).",
            AtMostOnce(
                **_EX_COMMON,
                pattern="at_most_once",
                event="paid",
                exceptions=[
                    ResetAfter(reset_after="reversed"),
                    AllowIf(allow_if=Condition(field="kind", op="eq", value="test")),
                ],
            ),
        ),
        (
            "Once a claim is withdrawn it must never be paid.",
            NeverAfter(**_EX_COMMON, pattern="never_after", event="paid", after="withdrawn"),
        ),
        (
            "A claim may only be paid after it was approved.",
            MustPrecede(**_EX_COMMON, pattern="must_precede", event="paid", requires="approved"),
        ),
        (
            "Every submitted claim must be decided within 72 hours.",
            WithinTime(
                **_EX_COMMON,
                pattern="within_time",
                start="submitted",
                event="decided",
                within=timedelta(hours=72),
            ),
        ),
    ]
    out = [(text, from_rule_v2(expand_v1(rule))) for text, rule in presets]

    composed = WireRule(
        per="claim_id",
        root="check",
        nodes=[
            wire_node(id="approvals", type="select", event="approved"),
            wire_node(id="payments", type="select", event="paid"),
            wire_node(
                id="big",
                type="select",
                event="paid",
                where=[WireCondition(field="amount", op="gt", value="5000")],
            ),
            wire_node(
                id="four_eyes",
                type="field_compare",
                of="approvals",
                a="approver",
                op="ne",
                b="submitter",
            ),  # fmt: skip
            wire_node(
                id="cap",
                type="sum_compare",
                left_of="payments",
                left_field="amount",
                op="le",
                right_of="approvals",
                right_field="amount",
            ),
            wire_node(id="big_once", type="count", of="big", op="le", value=1),
            wire_node(id="check", type="all_of", children=["four_eyes", "cap", "big_once"]),
        ],
    )
    out.append(
        (
            "The approver must not be the submitter, total paid must not exceed total "
            "approved, and a claim gets at most one payment above 5000.",
            composed,
        )
    )
    out.append(
        (
            "Pay the claim in the employee's favourite currency.",
            WireRule(unsupported_reason="no event or field describes a favourite currency"),
        )
    )
    return out


def _examples_text() -> str:
    blocks = []
    for text, wire in _examples():
        answer = json.dumps(wire.model_dump(exclude_defaults=True), separators=(",", ":"))
        blocks.append(f'Rule: "{text}"\nAnswer: {answer}')
    return "\n\n".join(blocks)
