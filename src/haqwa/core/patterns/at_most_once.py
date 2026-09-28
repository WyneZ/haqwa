"""`at_most_once`: `event` may happen at most once per entity.

Semantics (DRAFT):
- Events matching an `allow_if` are not counted.
- A `reset_after` event sets the count back to 0.
- Every counted `event` beyond the first (since the last reset) is a finding.
"""

from __future__ import annotations

from ..conditions import is_allowed, reset_events
from ..events import Event
from ..spec import AtMostOnce
from .base import Finding


def evaluate(rule: AtMostOnce, events: list[Event]) -> list[Finding]:
    resets = reset_events(rule)
    count = 0
    findings: list[Finding] = []
    for i, e in enumerate(events):
        if e.event in resets:
            count = 0
        elif e.event == rule.event and not is_allowed(rule, e):
            count += 1
            if count > 1:
                suffix = f" with no {' / '.join(sorted(resets))} in between" if resets else ""
                findings.append(Finding(i, f"'{rule.event}' happened {count} times{suffix}"))
    return findings
