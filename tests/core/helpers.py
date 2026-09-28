"""Small builders so tests read like timelines."""

from datetime import UTC, datetime, timedelta
from typing import Any

from haqwa.core.events import Event
from haqwa.core.spec import AtMostOnce

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
