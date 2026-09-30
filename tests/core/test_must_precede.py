from haqwa.core.patterns.must_precede import evaluate

from .helpers import ev, mp

RESET = [{"reset_after": "edited"}]
INTERNAL = [{"allow_if": {"field": "channel", "op": "eq", "value": "internal"}}]


def idx(findings):
    return [f.index for f in findings]


# ---- positive: no violation ----
def test_requires_before_event_passes():
    assert evaluate(mp(), [ev("approved", 0), ev("shipped", 1)]) == []


def test_one_requires_enables_many_events():
    assert evaluate(mp(), [ev("approved", 0), ev("shipped", 1), ev("shipped", 2)]) == []


def test_requires_alone_passes():
    assert evaluate(mp(), [ev("approved", 0)]) == []


def test_empty_stream_passes():
    assert evaluate(mp(), []) == []


def test_allowed_event_needs_no_requires():
    evs = [ev("shipped", 0, channel="internal")]
    assert evaluate(mp(**{"except": INTERNAL}), evs) == []


def test_requires_again_after_reset_enables():
    evs = [ev("approved", 0), ev("edited", 1), ev("approved", 2), ev("shipped", 3)]
    assert evaluate(mp(**{"except": RESET}), evs) == []


# ---- negative: violation ----
def test_event_without_requires_is_violation():
    f = evaluate(mp(), [ev("shipped", 0)])
    assert idx(f) == [0]
    assert "without an earlier 'approved'" in f[0].message


def test_reversed_order_is_violation():
    assert idx(evaluate(mp(), [ev("shipped", 0), ev("approved", 1)])) == [0]


def test_reset_clears_requires():
    evs = [ev("approved", 0), ev("edited", 1), ev("shipped", 2)]
    f = evaluate(mp(**{"except": RESET}), evs)
    assert idx(f) == [2]
    assert "since the last 'edited'" in f[0].message


def test_allowed_requires_does_not_enable():
    evs = [ev("approved", 0, channel="internal"), ev("shipped", 1)]
    assert idx(evaluate(mp(**{"except": INTERNAL}), evs)) == [1]


def test_every_unenabled_event_is_reported():
    assert idx(evaluate(mp(), [ev("shipped", 0), ev("shipped", 1)])) == [0, 1]
