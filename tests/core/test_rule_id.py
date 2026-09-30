import re

import pytest

from haqwa.core.spec import suggest_rule_id

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("A customer must not be charged twice for the same order.", "no-charged-twice-order"),
        ("Every order must be approved before it is shipped.", "order-approved-before-shipped"),
        ("Refunds must be completed within 48 hours.", "refunds-completed-within-48"),
    ],
)
def test_suggested_ids(text, expected):
    assert suggest_rule_id(text) == expected


def test_deterministic():
    text = "Never ship an order after it was cancelled."
    assert suggest_rule_id(text) == suggest_rule_id(text)


def test_existing_ids_get_suffix():
    text = "Never ship an order after it was cancelled."
    base = suggest_rule_id(text)
    assert suggest_rule_id(text, [base]) == f"{base}-2"
    assert suggest_rule_id(text, [base, f"{base}-2"]) == f"{base}-3"


@pytest.mark.parametrize("text", ["", "!!!", "The a an of", "Ünïcödé rule ✓", "123 go"])
def test_always_valid_c1_id(text):
    assert ID_RE.match(suggest_rule_id(text))
