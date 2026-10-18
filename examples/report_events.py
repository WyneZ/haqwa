"""Send an agent's own C2 events to a Haqwa event session (standard library only)."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from typing import Any
from urllib.request import Request, urlopen


class Reporter:
    """Report each completed agent action to a private ingest URL."""

    def __init__(self, ingest_url: str) -> None:
        self.ingest_url = ingest_url

    def emit(self, event: str, *, ts: datetime | None = None, **data: Any) -> dict[str, Any]:
        """Send an event with its UTC action time; pass ts for an earlier action."""
        occurred_at = ts or datetime.now(UTC)
        if occurred_at.utcoffset() is None:
            raise ValueError("ts must have a timezone")
        timestamp = occurred_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
        payload = json.dumps(
            {"event": event, "ts": timestamp, "data": data}, ensure_ascii=False
        ).encode("utf-8")
        request = Request(
            self.ingest_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=10) as response:
            return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser(description="Report three sample agent events to Haqwa.")
    parser.add_argument("--url", required=True, help="Private ingest_url from an events session")
    args = parser.parse_args()
    reporter = Reporter(args.url)
    # The first packing action violates a rule that requires prior approval.
    reporter.emit("order_packed", order_id="A-1")
    reporter.emit("order_approved", order_id="A-1")
    reporter.emit("order_packed", order_id="A-1")
    print("Reported 3 events; the first packing action preceded approval.")


if __name__ == "__main__":
    main()
