"""Owner-answer patch shape, errors, idempotence and v1 preset parity."""

import gzip
import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from haqwa.core.errors import HaqwaError
from haqwa.core.events import Event, group_by, sort_events
from haqwa.core.patches_v2 import AddExcludeV2, AddResetV2, PatchV2, apply_patch_v2
from haqwa.core.presets_v2 import expand_v1
from haqwa.core.rules_v2 import SelectNode, validate_rule_v2
from haqwa.core.rules_v2_eval import evaluate_v2
from haqwa.core.spec import Spec

CORPUS = Path(__file__).with_name("golden") / "corpus.json.gz"
PATTERNS = ("at_most_once", "never_after", "must_precede", "within_time")


def _rule(pattern: str = "at_most_once"):
    data = {
        "id": "sample",
        "source": "Sample rule",
        "per": "order_id",
        "pattern": pattern,
        "event": "charged",
    }
    if pattern == "never_after":
        data["after"] = "shipped"
    elif pattern == "must_precede":
        data["requires"] = "shipped"
    elif pattern == "within_time":
        data.update(start="shipped", within="PT48H")
    return expand_v1(Spec.model_validate({"rules": [data]}).rules[0])


def test_patch_models_match_decision_wire_shape():
    adapter = TypeAdapter(PatchV2)
    reset = {"op": "add_reset", "node_id": "rule", "event": "refunded"}
    exclude = {
        "op": "add_exclude",
        "select_ids": ["target"],
        "condition": {"field": "payment_type", "op": "in", "values": ["installment"]},
    }
    assert adapter.validate_python(reset).model_dump() == reset
    assert adapter.validate_python(exclude).model_dump() == exclude
    assert isinstance(adapter.validate_python(reset), AddResetV2)
    assert isinstance(adapter.validate_python(exclude), AddExcludeV2)

    with pytest.raises(ValidationError):
        adapter.validate_python({**exclude, "select_ids": []})
    with pytest.raises(ValidationError):
        adapter.validate_python({**exclude, "condition": {**exclude["condition"], "values": []}})


@pytest.mark.parametrize("pattern", PATTERNS)
def test_add_reset_is_pure_idempotent_and_valid(pattern):
    original = _rule(pattern)
    patch = {"op": "add_reset", "node_id": "rule", "event": "refunded"}
    changed = apply_patch_v2(original, patch)
    assert changed is not original
    assert original.nodes[-1].since == []
    assert changed.nodes[-1].since == ["refunded"]
    assert apply_patch_v2(changed, patch) == changed
    assert validate_rule_v2(changed, {"charged", "shipped", "refunded"}, {"order_id"}, set()) == []


def test_add_exclude_updates_each_select_once():
    original = _rule("never_after")
    patch = {
        "op": "add_exclude",
        "select_ids": ["target", "trigger", "target"],
        "condition": {"field": "payment_type", "op": "eq", "value": "installment"},
    }
    changed = apply_patch_v2(original, patch)
    assert all(len(node.exclude) == 1 for node in changed.nodes if isinstance(node, SelectNode))
    assert all(not node.exclude for node in original.nodes if isinstance(node, SelectNode))
    assert apply_patch_v2(changed, patch) == changed
    assert (
        validate_rule_v2(changed, {"charged", "shipped"}, {"order_id", "payment_type"}, set()) == []
    )


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"op": "add_reset", "node_id": "missing", "event": "refunded"}, "unknown node id"),
        ({"op": "add_reset", "node_id": "target", "event": "refunded"}, "does not accept since"),
        (
            {
                "op": "add_exclude",
                "select_ids": ["rule"],
                "condition": {"field": "payment_type", "op": "ne", "value": "manual"},
            },
            "is not a select",
        ),
        (
            {
                "op": "add_exclude",
                "select_ids": ["missing"],
                "condition": {"field": "payment_type", "op": "ne", "value": "manual"},
            },
            "is not a select",
        ),
    ],
)
def test_invalid_target_raises_clear_haqwa_error(patch, message):
    with pytest.raises(HaqwaError, match=message):
        apply_patch_v2(_rule(), patch)


def _findings(rule, events):
    ordered = sort_events(events)
    trace_end = ordered[-1].ts if ordered else None
    return {
        str(entity): [
            (finding.index, finding.message) for finding in evaluate_v2(rule, stream, trace_end)
        ]
        for entity, stream in group_by(ordered, rule.per).items()
    }


@pytest.mark.parametrize("pattern", PATTERNS)
@pytest.mark.parametrize("kind", ("reset", "exclude"))
def test_patch_matches_expanded_v1_exception_on_golden_sample(pattern, kind):
    with gzip.open(CORPUS, "rt", encoding="utf-8") as zipped:
        corpus = json.load(zipped)
    suffix = "r1-none" if kind == "reset" else "r0-eq"
    entries = [
        entry
        for entry in corpus
        if entry["rule"]["pattern"] == pattern and entry["rule"]["id"].endswith(suffix)
    ][:60]
    assert len(entries) == 60
    for entry in entries:
        with_exception = entry["rule"]
        without_exception = {**with_exception, "except": []}
        original = expand_v1(Spec.model_validate({"rules": [without_exception]}).rules[0])
        expected = expand_v1(Spec.model_validate({"rules": [with_exception]}).rules[0])
        if kind == "reset":
            patch = {"op": "add_reset", "node_id": "rule", "event": "r"}
        else:
            patch = {
                "op": "add_exclude",
                "select_ids": [node.id for node in original.nodes if isinstance(node, SelectNode)],
                "condition": {
                    "field": "payment_type",
                    "op": "eq",
                    "value": "i",
                },
            }
        actual = apply_patch_v2(original, patch)
        assert actual == expected
        events = [Event.model_validate(item) for item in entry["events"]]
        assert _findings(actual, events) == _findings(expected, events)
