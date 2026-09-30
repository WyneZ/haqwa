import pytest

from haqwa.core.canonical import canonical_examples
from haqwa.core.compiler import compile_spec, violates
from haqwa.core.spec import Spec

from .helpers import amo, mp, nav, wt

RULES = [amo(), nav(), mp(), wt()]


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r.pattern)
def test_evaluators_agree_with_every_canonical_example(rule):
    for ex in canonical_examples(rule):
        assert violates(rule, ex.timeline) is ex.violation, ex.label


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r.pattern)
def test_minimum_set_per_pattern(rule):
    labels = [ex.label for ex in canonical_examples(rule)]
    assert len(labels) >= 3
    assert any("different" in label for label in labels)
    assert {ex.violation for ex in canonical_examples(rule)} == {True, False}


def test_examples_hold_even_with_exceptions_on_the_rule():
    rule = amo(
        **{
            "except": [
                {"reset_after": "refunded"},
                {"allow_if": {"field": "payment_type", "op": "eq", "value": "installment"}},
            ]
        }
    )
    for ex in canonical_examples(rule):
        assert violates(rule, ex.timeline) is ex.violation


def test_within_time_includes_calendar_hours_example():
    labels = [ex.label for ex in canonical_examples(wt(within="PT48H"))]
    assert any("Fri 17:00" in label for label in labels)
    labels = [ex.label for ex in canonical_examples(wt(within="PT72H"))]
    assert not any("Fri 17:00" in label for label in labels)


def test_confirmed_examples_compile_and_self_test():
    rule = wt()
    confirmed = [ex.as_confirmed() for ex in canonical_examples(rule)]
    spec = Spec.model_validate(
        {"rules": [{**rule.model_dump(by_alias=True), "confirmed_examples": confirmed}]}
    )
    compile_spec(spec)  # no CompileError


def test_owner_answer_maps_to_violation():
    ex = canonical_examples(amo())[0]
    assert ex.as_confirmed(owner_says_allowed=True).violation is False
    assert ex.as_confirmed(owner_says_allowed=False).violation is True
