import pytest
from pydantic import ValidationError

from haqwa.core.spec import AllowIf, AtMostOnce, ResetAfter, Spec, WithinTime, load_spec

BASE = {"id": "r1", "source": "s", "per": "order_id"}


def spec_with(**rule) -> Spec:
    return Spec.model_validate({"rules": [{**BASE, **rule}]})


def test_example_spec_loads(shop_dir):
    spec = load_spec(shop_dir / "rules.spec.yaml")
    rule = spec.rules[0]
    assert isinstance(rule, AtMostOnce)
    assert isinstance(rule.exceptions[0], ResetAfter)
    assert isinstance(rule.exceptions[1], AllowIf)
    assert len(rule.confirmed_examples) == 3


def test_each_pattern_picks_its_model():
    s = spec_with(pattern="within_time", start="ordered", event="shipped", within="PT24H")
    assert isinstance(s.rules[0], WithinTime)
    assert s.rules[0].within.total_seconds() == 86400


@pytest.mark.parametrize(
    "rule",
    [
        {"pattern": "exactly_twice", "event": "charged"},  # unknown pattern
        {"pattern": "at_most_once", "event": "charged", "after": "x"},  # field of another pattern
        {"pattern": "never_after", "event": "charged"},  # missing `after`
        {"pattern": "at_most_once", "event": "charged", "excpet": []},  # typo
        {"pattern": "at_most_once", "event": "charged", "id": "Bad Id"},
        {
            "pattern": "at_most_once",
            "event": "charged",
            "except": [{"allow_if": {"field": "a", "op": "gt", "value": 1}}],
        },
        {
            "pattern": "at_most_once",
            "event": "charged",
            "except": [{"allow_if": {"field": "a", "op": "in", "value": "x"}}],
        },
        {
            "pattern": "at_most_once",
            "event": "charged",
            "except": [{"allow_if": {"field": "a", "op": "eq", "value": ["x"]}}],
        },
        {
            "pattern": "at_most_once",
            "event": "charged",
            "confirmed_examples": [{"timeline": [], "violation": True}],
        },
    ],
)
def test_invalid_rules_rejected(rule):
    with pytest.raises(ValidationError):
        spec_with(**rule)


def test_duplicate_ids_rejected():
    r = {**BASE, "pattern": "at_most_once", "event": "charged"}
    with pytest.raises(ValidationError, match="duplicate rule ids"):
        Spec.model_validate({"rules": [r, r]})


def test_spec_is_frozen(shop_dir):
    spec = load_spec(shop_dir / "rules.spec.yaml")
    with pytest.raises(ValidationError):
        spec.rules[0].event = "other"


def _example(timeline):
    return spec_with(
        pattern="within_time",
        start="s",
        event="e",
        within="PT1H",
        confirmed_examples=[{"timeline": timeline, "violation": False}],
    )


def test_at_offsets_accepted():
    s = _example([{"event": "s", "at": "PT0S"}, {"event": "e", "at": "PT65H"}])
    assert s.rules[0].confirmed_examples[0].timeline[1].at.total_seconds() == 65 * 3600


@pytest.mark.parametrize(
    "timeline",
    [
        [{"event": "s", "at": "PT0S"}, {"event": "e"}],  # mixed
        [{"event": "s", "at": "PT1H"}, {"event": "e", "at": "PT2H"}],  # first not 0
        [{"event": "s", "at": "PT0S"}, {"event": "e", "at": "PT2H"}, {"event": "e", "at": "PT1H"}],
    ],
)
def test_bad_at_offsets_rejected(timeline):
    with pytest.raises(ValidationError):
        _example(timeline)


def test_within_must_be_positive():
    with pytest.raises(ValidationError):
        spec_with(pattern="within_time", start="s", event="e", within="PT0S")
