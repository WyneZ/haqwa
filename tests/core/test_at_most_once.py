from haqwa.core.patterns.at_most_once import evaluate

from .helpers import amo, ev

RESET = [{"reset_after": "refunded"}]
INSTALLMENT = [{"allow_if": {"field": "payment_type", "op": "eq", "value": "installment"}}]


# ---- positive: no violation ----
def test_single_event_passes():
    assert evaluate(amo(), [ev("charged", 0)]) == []


def test_no_events_passes():
    assert evaluate(amo(), []) == []


def test_other_events_ignored():
    assert evaluate(amo(), [ev("charged", 0), ev("shipped", 1), ev("emailed", 2)]) == []


def test_reset_after_allows_second():
    evs = [ev("charged", 0), ev("refunded", 1), ev("charged", 2)]
    assert evaluate(amo(**{"except": RESET}), evs) == []


def test_allow_if_exempts_matching_events():
    evs = [
        ev("charged", 0, payment_type="installment"),
        ev("charged", 1, payment_type="installment"),
    ]
    assert evaluate(amo(**{"except": INSTALLMENT}), evs) == []


def test_allowed_event_does_not_count_toward_limit():
    evs = [ev("charged", 0, payment_type="installment"), ev("charged", 1)]
    assert evaluate(amo(**{"except": INSTALLMENT}), evs) == []


# ---- negative: violation ----
def test_second_event_is_violation():
    f = evaluate(amo(), [ev("charged", 0), ev("charged", 1)])
    assert [x.index for x in f] == [1]


def test_every_extra_event_is_reported():
    f = evaluate(amo(), [ev("charged", i) for i in range(3)])
    assert [x.index for x in f] == [1, 2]


def test_reset_before_first_event_does_not_help():
    evs = [ev("refunded", 0), ev("charged", 1), ev("charged", 2)]
    assert [x.index for x in evaluate(amo(**{"except": RESET}), evs)] == [2]


def test_violation_after_reset_cycle():
    evs = [ev("charged", 0), ev("refunded", 1), ev("charged", 2), ev("charged", 3)]
    f = evaluate(amo(**{"except": RESET}), evs)
    assert [x.index for x in f] == [3]
    assert "refunded" in f[0].message


def test_allow_if_does_not_exempt_non_matching():
    evs = [ev("charged", 0, payment_type="full"), ev("charged", 1, payment_type="full")]
    assert len(evaluate(amo(**{"except": INSTALLMENT}), evs)) == 1
