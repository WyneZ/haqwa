"""Exception helpers shared by all patterns (`reset_after`, `allow_if`).

Semantics (DRAFT):
- `reset_after`: when a reset event happens for the entity, the rule forgets
  everything it saw before for that entity. Reset events always reset
  (allow_if is not checked for them).
- `allow_if`: any other event that matches ANY allow_if condition is ignored by
  the rule (it is not counted, does not trigger and does not violate).
- A condition on a field the event doesn't have is False (never allows).
"""

from __future__ import annotations

from .events import Event
from .spec import AllowIf, Condition, ResetAfter, Rule


def matches(cond: Condition, event: Event) -> bool:
    """True if `event.data` satisfies the condition. Missing field -> False."""
    if cond.field not in event.data:
        return False
    actual = event.data[cond.field]
    if cond.op == "eq":
        return actual == cond.value
    if cond.op == "ne":
        return actual != cond.value
    if cond.op == "in":
        return actual in cond.value  # type: ignore[operator]
    raise ValueError(f"unknown op {cond.op!r}")  # unreachable: spec validation


def reset_events(rule: Rule) -> set[str]:
    """Event names that reset the rule for an entity."""
    return {x.reset_after for x in rule.exceptions if isinstance(x, ResetAfter)}


def is_allowed(rule: Rule, event: Event) -> bool:
    """True if an `allow_if` exception exempts this event."""
    return any(matches(x.allow_if, event) for x in rule.exceptions if isinstance(x, AllowIf))
