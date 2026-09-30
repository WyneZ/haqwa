"""Small builders so tests read like timelines."""

from datetime import UTC, datetime, timedelta
from typing import Any

from haqwa.core.events import Event
from haqwa.core.spec import AtMostOnce, MustPrecede, NeverAfter, WithinTime

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def ev(name: str, sec: int, order: str = "o1", **data: Any) -> Event:
    return Event(event=name, ts=T0 + timedelta(seconds=sec), data={"order_id": order, **data})


def amo(**kw: Any) -> AtMostOnce:
    base = {
        "id": "r",
        "source": "s",
        "pattern": "at_most_once",
        "event": "charged",
        "per": "order_id",
    }
    return AtMostOnce.model_validate({**base, **kw})


def nav(**kw: Any) -> NeverAfter:
    base = {
        "id": "r",
        "source": "s",
        "pattern": "never_after",
        "event": "shipped",
        "after": "cancelled",
        "per": "order_id",
    }
    return NeverAfter.model_validate({**base, **kw})


def mp(**kw: Any) -> MustPrecede:
    base = {
        "id": "r",
        "source": "s",
        "pattern": "must_precede",
        "event": "shipped",
        "requires": "approved",
        "per": "order_id",
    }
    return MustPrecede.model_validate({**base, **kw})


def wt(**kw: Any) -> WithinTime:
    base = {
        "id": "r",
        "source": "s",
        "pattern": "within_time",
        "start": "refund_requested",
        "event": "refund_completed",
        "within": "PT48H",
        "per": "order_id",
    }
    return WithinTime.model_validate({**base, **kw})


H = 3600  # seconds per hour, for ev(name, sec)
