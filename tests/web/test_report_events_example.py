"""The standalone reporter sends action times in the C2 shape."""

import json
from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest

from examples import report_events


def test_reporter_sends_utc_action_time_and_data(monkeypatch) -> None:
    sent = []

    def fake_urlopen(request, timeout):
        sent.append((request, timeout))
        return BytesIO(b'{"accepted":1,"total":1}')

    monkeypatch.setattr(report_events, "urlopen", fake_urlopen)
    reporter = report_events.Reporter("https://example.test/events")
    local_time = datetime(2026, 10, 18, 16, 30, tzinfo=timezone(timedelta(hours=6, minutes=30)))
    assert reporter.emit("order_approved", order_id="A-1", ts=local_time) == {
        "accepted": 1,
        "total": 1,
    }
    request, timeout = sent[0]
    assert request.full_url == "https://example.test/events"
    assert request.get_method() == "POST" and timeout == 10
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data) == {
        "event": "order_approved",
        "ts": "2026-10-18T10:00:00Z",
        "data": {"order_id": "A-1"},
    }

    with pytest.raises(ValueError, match="timezone"):
        reporter.emit("order_approved", ts=datetime(2026, 10, 18))
    assert len(sent) == 1
