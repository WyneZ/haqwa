from haqwa.core.patterns.within_time import evaluate, fmt_duration

from .helpers import H, ev, wt

CANCEL = [{"reset_after": "order_cancelled"}]
MANUAL = [{"allow_if": {"field": "method", "op": "eq", "value": "manual"}}]
REQ, DONE = "refund_requested", "refund_completed"


def idx(findings):
    return [f.index for f in findings]


# ---- positive: no violation ----
def test_on_time_passes():
    assert evaluate(wt(), [ev(REQ, 0), ev(DONE, 10 * H)]) == []


def test_exactly_at_deadline_is_on_time():
    assert evaluate(wt(), [ev(REQ, 0), ev(DONE, 48 * H)]) == []


def test_open_but_trace_ends_before_deadline_passes():
    assert evaluate(wt(), [ev(REQ, 0), ev("note", 5 * H)]) == []


def test_event_without_start_is_ignored():
    assert evaluate(wt(), [ev(DONE, 0), ev(DONE, 100 * H)]) == []


def test_reset_cancels_obligation():
    evs = [ev(REQ, 0), ev("order_cancelled", 1 * H), ev("note", 100 * H)]
    assert evaluate(wt(**{"except": CANCEL}), evs) == []


def test_allowed_start_opens_nothing():
    evs = [ev(REQ, 0, method="manual"), ev("note", 100 * H)]
    assert evaluate(wt(**{"except": MANUAL}), evs) == []


def test_empty_stream_passes():
    assert evaluate(wt(), []) == []


# ---- negative: violation ----
def test_late_event_is_violation():
    f = evaluate(wt(), [ev(REQ, 0), ev(DONE, 49 * H)])
    assert idx(f) == [1]
    assert "49h after 'refund_requested' (limit 48h)" in f[0].message


def test_weekend_counts_calendar_hours():
    # Fri 17:00 -> Mon 10:00 = 65 h (owner decision: calendar hours)
    assert idx(evaluate(wt(), [ev(REQ, 0), ev(DONE, 65 * H)])) == [1]


def test_never_happened_and_trace_past_deadline():
    f = evaluate(wt(), [ev(REQ, 0), ev("note", 50 * H)])
    assert idx(f) == [1]
    assert "did not happen within 48h" in f[0].message


def test_trace_end_from_other_entities_counts():
    # The entity's own stream ends at the request, but the checked trace ran 60 h.
    later = ev("x", 60 * H).ts
    assert idx(evaluate(wt(), [ev(REQ, 0)], trace_end=later)) == [0]


def test_second_start_after_fulfilled_one_needs_its_own_event():
    evs = [ev(REQ, 0), ev(DONE, 1 * H), ev(REQ, 2 * H), ev("note", 60 * H)]
    assert idx(evaluate(wt(), evs)) == [3]


def test_allowed_event_does_not_fulfil():
    evs = [ev(REQ, 0), ev(DONE, 1 * H, method="manual"), ev("note", 50 * H)]
    assert idx(evaluate(wt(**{"except": MANUAL}), evs)) == [2]


def test_fmt_duration():
    from datetime import timedelta

    assert fmt_duration(timedelta(hours=48)) == "48h"
    assert fmt_duration(timedelta(hours=49)) == "49h"
    assert fmt_duration(timedelta(minutes=90)) == "1h30m"
    assert fmt_duration(timedelta(seconds=45)) == "45s"
