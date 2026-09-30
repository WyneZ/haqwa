import pytest

from haqwa import load_events
from haqwa.adapters.pytest import assert_policies


def test_violation_raises_with_timeline(shop_dir):
    with pytest.raises(AssertionError, match="no-double-charge"):
        assert_policies(
            shop_dir / "rules.spec.yaml",
            load_events(shop_dir / "events.json"),
            event_map=shop_dir / "events.map.yaml",
        )


def test_clean_events_return_report(shop_dir):
    events = [
        e
        for e in load_events(shop_dir / "events.json")
        if not (e.data["order_id"] == "A-1" and e.ts.second == 45)
    ]
    report = assert_policies(
        shop_dir / "rules.spec.yaml", events, event_map=shop_dir / "events.map.yaml"
    )
    assert report.passed
