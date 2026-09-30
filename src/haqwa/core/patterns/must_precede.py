"""`must_precede`: `event` may only happen if `requires` happened earlier for the entity.

Semantics (DRAFT, Track B):
- One `requires` enables any number of later `event`s (it is not consumed).
- Events matching an `allow_if` are ignored (an allowed `event` needs no `requires`,
  an allowed `requires` does not enable anything).
- A `reset_after` event clears the enabling `requires`.
- Every `event` without an earlier `requires` (since the last reset) is a finding.
"""

from __future__ import annotations

from datetime import datetime

from ..conditions import is_allowed, reset_events
from ..events import Event
from ..spec import MustPrecede
from .base import Finding


def evaluate(
    rule: MustPrecede, events: list[Event], trace_end: datetime | None = None
) -> list[Finding]:
    del trace_end  # not time-based
    resets = reset_events(rule)
    enabled = False
    findings: list[Finding] = []
    for i, e in enumerate(events):
        if e.event in resets:
            enabled = False
            continue
        if is_allowed(rule, e):
            continue
        if e.event == rule.event and not enabled:
            suffix = f" (since the last '{' / '.join(sorted(resets))}')" if resets else ""
            findings.append(
                Finding(i, f"'{rule.event}' happened without an earlier '{rule.requires}'{suffix}")
            )
        if e.event == rule.requires:
            enabled = True
    return findings
