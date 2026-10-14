"""Freeze the current checker output before introducing a v2 interpreter."""

import gzip
import json
from collections import Counter
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from haqwa.core.checker import check
from haqwa.core.compiler import compile_spec
from haqwa.core.events import Event, group_by, sort_events
from haqwa.core.spec import Spec

CORPUS = Path(__file__).with_name("golden") / "corpus.json.gz"


def test_current_checker_matches_golden_corpus():
    assert CORPUS.stat().st_size < 1_500_000
    with gzip.open(CORPUS, "rt", encoding="utf-8") as zipped:
        entries = json.load(zipped)
    expected_variants = {
        f"{pattern}-r{reset}-{allow}": 300
        for pattern in "anmw"
        for reset in (0, 1)
        for allow in ("none", "eq", "ne", "in", "two")
    }
    variants = Counter(
        entry["rule"]["id"] for entry in entries if entry["rule"]["id"] in expected_variants
    )
    assert variants == expected_variants
    for index, entry in enumerate(entries):
        spec = Spec.model_validate({"rules": [entry["rule"]]})
        events = [Event.model_validate(event) for event in entry["events"]]
        report = check(compile_spec(spec), events)
        actual = {str(entity): [] for entity in group_by(sort_events(events), spec.rules[0].per)}
        for violation in report.results[0].violations:
            actual[violation.entity].append([violation.offending_index, violation.message])
        assert actual == entry["findings"], f"corpus entry {index}"


@settings(max_examples=100, deadline=None)
@given(st.lists(st.sampled_from(("charged", "refunded", "unrelated")), max_size=30))
def test_at_most_once_findings_do_not_exceed_matching_events(names):
    rule = {
        "id": "no-double-charge",
        "source": "Charge at most once",
        "pattern": "at_most_once",
        "event": "charged",
        "per": "order_id",
        "except": [{"reset_after": "refunded"}],
    }
    spec = Spec.model_validate({"rules": [rule]})
    events = [
        Event(event=name, ts=f"2026-01-01T00:00:{index:02d}Z", data={"order_id": "one"})
        for index, name in enumerate(names)
    ]
    findings = check(compile_spec(spec), events).results[0].violations
    assert len(findings) <= names.count("charged")
