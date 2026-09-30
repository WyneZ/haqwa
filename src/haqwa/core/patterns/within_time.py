"""`within_time`: after `start`, `event` must happen within `within` for the same entity.

Semantics (DRAFT, Track B):
- The window is elapsed (calendar) time: weekends and nights count. An `event` exactly
  at the deadline is on time.
- Each `start` opens an obligation; the next `event` fulfils every open obligation.
  If it comes after a deadline, it is a finding (late).
- End of trace (open question Q2, option B): an obligation still open is a finding only if
  the end of the checked trace (last event of ANY entity) is past its deadline; otherwise
  it passes. The finding points at the entity's last event.
- A `reset_after` event cancels open obligations (e.g. the order was cancelled).
- Events matching an `allow_if` are ignored. An `event` with no open obligation is ignored.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ..conditions import is_allowed, reset_events
from ..events import Event
from ..spec import WithinTime
from .base import Finding


def fmt_duration(d: timedelta) -> str:
    """Short human form in hours, as policies say it: 48h, 65h, 1h30m, 45s."""
    total = int(d.total_seconds())
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    parts = [f"{h}h" if h else "", f"{m}m" if m else "", f"{s}s" if s else ""]
    return "".join(parts) or "0s"


def evaluate(
    rule: WithinTime, events: list[Event], trace_end: datetime | None = None
) -> list[Finding]:
    resets = reset_events(rule)
    limit = fmt_duration(rule.within)
    open_starts: list[Event] = []
    findings: list[Finding] = []
    for i, e in enumerate(events):
        if e.event in resets:
            open_starts.clear()
            continue
        if is_allowed(rule, e):
            continue
        if e.event == rule.event and open_starts:
            late = [s for s in open_starts if e.ts - s.ts > rule.within]
            if late:
                took = fmt_duration(e.ts - late[0].ts)
                findings.append(
                    Finding(
                        i,
                        f"'{rule.event}' happened {took} after '{rule.start}' (limit {limit})",
                    )
                )
            open_starts.clear()
        elif e.event == rule.start:
            open_starts.append(e)

    if open_starts and events:
        last = len(events) - 1
        end = trace_end or events[last].ts
        overdue = [s for s in open_starts if end - s.ts > rule.within]
        if overdue:
            findings.append(
                Finding(
                    last,
                    f"'{rule.event}' did not happen within {limit} after '{rule.start}'",
                )
            )
    return findings
