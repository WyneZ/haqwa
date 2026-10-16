"""Typed clarification proposals are tested without Gemini quota or core patch logic."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from haqwa.ai.clarify_v2 import (
    AddExclude,
    AddReset,
    build_decision_prompt,
    decision_schema,
    propose_decisions,
    to_core_patches,
)
from haqwa.ai.client import GeminiBadOutput, GeminiClient
from haqwa.ai.parse import ParseError
from haqwa.ai.render_v2 import render_rule
from haqwa.ai.vocab import Vocabulary
from haqwa.core.canonical import CanonicalExample
from haqwa.core.rules_v2 import RuleV2
from haqwa.core.spec import TimelineEvent

from .test_parse_v2 import FakeSDK

SHOP = Vocabulary(
    events=["charged", "refunded", "cancelled", "refund_requested", "refund_completed"],
    fields=["order_id", "payment_type", "amount"],
    field_values={"payment_type": ["card", "installment"]},
    numeric_fields=["amount"],
)
EXAMPLE = CanonicalExample(
    label="Injected example, not a core-generated boundary",
    timeline=(TimelineEvent(event="charged"),),
    violation=True,
)


def rule(*, deadline: bool = False) -> RuleV2:
    """Build a validated count or deadline fixture with distinct target ids."""
    nodes = (
        [
            {"id": "request", "type": "select", "event": "refund_requested"},
            {"id": "completion", "type": "select", "event": "refund_completed"},
            {
                "id": "check",
                "type": "every_followed_within",
                "start": "request",
                "by": "completion",
                "within": "PT24H",
            },
        ]
        if deadline
        else [
            {"id": "charges", "type": "select", "event": "charged"},
            {"id": "check", "type": "count", "of": "charges", "op": "le", "value": 1},
        ]
    )
    return RuleV2.model_validate(
        {
            "id": "r1",
            "source": "No double charge",
            "version": 2,
            "per": "order_id",
            "root": "check",
            "nodes": nodes,
        }
    )


def reset(node_id: str = "check", event: str = "refunded") -> dict[str, Any]:
    """Build a wire reset proposal."""
    return {"op": "add_reset", "node_id": node_id, "event": event}


def exclude(**changes: Any) -> dict[str, Any]:
    """Build an installment exemption proposal."""
    return {
        "op": "add_exclude",
        "select_ids": ["charges"],
        "condition": {"field": "payment_type", "op": "eq", "value": "installment"},
        **changes,
    }


def proposal(patch: dict[str, Any], gid: str = "proposal") -> dict[str, Any]:
    """Wrap one patch in an owner-facing decision."""
    return {
        "id": gid,
        "question": "Should this exception be allowed?",
        "why": "The owner must decide this business exception.",
        "patch": patch,
    }


def run(proposals: list[dict[str, Any]], *, target: RuleV2 | None = None, example=EXAMPLE):
    """Exercise the real client and dynamic response validation with a fake SDK."""
    sdk = FakeSDK({"decisions": proposals})
    seen = []

    def make_example(original, patch):
        seen.append((original, patch))
        return example

    outcome = propose_decisions(
        target or rule(),
        vocab=SHOP,
        client=GeminiClient(model="test", sdk=sdk, cache_dir=None),
        make_example=make_example,
    )
    return outcome, sdk, seen


def test_keeps_reset_and_exclude_without_changing_rule() -> None:
    original = rule()
    snapshot = original.model_dump_json()
    result, sdk, seen = run([proposal(reset(), "a"), proposal(exclude(), "b")], target=original)
    assert len(sdk.prompts) == 1
    assert len(result.decisions) == len(seen) == 2
    assert not result.dropped and not result.cached
    assert result.rule == original and original.model_dump_json() == snapshot
    assert result.meaning == render_rule(original)
    assert result.decisions[0].example == EXAMPLE
    assert [d.id for d in result.decisions] == ["d1", "d2"]


@pytest.mark.parametrize(
    "patch",
    [
        reset("charges"),
        reset(event="invented"),
        reset("missing"),
        exclude(select_ids=["check"]),
        exclude(select_ids=["missing"]),
        exclude(select_ids=[]),
        exclude(select_ids=["charges", "charges"]),
        exclude(condition={"field": "payment_type", "op": "eq", "value": "store_credit"}),
        exclude(condition={"field": "amount", "op": "eq", "value": "100"}),
        exclude(condition={"field": "invented", "op": "eq", "value": "installment"}),
        exclude(condition={"field": "payment_type", "op": "in", "values": ["store_credit"]}),
        exclude(condition={"field": "payment_type", "op": "eq", "value": "card,installment"}),
        exclude(condition={"field": "payment_type", "op": "in", "values": []}),
        {"op": "add_reset", "node_id": "check"},
    ],
)
def test_bad_proposal_is_dropped_without_losing_valid_sibling(patch) -> None:
    outcome, _, seen = run([proposal(patch, "bad"), proposal(reset(), "good")])
    assert len(outcome.decisions) == 1 and len(seen) == 1
    assert outcome.dropped[0].gemini_id == "bad"
    assert outcome.dropped[0].reasons


def test_duplicate_patch_is_dropped_even_with_different_question_id() -> None:
    result, _, _ = run([proposal(reset(), "a"), proposal(reset(), "b")])
    assert len(result.decisions) == 1
    assert "duplicate" in " ".join(result.dropped[0].reasons)


def test_equivalent_singleton_in_and_eq_are_duplicates() -> None:
    second = exclude(condition={"field": "payment_type", "op": "in", "values": ["installment"]})
    result, _, _ = run([proposal(exclude(), "a"), proposal(second, "b")])
    assert len(result.decisions) == 1
    assert result.dropped


@pytest.mark.parametrize("kind", ["reset", "exclude"])
def test_noop_is_dropped(kind) -> None:
    original = rule()
    if kind == "reset":
        original.nodes[-1].since.append("refunded")
        patch = reset()
    else:
        from haqwa.core.rules_v2 import ConditionV2

        original.nodes[0].exclude.append(
            ConditionV2(field="payment_type", op="eq", value="installment")
        )
        patch = exclude()
    result, _, seen = run([proposal(patch)], target=original)
    assert not result.decisions and not seen
    assert "already present" in " ".join(result.dropped[0].reasons)


def test_no_separating_example_is_dropped() -> None:
    result, _, _ = run([proposal(reset())], example=None)
    assert not result.decisions
    assert "separat" in " ".join(result.dropped[0].reasons)


def test_zero_decisions_is_valid() -> None:
    result, _, seen = run([])
    assert not result.decisions and not result.dropped and not seen


def test_schema_has_rule_specific_enums_and_no_provider_incompatible_features() -> None:
    schema = decision_schema(rule(deadline=True), SHOP).model_json_schema()
    definitions = schema["$defs"]
    reset_schema = next(v for v in definitions.values() if "node_id" in v.get("properties", {}))
    exclude_schema = next(
        v for v in definitions.values() if "select_ids" in v.get("properties", {})
    )
    target = reset_schema["properties"]["node_id"]
    assert target.get("enum", [target.get("const")]) == ["check"]
    assert set(exclude_schema["properties"]["select_ids"]["items"]["enum"]) == {
        "request",
        "completion",
    }
    assert set(reset_schema["required"]) == {"op", "node_id", "event"}
    assert schema["properties"]["decisions"]["maxItems"] == 3
    text = json.dumps(schema)
    assert "oneOf" not in text and "additionalProperties" not in text
    assert "anyOf" in text


def test_schema_without_resettable_nodes_omits_reset_branch() -> None:
    original = RuleV2.model_validate(
        {
            "id": "fields",
            "source": "Different fields",
            "version": 2,
            "per": "order_id",
            "root": "check",
            "nodes": [
                {"id": "charges", "type": "select", "event": "charged"},
                {
                    "id": "check",
                    "type": "field_compare",
                    "of": "charges",
                    "a": "order_id",
                    "op": "ne",
                    "b": "payment_type",
                },
            ],
        }
    )
    assert '"add_reset"' not in json.dumps(decision_schema(original, SHOP).model_json_schema())


def test_schema_caps_decisions_at_three() -> None:
    with pytest.raises(ValidationError):
        decision_schema(rule(), SHOP).model_validate({"decisions": [proposal(reset())] * 4})


def test_prompt_is_deterministic_and_has_meaning_targets_and_noise_controls() -> None:
    prompt = build_decision_prompt(rule(), SHOP)
    assert prompt == build_decision_prompt(rule(), SHOP)
    for text in [
        render_rule(rule()),
        "charges",
        "count",
        "calendar hours",
        "confirmation",
        "closed",
        "0 to 3",
        "installment",
    ]:
        assert text in prompt


def test_prompt_has_per_node_checklist() -> None:
    # G2 run 1 missed "a new request restarts the clock" without this checklist.
    prompt = build_decision_prompt(rule(), SHOP)
    for text in [
        "count: which event resets the count",
        "none_after: which later event lifts the ban",
        "every_preceded_by: which event clears the prerequisite",
        "does the clock restart",
        "START event itself",
        "this rule's own business",
    ]:
        assert text in prompt


def test_to_core_patches_expands_two_select_exclude() -> None:
    patch = AddExclude.model_validate(exclude(select_ids=["request", "completion"]))
    calls = []

    def add_exclude(select_id, condition):
        calls.append((select_id, condition))
        return select_id

    mapped = to_core_patches(patch, add_reset=lambda *args: args, add_exclude=add_exclude)
    assert mapped == ["request", "completion"]
    assert [c[0] for c in calls] == ["request", "completion"]
    assert all(c[1].value == "installment" for c in calls)


def test_to_core_patches_maps_reset() -> None:
    assert to_core_patches(
        AddReset.model_validate(reset()),
        add_reset=lambda *args: args,
        add_exclude=lambda *args: args,
    ) == [("check", "refunded")]


def test_duplicate_excludes_ignore_target_and_membership_order() -> None:
    first = exclude(
        select_ids=["request", "completion"],
        condition={"field": "payment_type", "op": "in", "values": ["card", "installment"]},
    )
    second = exclude(
        select_ids=["completion", "request"],
        condition={"field": "payment_type", "op": "in", "values": ["installment", "card"]},
    )
    outcome, _, _ = run([proposal(first, "a"), proposal(second, "b")], target=rule(deadline=True))
    assert len(outcome.decisions) == 1 and len(outcome.dropped) == 1


def test_builder_cannot_mutate_original_rule_or_retained_patch() -> None:
    original = rule()
    snapshot = original.model_dump_json()
    sdk = FakeSDK({"decisions": [proposal(exclude())]})

    def builder(target, patch):
        target.nodes.clear()
        patch.select_ids.clear()
        return EXAMPLE

    outcome = propose_decisions(
        original,
        vocab=SHOP,
        client=GeminiClient(sdk=sdk, cache_dir=None),
        make_example=builder,
    )
    assert original.model_dump_json() == snapshot
    assert outcome.decisions[0].patch.select_ids == ["charges"]


def test_cache_preserves_schema_rejection_evidence(tmp_path) -> None:
    sdk = FakeSDK({"decisions": [proposal(reset("charges"), "bad")]})
    client = GeminiClient(model="test", sdk=sdk, cache_dir=tmp_path)
    kwargs = {"vocab": SHOP, "client": client, "make_example": lambda *_: EXAMPLE}
    first = propose_decisions(rule(), **kwargs)
    second = propose_decisions(rule(), **kwargs)
    assert not first.cached and second.cached and len(sdk.prompts) == 1
    assert first.dropped == second.dropped


@pytest.mark.parametrize(
    "patch",
    [
        {**reset(), "unsupported_key": "ignored changes are unsafe"},
        exclude(
            condition={
                "field": "payment_type",
                "op": "eq",
                "value": "installment",
                "values": ["card"],
            }
        ),
    ],
)
def test_unexpected_patch_fields_are_retained_as_drops(patch) -> None:
    outcome, _, _ = run([proposal(patch, "bad"), proposal(reset(), "good")])
    assert len(outcome.decisions) == 1
    assert outcome.dropped[0].gemini_id == "bad"
    assert "unexpected fields" in " ".join(outcome.dropped[0].reasons)


def test_unexpected_envelope_fields_are_not_silently_ignored() -> None:
    sdk = FakeSDK({"decisions": [], "apply_rule": True})
    with pytest.raises(GeminiBadOutput):
        propose_decisions(
            rule(),
            vocab=SHOP,
            client=GeminiClient(sdk=sdk, cache_dir=None),
            make_example=lambda *_: EXAMPLE,
        )


def test_invalid_input_rule_prevents_gemini_call() -> None:
    sdk = FakeSDK({"decisions": []})
    with pytest.raises(ParseError):
        propose_decisions(
            rule().model_copy(update={"root": "missing"}),
            vocab=SHOP,
            client=GeminiClient(sdk=sdk, cache_dir=None),
            make_example=lambda *_: EXAMPLE,
        )
    assert not sdk.prompts


def test_rule_specific_schema_does_not_leak_other_rules_targets() -> None:
    first = decision_schema(rule(), SHOP)
    second = decision_schema(rule(deadline=True), SHOP)
    assert '"charges"' in json.dumps(first.model_json_schema())
    assert '"charges"' not in json.dumps(second.model_json_schema())
    assert '"completion"' not in json.dumps(first.model_json_schema())


def test_whitespace_question_is_dropped_before_example_builder() -> None:
    bad = {**proposal(reset()), "question": "   "}
    result, _, seen = run([bad])
    assert not result.decisions and not seen
    assert "non-whitespace" in " ".join(result.dropped[0].reasons)
