"""Versioned spec parsing, dumping, and migration contracts."""

import json

import pytest
import yaml
from pydantic import ValidationError

from haqwa import migrate_spec
from haqwa.core.rules_v2 import RuleV2
from haqwa.core.spec import AtMostOnce, Spec, dump_spec, load_spec, parse_spec, save_spec

V2_YAML = """\
version: 2
rules:
  - id: ship-soon
    source: Ship within a day of ordering.
    per: order_id
    version: 2
    nodes:
      - {id: ordered, type: select, event: ordered}
      - {id: shipped, type: select, event: shipped}
      - {id: rule, type: every_followed_within, start: ordered, by: shipped, within: PT24H}
    root: rule
    confirmed_examples:
      - timeline: [{event: ordered, at: PT0S}, {event: shipped, at: PT1H}]
        violation: false
"""

V1_RULE = {
    "id": "charge-once",
    "source": "Charge each order at most once.",
    "pattern": "at_most_once",
    "event": "charged",
    "per": "order_id",
    "confirmed_examples": [{"timeline": [{"event": "charged", "at": "PT0S"}], "violation": False}],
}


def test_v2_rule_with_yaml_examples_loads_and_roundtrips(tmp_path):
    path = tmp_path / "rules.spec.yaml"
    path.write_text(V2_YAML, encoding="utf-8")
    spec = load_spec(path)
    rule = spec.rules[0]
    assert isinstance(rule, RuleV2)
    assert rule.confirmed_examples[0].timeline[1].at.total_seconds() == 3600
    assert rule.nodes[2].within == "PT24H"

    dumped = dump_spec(spec)
    saved = tmp_path / "saved.spec.yaml"
    save_spec(spec, saved)
    assert saved.read_text(encoding="utf-8") == dumped
    assert load_spec(saved) == spec
    assert dump_spec(load_spec(saved)) == dumped
    assert parse_spec(json.loads(json.dumps(yaml.safe_load(dumped)))) == spec

    assert list(yaml.safe_load(dumped)["rules"][0]) == [
        "id",
        "source",
        "per",
        "version",
        "nodes",
        "root",
        "confirmed_examples",
    ]
    assert list(yaml.safe_load(dumped)["rules"][0]["nodes"][0]) == ["id", "type", "event"]
    assert "where:" not in dumped and "exclude:" not in dumped and "since:" not in dumped


def test_v1_dump_stays_byte_identical():
    rule = {k: v for k, v in V1_RULE.items() if k != "confirmed_examples"}
    spec = Spec.model_validate({"rules": [rule]})
    assert dump_spec(spec) == (
        "version: 1\n"
        "rules:\n"
        "  - id: charge-once\n"
        "    source: Charge each order at most once.\n"
        "    pattern: at_most_once\n"
        "    event: charged\n"
        "    per: order_id\n"
    )
    assert parse_spec(yaml.safe_load(dump_spec(spec))) == spec


def test_mixed_spec_roundtrips_and_migration_keeps_examples():
    v2_rule = yaml.safe_load(V2_YAML)["rules"][0]
    spec = parse_spec({"version": 2, "rules": [V1_RULE, v2_rule]})
    assert isinstance(spec.rules[0], AtMostOnce)
    assert isinstance(spec.rules[1], RuleV2)
    assert parse_spec(yaml.safe_load(dump_spec(spec))) == spec

    migrated = migrate_spec(spec)
    assert migrated.version == 2
    assert all(isinstance(rule, RuleV2) for rule in migrated.rules)
    assert [rule.id for rule in migrated.rules] == ["charge-once", "ship-soon"]
    assert migrated.rules[0].confirmed_examples == spec.rules[0].confirmed_examples
    assert migrated.rules[1] == spec.rules[1]
    assert migrate_spec(migrated) == migrated
    assert parse_spec(yaml.safe_load(dump_spec(migrated))) == migrated


def test_migrate_v1_spec_is_idempotent_and_keeps_examples():
    spec = parse_spec({"rules": [V1_RULE]})
    migrated = migrate_spec(spec)
    assert migrated.version == 2
    assert isinstance(migrated.rules[0], RuleV2)
    assert migrated.rules[0].confirmed_examples == spec.rules[0].confirmed_examples
    assert migrate_spec(migrated) is migrated


def test_v2_rule_requires_version_two_spec():
    with pytest.raises(ValidationError, match="v2 rules must have version 2"):
        Spec.model_validate({"version": 1, "rules": yaml.safe_load(V2_YAML)["rules"]})


def test_v1_only_spec_requires_version_one():
    with pytest.raises(ValidationError, match="only v1 rules must have version 1"):
        Spec.model_validate({"version": 2, "rules": [V1_RULE]})


def test_duplicate_ids_across_versions_rejected():
    v2_rule = yaml.safe_load(V2_YAML)["rules"][0]
    v2_rule["id"] = V1_RULE["id"]
    with pytest.raises(ValidationError, match="duplicate rule ids"):
        Spec.model_validate({"version": 2, "rules": [V1_RULE, v2_rule]})
