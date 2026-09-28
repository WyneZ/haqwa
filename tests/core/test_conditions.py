import pytest

from haqwa.core.conditions import matches
from haqwa.core.spec import Condition

from .helpers import ev


@pytest.mark.parametrize(
    ("op", "value", "data", "expected"),
    [
        ("eq", "installment", {"payment_type": "installment"}, True),
        ("eq", "installment", {"payment_type": "full"}, False),
        ("ne", "installment", {"payment_type": "full"}, True),
        ("ne", "installment", {"payment_type": "installment"}, False),
        ("in", ["a", "b"], {"payment_type": "b"}, True),
        ("in", ["a", "b"], {"payment_type": "c"}, False),
        ("eq", "installment", {}, False),  # missing field never matches
        ("ne", "installment", {}, False),  # ...even for `ne`
    ],
)
def test_matches(op, value, data, expected):
    cond = Condition(field="payment_type", op=op, value=value)
    assert matches(cond, ev("charged", 0, **data)) is expected
