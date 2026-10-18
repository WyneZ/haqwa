"""Clarify v2: code lists candidate changes, Gemini (faked here) only chooses and words them."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from haqwa.ai.clarify_v2 import (
    AddExclude,
    AddReset,
    build_decision_prompt,
    choice_schema,
    enumerate_candidates,
    patch_key,
    propose_decisions,
    to_core_patches,
)
from haqwa.ai.client import GeminiBadOutput, GeminiClient
from haqwa.ai.core_v2_ports import core_ports
from haqwa.ai.parse import ParseError
from haqwa.ai.render_v2 import render_rule
from haqwa.ai.vocab import Vocabulary
from haqwa.core.canonical import CanonicalExample
from haqwa.core.errors import INVALID_REQUEST, HaqwaError
from haqwa.core.rules_v2 import ConditionV2, RuleV2
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
CORE = core_ports().make_example


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
    """Build a reset patch."""
    return {"op": "add_reset", "node_id": node_id, "event": event}


def exclude(**changes: Any) -> dict[str, Any]:
    """Build an installment exemption patch."""
    return {
        "op": "add_exclude",
        "select_ids": ["charges"],
        "condition": {"field": "payment_type", "op": "eq", "value": "installment"},
        **changes,
    }


def keys(patches: list[dict[str, Any]]) -> set[tuple]:
    """Comparable keys for expected patches."""
    return {
        patch_key(
            AddReset.model_validate(p) if p["op"] == "add_reset" else AddExclude.model_validate(p)
        )
        for p in patches
    }


def choice(candidate: str, question: str = "Is this allowed?") -> dict[str, Any]:
    """One Gemini choice of a listed candidate."""
    return {"candidate": candidate, "question": question, "why": "The owner must decide."}


def run(choices: list[dict[str, Any]], *, target: RuleV2 | None = None, make_example=CORE):
    """Exercise the real client and the per-rule schema with a fake SDK."""
    sdk = FakeSDK({"decisions": choices})
    outcome = propose_decisions(
        target or rule(),
        vocab=SHOP,
        client=GeminiClient(model="test", sdk=sdk, cache_dir=None),
        make_example=make_example,
    )
    return outcome, sdk


def ids_by_key(target: RuleV2) -> dict[tuple, str]:
    """Candidate id for each candidate patch, as code numbers them."""
    return {patch_key(c.patch): c.id for c in enumerate_candidates(target, SHOP, CORE)}


# ---- candidates: code lists every change that matters ----------------------------------


def test_count_candidates_are_every_reset_and_exemption_except_the_counted_event() -> None:
    candidates = enumerate_candidates(rule(), SHOP, CORE)
    expected = [reset(event=e) for e in ("refunded", "cancelled", "refund_requested")]
    expected += [reset(event="refund_completed")]
    expected += [
        exclude(condition={"field": "payment_type", "op": "eq", "value": v})
        for v in ("card", "installment")
    ]
    assert {patch_key(c.patch) for c in candidates} == keys(expected)
    assert [c.id for c in candidates] == [f"p{i}" for i in range(1, len(candidates) + 1)]
    # Each example breaks today's rule and is allowed with the change: Yes = apply it.
    assert all(c.example.violation for c in candidates)


def test_deadline_candidates_include_restart_on_start_but_not_the_completion_event() -> None:
    candidates = enumerate_candidates(rule(deadline=True), SHOP, CORE)
    found = {patch_key(c.patch) for c in candidates}
    assert keys([reset(event="refund_requested")]) <= found  # G3.2 restart is always listed
    assert not keys([reset(event="refund_completed")]) & found  # would switch the rule off
    exemption = exclude(select_ids=["request", "completion"])
    assert keys([exemption]) <= found  # covers both sides of the deadline
    restart = next(
        c for c in candidates if patch_key(c.patch) in keys([reset(event="refund_requested")])
    )
    assert "restarts the deadline clock" in restart.text


def test_changes_already_in_the_rule_are_not_candidates() -> None:
    original = rule()
    original.nodes[-1].since.append("refunded")
    original.nodes[0].exclude.append(
        ConditionV2(field="payment_type", op="eq", value="installment")
    )
    found = {patch_key(c.patch) for c in enumerate_candidates(original, SHOP, CORE)}
    assert not found & keys([reset(), exclude()])


@pytest.mark.parametrize(
    "example",
    [
        None,  # core found no timeline that separates Yes from No
        CanonicalExample("stricter", (TimelineEvent(event="charged"),), violation=False),
    ],
)
def test_changes_without_a_relaxing_example_are_not_candidates(example) -> None:
    assert enumerate_candidates(rule(), SHOP, lambda *_: example) == []


def test_core_rejecting_a_patch_skips_only_that_candidate() -> None:
    def builder(target, patch):
        if isinstance(patch, AddExclude):
            raise HaqwaError(INVALID_REQUEST, "rejected by core")
        return EXAMPLE

    candidates = enumerate_candidates(rule(), SHOP, builder)
    assert candidates and all(isinstance(c.patch, AddReset) for c in candidates)


def test_builder_cannot_mutate_the_rule_or_the_candidate_patch() -> None:
    original = rule()
    snapshot = original.model_dump_json()

    def builder(target, patch):
        target.nodes.clear()
        if isinstance(patch, AddExclude):
            patch.select_ids.clear()
        return EXAMPLE

    candidates = enumerate_candidates(original, SHOP, builder)
    assert original.model_dump_json() == snapshot
    assert all(
        c.patch.select_ids == ["charges"] for c in candidates if isinstance(c.patch, AddExclude)
    )


# ---- Gemini chooses from the list -------------------------------------------------------


def test_chosen_candidates_become_decisions_with_core_examples() -> None:
    original = rule()
    snapshot = original.model_dump_json()
    ids = ids_by_key(original)
    refund, installment = ids[next(iter(keys([reset()])))], ids[next(iter(keys([exclude()])))]
    outcome, sdk = run(
        [choice(refund, "  Can an order be charged again after a refund?  "), choice(installment)],
        target=original,
    )
    assert len(sdk.prompts) == 1 and not outcome.dropped and not outcome.cached
    assert [d.id for d in outcome.decisions] == ["d1", "d2"]
    first = outcome.decisions[0]
    assert first.question == "Can an order be charged again after a refund?"
    assert keys([reset()]) == {patch_key(first.patch)}
    assert [e.event for e in first.example.timeline] == ["charged", "refunded", "charged"]
    assert outcome.rule == original and original.model_dump_json() == snapshot
    assert outcome.meaning == render_rule(original)


def test_zero_choices_is_valid() -> None:
    outcome, _ = run([])
    assert not outcome.decisions and not outcome.dropped


def test_duplicate_choice_is_dropped_and_sibling_kept() -> None:
    outcome, _ = run([choice("p1"), choice("p1"), choice("p2")])
    assert [d.patch for d in outcome.decisions] == [
        c.patch for c in enumerate_candidates(rule(), SHOP, CORE)[:2]
    ]
    assert outcome.dropped[0].gemini_id == "p1"
    assert "duplicate" in outcome.dropped[0].reasons[0]


@pytest.mark.parametrize("field", ["question", "why"])
def test_blank_text_is_dropped(field) -> None:
    outcome, _ = run([{**choice("p1"), field: "   "}, choice("p2")])
    assert len(outcome.decisions) == 1
    assert "non-whitespace" in outcome.dropped[0].reasons[0]


def test_unlisted_candidate_id_is_bad_output() -> None:
    with pytest.raises(GeminiBadOutput):
        run([choice("p99")])


def test_unexpected_envelope_or_choice_fields_are_bad_output() -> None:
    with pytest.raises(GeminiBadOutput):
        run([{**choice("p1"), "patch": reset()}])
    sdk = FakeSDK({"decisions": [], "apply_rule": True})
    with pytest.raises(GeminiBadOutput):
        propose_decisions(
            rule(), vocab=SHOP, client=GeminiClient(sdk=sdk, cache_dir=None), make_example=CORE
        )


def test_no_candidates_means_no_gemini_call() -> None:
    sdk = FakeSDK({"decisions": []})
    outcome = propose_decisions(
        rule(),
        vocab=SHOP,
        client=GeminiClient(sdk=sdk, cache_dir=None),
        make_example=lambda *_: None,
    )
    assert not sdk.prompts and not outcome.decisions and outcome.cached


def test_invalid_input_rule_prevents_gemini_call() -> None:
    sdk = FakeSDK({"decisions": []})
    with pytest.raises(ParseError):
        propose_decisions(
            rule().model_copy(update={"root": "missing"}),
            vocab=SHOP,
            client=GeminiClient(sdk=sdk, cache_dir=None),
            make_example=CORE,
        )
    assert not sdk.prompts


def test_second_call_is_cached(tmp_path) -> None:
    sdk = FakeSDK({"decisions": [choice("p1")]})
    client = GeminiClient(model="test", sdk=sdk, cache_dir=tmp_path)
    kwargs = {"vocab": SHOP, "client": client, "make_example": CORE}
    first = propose_decisions(rule(), **kwargs)
    second = propose_decisions(rule(), **kwargs)
    assert not first.cached and second.cached and len(sdk.prompts) == 1
    assert first.decisions == second.decisions


# ---- schema and prompt ------------------------------------------------------------------


def test_schema_enumerates_ids_caps_choices_and_is_provider_safe() -> None:
    schema_model = choice_schema(("p1", "p2"))
    schema = schema_model.model_json_schema()
    text = json.dumps(schema)
    assert '"p1"' in text and '"p2"' in text
    assert schema["properties"]["decisions"]["maxItems"] == 4
    assert "oneOf" not in text and "additionalProperties" not in text
    with pytest.raises(ValidationError):
        schema_model.model_validate({"decisions": [choice("p3")]})
    with pytest.raises(ValidationError):
        schema_model.model_validate({"decisions": [choice("p1")] * 5})


def test_prompt_lists_every_candidate_with_its_example_and_guidance() -> None:
    target = rule(deadline=True)
    candidates = enumerate_candidates(target, SHOP, CORE)
    prompt = build_decision_prompt(target, candidates)
    assert prompt == build_decision_prompt(target, candidates)
    assert json.dumps(target.source) in prompt and render_rule(target) in prompt
    for candidate in candidates:
        assert f"- {candidate.id}: {candidate.text}." in prompt
    assert "refund requested -> refund requested at +12h -> refund completed at +1d 1s" in prompt
    for text in [
        "EVERY change",
        "0 to 4",
        "restarts the clock",
        "installment",
        "Yes means the\n  change applies",
        "Do not decide pass/fail",
    ]:
        assert text in prompt


# ---- core adapter -----------------------------------------------------------------------


def test_to_core_patches_expands_two_select_exclude() -> None:
    patch = AddExclude.model_validate(exclude(select_ids=["request", "completion"]))
    calls = []

    def add_exclude(select_id, condition):
        calls.append((select_id, condition))
        return select_id

    mapped = to_core_patches(patch, add_reset=lambda *args: args, add_exclude=add_exclude)
    assert mapped == ["request", "completion"]
    assert all(c[1].value == "installment" for c in calls)


def test_to_core_patches_maps_reset() -> None:
    assert to_core_patches(
        AddReset.model_validate(reset()),
        add_reset=lambda *args: args,
        add_exclude=lambda *args: args,
    ) == [("check", "refunded")]
