"""Regenerate the frozen v1 checker corpus: uv run python tests/core/golden/build_corpus.py."""

from __future__ import annotations

import gzip
import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from haqwa.core.checker import check
from haqwa.core.compiler import compile_spec, rule_event_names
from haqwa.core.events import Event, group_by, load_events, sort_events, synthetic_timeline
from haqwa.core.spec import Rule, Spec, load_spec
from haqwa.demo import run_scenario
from haqwa.demo.recording import RECORDINGS_DIR, load_effects

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = Path(__file__).with_name("corpus.json.gz")
SEED = 20261014
TRACES_PER_VARIANT = 300
BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)
RESET_EVENT = "r"
UNRELATED_EVENT = "z"
ALLOW_VARIANTS: dict[str, list[dict[str, Any]]] = {
    "none": [],
    "eq": [{"allow_if": {"field": "payment_type", "op": "eq", "value": "i"}}],
    "ne": [{"allow_if": {"field": "payment_type", "op": "ne", "value": "i"}}],
    "in": [{"allow_if": {"field": "payment_type", "op": "in", "value": ["i", "h"]}}],
    "two": [
        {"allow_if": {"field": "payment_type", "op": "eq", "value": "i"}},
        {"allow_if": {"field": "amount", "op": "in", "value": [0, 50]}},
    ],
}


def _rule_dict(rule: Rule) -> dict[str, Any]:
    return rule.model_dump(
        mode="json", by_alias=True, exclude_defaults=True, exclude={"confirmed_examples"}
    )


def _event_dict(event: Event) -> dict[str, Any]:
    # source_id is optional C2 metadata, and does not affect any checker.
    return {
        "event": event.event,
        "ts": event.ts.isoformat().replace("+00:00", "Z"),
        "data": event.data,
    }


def _entry(rule: Rule, events: list[Event]) -> dict[str, Any]:
    report = check(compile_spec(Spec(rules=[rule])), events)
    streams = group_by(sort_events(events), rule.per)
    findings: dict[str, list[list[int | str]]] = {str(entity): [] for entity in streams}
    for violation in report.results[0].violations:
        findings[violation.entity].append([violation.offending_index, violation.message])
    return {
        "rule": _rule_dict(rule),
        "events": [_event_dict(e) for e in events],
        "findings": findings,
    }


def _variant(rule: Rule, *, reset: bool, allow: str) -> Rule:
    # Compact synthetic names keep the expanded fixture readable after decompression.
    data: dict[str, Any] = {
        "id": f"{rule.pattern[0]}-r{int(reset)}-{allow}",
        "source": "Golden corpus rule",
        "per": "e",
        "pattern": rule.pattern,
        "event": "a",
    }
    if rule.pattern == "never_after":
        data["after"] = "b"
    elif rule.pattern == "must_precede":
        data["requires"] = "b"
    elif rule.pattern == "within_time":
        data.update(start="b", within="PT48H")
    exceptions: list[dict[str, Any]] = []
    if reset:
        exceptions.append({"reset_after": RESET_EVENT})
    exceptions.extend(ALLOW_VARIANTS[allow])
    if exceptions:
        data["except"] = exceptions
    return type(rule).model_validate(data)


def _random_trace(rule: Rule, rng: random.Random) -> list[Event]:
    names = sorted(rule_event_names(rule) | {UNRELATED_EVENT})
    events: list[Event] = []
    # All lengths 0..8 have positive weight; missing fields remain common.
    lengths = range(9)
    weights = (35, 42, 14, 5, 1, 1, 1, 1, 1)
    for entity in range(rng.randint(1, 3)):
        timestamp = BASE_TIME
        for _ in range(rng.choices(lengths, weights=weights)[0]):
            timestamp += timedelta(hours=rng.randint(0, 72))
            data: dict[str, Any] = {rule.per: str(entity)}
            if rng.random() < 0.35:
                data["amount"] = rng.choice((0, 50, rng.randint(1, 100)))
            if rng.random() < 0.35:
                data["payment_type"] = rng.choice(("c", "i", "h"))
            events.append(Event(event=rng.choice(names), ts=timestamp, data=data))
    return sort_events(events)


def build() -> list[dict[str, Any]]:
    specs = [load_spec(path) for path in sorted((ROOT / "examples").glob("**/*.spec.yaml"))]
    rules = [rule for spec in specs for rule in spec.rules]
    shop_spec = load_spec(ROOT / "examples/shop/rules.spec.yaml")
    scenario_ids = [
        "payment_timeout_naive",
        "payment_timeout_fixed",
        "duplicate_webhook_naive",
        "duplicate_webhook_fixed",
        "stale_status_naive",
        "stale_status_fixed",
    ]
    sources: list[list[Event]] = [
        run_scenario(scenario_id, shop_spec)[0] for scenario_id in scenario_ids
    ]
    sources += [load_effects(path) for path in sorted(RECORDINGS_DIR.glob("*.json"))]
    sources += [load_events(ROOT / "examples/hr/events.json")]
    sources += [load_events(ROOT / "examples/shop/events.json")]
    entries = [_entry(rule, events) for rule in rules for events in sources]
    for rule in rules:
        for spec in specs:
            for source_rule in spec.rules:
                for example in source_rule.confirmed_examples:
                    events = synthetic_timeline(
                        ((item.event, item.data, item.at) for item in example.timeline),
                        per=rule.per,
                    )
                    entries.append(_entry(rule, events))
    rng = random.Random(SEED)
    for pattern in ("at_most_once", "never_after", "must_precede", "within_time"):
        base = next(rule for rule in rules if rule.pattern == pattern)
        for reset in (False, True):
            for allow in ALLOW_VARIANTS:
                variant = _variant(base, reset=reset, allow=allow)
                entries.extend(
                    _entry(variant, _random_trace(variant, rng)) for _ in range(TRACES_PER_VARIANT)
                )
    return entries


if __name__ == "__main__":
    corpus = build()
    payload = (json.dumps(corpus, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
    with (
        OUTPUT.open("wb") as output,
        gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0) as zipped,
    ):
        zipped.write(payload)
    print(f"{len(corpus)} entries, {OUTPUT.stat().st_size} bytes")
