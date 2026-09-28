import pytest

from haqwa.core.compiler import CompileError, compile_spec
from haqwa.core.events import EventMap
from haqwa.core.spec import Spec, load_spec


def rule(**kw):
    return {
        "id": "no-double-charge",
        "source": "s",
        "pattern": "at_most_once",
        "event": "charged",
        "per": "order_id",
        **kw,
    }


def test_example_spec_compiles_and_self_tests(shop_dir):
    compiled = compile_spec(load_spec(shop_dir / "rules.spec.yaml"))
    assert [c.rule.id for c in compiled.rules] == ["no-double-charge"]


def test_self_test_catches_missing_exception():
    # Human said "charge, refund, charge" is fine, but the parsed rule lost reset_after.
    spec = Spec.model_validate(
        {
            "rules": [
                rule(
                    confirmed_examples=[
                        {
                            "timeline": [
                                {"event": "charged"},
                                {"event": "refunded"},
                                {"event": "charged"},
                            ],
                            "violation": False,
                        }
                    ]
                )
            ]
        }
    )
    with pytest.raises(CompileError) as exc:
        compile_spec(spec)
    assert len(exc.value.failures) == 1
    assert "charged -> refunded -> charged" in str(exc.value)


def test_unimplemented_pattern_fails_clearly():
    spec = Spec.model_validate(
        {
            "rules": [
                {
                    "id": "r",
                    "source": "s",
                    "pattern": "never_after",
                    "event": "charged",
                    "after": "cancelled",
                    "per": "order_id",
                }
            ]
        }
    )
    with pytest.raises(CompileError, match="not implemented yet"):
        compile_spec(spec)


def test_unknown_event_name_fails_with_event_map():
    spec = Spec.model_validate({"rules": [rule(**{"except": [{"reset_after": "voided"}]})]})
    emap = EventMap.model_validate({"events": {"charged": "PAY", "refunded": "REF"}})
    with pytest.raises(CompileError, match="voided"):
        compile_spec(spec, emap)


def test_all_problems_reported_at_once():
    spec = Spec.model_validate(
        {
            "rules": [
                {
                    "id": "a",
                    "source": "s",
                    "pattern": "never_after",
                    "event": "x",
                    "after": "y",
                    "per": "k",
                },
                {
                    "id": "b",
                    "source": "s",
                    "pattern": "must_precede",
                    "event": "x",
                    "requires": "y",
                    "per": "k",
                },
            ]
        }
    )
    with pytest.raises(CompileError) as exc:
        compile_spec(spec)
    assert len(exc.value.problems) == 2
