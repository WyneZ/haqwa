"""Prove each v1 preset expands to the exact frozen checker findings."""

import gzip
import json
from collections import Counter
from pathlib import Path

import pytest

from haqwa.core.compiler import rule_event_names
from haqwa.core.events import Event, group_by, sort_events
from haqwa.core.presets_v2 import expand_v1
from haqwa.core.rules_v2 import SelectNode, validate_rule_v2
from haqwa.core.rules_v2_eval import evaluate_v2
from haqwa.core.spec import AllowIf, Spec

CORPUS = Path(__file__).with_name("golden") / "corpus.json.gz"
PATTERNS = ("at_most_once", "never_after", "must_precede", "within_time")


@pytest.fixture(scope="module")
def corpus():
    with gzip.open(CORPUS, "rt", encoding="utf-8") as zipped:
        return json.load(zipped)


@pytest.mark.parametrize("pattern", PATTERNS)
def test_expanded_preset_matches_golden_corpus(pattern, corpus):
    entries = [
        (index, entry) for index, entry in enumerate(corpus) if entry["rule"]["pattern"] == pattern
    ]
    assert len(entries) >= 3000
    mismatches = []
    for index, entry in entries:
        rule = Spec.model_validate({"rules": [entry["rule"]]}).rules[0]
        expanded = expand_v1(rule)
        events = [Event.model_validate(item) for item in entry["events"]]
        vocabulary = rule_event_names(rule) | {event.event for event in events}
        fields = {rule.per} | {field for event in events for field in event.data}
        fields |= {
            exception.allow_if.field
            for exception in rule.exceptions
            if isinstance(exception, AllowIf)
        }
        numeric = {
            field
            for event in events
            for field, value in event.data.items()
            if type(value) in (int, float)
        }
        assert validate_rule_v2(expanded, vocabulary, fields, numeric) == [], index

        ordered = sort_events(events)
        trace_end = ordered[-1].ts if ordered else None
        actual = {
            str(entity): [
                [finding.index, finding.message]
                for finding in evaluate_v2(expanded, stream, trace_end)
            ]
            for entity, stream in group_by(ordered, rule.per).items()
        }
        if actual != entry["findings"]:
            mismatches.append((len(events), index, entry, actual))
    if mismatches:
        _, index, entry, actual = min(mismatches)
        pytest.fail(
            f"smallest {pattern} mismatch at corpus entry {index}: "
            f"{json.dumps(entry, sort_keys=True)}; actual={json.dumps(actual, sort_keys=True)}"
        )


def test_preset_shape_places_all_exclusions_on_every_select(corpus):
    exemplar = next(entry for entry in corpus if entry["rule"]["id"] == "n-r1-two")
    rule = Spec.model_validate({"rules": [exemplar["rule"]]}).rules[0]
    expanded = expand_v1(rule)
    selects = [node for node in expanded.nodes if isinstance(node, SelectNode)]
    assert len(selects) == 2
    assert all(len(node.exclude) == 2 for node in selects)
    assert Counter(node.type for node in expanded.nodes) == {"select": 2, "none_after": 1}
