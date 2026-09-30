from haqwa.core.patterns.never_after import evaluate

from .helpers import ev, nav

REOPEN = [{"reset_after": "reopened"}]
VIP = [{"allow_if": {"field": "tier", "op": "eq", "value": "vip"}}]


def idx(findings):
    return [f.index for f in findings]


# ---- positive: no violation ----
def test_event_without_trigger_passes():
    assert evaluate(nav(), [ev("shipped", 0), ev("shipped", 1)]) == []


def test_event_before_trigger_passes():
    assert evaluate(nav(), [ev("shipped", 0), ev("cancelled", 1)]) == []


def test_empty_stream_passes():
    assert evaluate(nav(), []) == []


def test_reset_disarms():
    evs = [ev("cancelled", 0), ev("reopened", 1), ev("shipped", 2)]
    assert evaluate(nav(**{"except": REOPEN}), evs) == []


def test_allowed_event_after_trigger_passes():
    evs = [ev("cancelled", 0), ev("shipped", 1, tier="vip")]
    assert evaluate(nav(**{"except": VIP}), evs) == []


def test_allowed_trigger_does_not_arm():
    evs = [ev("cancelled", 0, tier="vip"), ev("shipped", 1)]
    assert evaluate(nav(**{"except": VIP}), evs) == []


# ---- negative: violation ----
def test_event_after_trigger_is_violation():
    f = evaluate(nav(), [ev("cancelled", 0), ev("shipped", 1)])
    assert idx(f) == [1]
    assert "after 'cancelled'" in f[0].message


def test_every_event_after_trigger_is_reported():
    evs = [ev("cancelled", 0), ev("shipped", 1), ev("other", 2), ev("shipped", 3)]
    assert idx(evaluate(nav(), evs)) == [1, 3]


def test_trigger_again_after_reset_rearms():
    evs = [ev("cancelled", 0), ev("reopened", 1), ev("cancelled", 2), ev("shipped", 3)]
    assert idx(evaluate(nav(**{"except": REOPEN}), evs)) == [3]


def test_non_matching_allow_if_still_violates():
    evs = [ev("cancelled", 0), ev("shipped", 1, tier="basic")]
    assert idx(evaluate(nav(**{"except": VIP}), evs)) == [1]


def test_same_event_and_trigger_acts_like_at_most_once():
    rule = nav(event="charged", after="charged")
    assert idx(evaluate(rule, [ev("charged", 0), ev("charged", 1), ev("charged", 2)])) == [1, 2]
