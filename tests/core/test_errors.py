import json

import pytest

from haqwa.core.compiler import CompileError, compile_spec, run_timeline, validate_rule_events
from haqwa.core.errors import CODES, HaqwaError, to_problem
from haqwa.core.events import load_event_map, load_events, parse_event_map, parse_events
from haqwa.core.spec import Spec, load_spec, parse_spec


def code_of(fn, *args):
    with pytest.raises(HaqwaError) as exc:
        fn(*args)
    return exc.value


def test_invalid_spec_from_data():
    err = code_of(parse_spec, {"rules": [{"id": "x", "pattern": "nope"}]})
    assert err.code == "invalid_spec" and err.status == 422 and err.exit_code == 2
    assert err.extra["errors"]


def test_invalid_spec_from_bad_yaml(tmp_path):
    p = tmp_path / "rules.spec.yaml"
    p.write_text("rules: [unclosed", encoding="utf-8")
    assert code_of(load_spec, p).code == "invalid_spec"


def test_invalid_events(tmp_path):
    assert code_of(parse_events, {"not": "a list"}).code == "invalid_events"
    assert code_of(parse_events, [{"event": "x", "ts": "2026-01-01T00:00:00"}]).code == (
        "invalid_events"
    )  # naive timestamp
    p = tmp_path / "events.json"
    p.write_text("{oops", encoding="utf-8")
    assert code_of(load_events, p).exit_code == 3


def test_invalid_event_map(tmp_path):
    assert code_of(parse_event_map, {"events": {"a": "X", "b": "X"}}).code == "invalid_event_map"
    p = tmp_path / "events.map.yaml"
    p.write_text("events: [", encoding="utf-8")
    assert code_of(load_event_map, p).code == "invalid_event_map"


def test_compile_failed_is_a_haqwa_error_with_seal_shape():
    spec = Spec.model_validate(
        {
            "rules": [
                {
                    "id": "no-double-charge",
                    "source": "s",
                    "pattern": "at_most_once",
                    "event": "charged",
                    "per": "order_id",
                    "confirmed_examples": [
                        {
                            "timeline": [
                                {"event": "charged"},
                                {"event": "refunded"},
                                {"event": "charged"},
                            ],
                            "violation": False,
                        }
                    ],
                }
            ]
        }
    )
    with pytest.raises(CompileError) as exc:
        compile_spec(spec)
    problem = to_problem(exc.value)
    assert problem["code"] == "compile_failed"
    assert problem["status"] == 422
    (failure,) = problem["failures"]
    assert failure == {
        "rule_id": "no-double-charge",
        "example_index": 0,
        "timeline": [{"event": "charged"}, {"event": "refunded"}, {"event": "charged"}],
        "expected": False,
        "got": True,
    }
    json.dumps(problem)  # JSON-ready


def test_problem_details_shape():
    err = code_of(parse_spec, {"rules": "nope"})
    problem = to_problem(err)
    assert problem["type"] == "https://haqwa.dev/errors/invalid-spec"
    assert {"type", "title", "status", "detail", "code"} <= set(problem)


def test_pattern_not_implemented_from_missing_registry_entry(monkeypatch):
    from haqwa.core.patterns import REGISTRY

    rule = Spec.model_validate(
        {
            "rules": [
                {
                    "id": "once",
                    "source": "s",
                    "pattern": "at_most_once",
                    "event": "charged",
                    "per": "order_id",
                }
            ]
        }
    ).rules[0]
    monkeypatch.delitem(REGISTRY, "at_most_once")
    assert code_of(run_timeline, rule, []).code == "pattern_not_implemented"


def test_unknown_event_from_rule_and_map():
    rule = Spec.model_validate(
        {
            "rules": [
                {
                    "id": "once",
                    "source": "s",
                    "pattern": "at_most_once",
                    "event": "charged",
                    "per": "order_id",
                }
            ]
        }
    ).rules[0]
    mapping = parse_event_map({"events": {"refunded": "REFUND_ISSUED"}})
    assert code_of(validate_rule_events, rule, mapping).code == "unknown_event"


def test_codes_are_unique_and_exit_codes_reserved():
    assert len(CODES) == len({c.code for c in CODES.values()})
    # 0 = pass, 1 = violation: never used for errors
    assert all(c.exit_code >= 2 for c in CODES.values())


def test_valid_example_files_still_load(shop_dir):
    load_spec(shop_dir / "rules.spec.yaml")
    load_events(shop_dir / "events.json")
    load_event_map(shop_dir / "events.map.yaml")
