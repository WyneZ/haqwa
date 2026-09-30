"""`never_after`: once `after` has happened for an entity, `event` must not happen.

Semantics (DRAFT, Track B):
- Order is the time-sorted stream order; "after" means strictly later in that order.
- Events matching an `allow_if` are ignored (they neither trigger nor violate).
- A `reset_after` event disarms the rule until `after` happens again.
- Every `event` while armed is a finding.
- `event == after` is allowed and behaves like "at most once".
"""

from __future__ import annotations

from datetime import datetime

from ..conditions import is_allowed, reset_events
from ..events import Event
from ..spec import NeverAfter
from .base import Finding


def evaluate(
    rule: NeverAfter, events: list[Event], trace_end: datetime | None = None
) -> list[Finding]:
    del trace_end  # not time-based
    resets = reset_events(rule)
    armed = False
    findings: list[Finding] = []
    for i, e in enumerate(events):
        if e.event in resets:
            armed = False
            continue
        if is_allowed(rule, e):
            continue
        # Check before arming, so `event == after` flags the second occurrence, not the first.
        if armed and e.event == rule.event:
            findings.append(Finding(i, f"'{rule.event}' happened after '{rule.after}'"))
        if e.event == rule.after:
            armed = True
    return findings
