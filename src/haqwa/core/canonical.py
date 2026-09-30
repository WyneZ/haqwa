"""Canonical example timelines per pattern (agreed with Track A on 2026-09-27).

One source of truth for:
1. core pytest (the evaluators must agree with every example),
2. compile self-test (examples the owner confirms become `confirmed_examples`),
3. Track A's owner confirmation cards ("Is this allowed?").

Examples use only the rule's own events and no `data` besides the entity key,
so `allow_if` never matches and no reset happens: they check the pattern itself.
Exception behaviour is asked as decision questions (Gemini), not here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from .patterns.within_time import fmt_duration
from .spec import (
    AtMostOnce,
    ConfirmedExample,
    MustPrecede,
    NeverAfter,
    Rule,
    TimelineEvent,
    WithinTime,
)

OTHER_ENTITY = "example-2"
_CALENDAR_GAP = timedelta(hours=65)  # Fri 17:00 -> Mon 10:00


@dataclass(frozen=True)
class CanonicalExample:
    """One confirmation card: a timeline, the verdict the pattern implies, and a label."""

    label: str
    timeline: tuple[TimelineEvent, ...]
    violation: bool

    def as_confirmed(self, owner_says_allowed: bool | None = None) -> ConfirmedExample:
        """Turn into a C1 confirmed example.

        "Is this allowed?" Yes -> violation False, No -> violation True. Without an answer,
        the pattern's own verdict is used.
        """
        violation = self.violation if owner_says_allowed is None else not owner_says_allowed
        return ConfirmedExample(timeline=list(self.timeline), violation=violation)


def _t(
    event: str, at: timedelta | None = None, entity: str | None = None, per: str = ""
) -> TimelineEvent:
    data = {per: entity} if entity else {}
    return TimelineEvent(event=event, data=data, at=at)


def canonical_examples(rule: Rule) -> list[CanonicalExample]:
    """Minimum set per pattern: core case, reversed order (two-event patterns), other entity."""
    p = rule.per
    other = f"a different {p}"

    if isinstance(rule, AtMostOnce):
        e = rule.event
        return [
            CanonicalExample(f"'{e}' once", (_t(e),), False),
            CanonicalExample(f"'{e}' twice for the same {p}", (_t(e), _t(e)), True),
            CanonicalExample(
                f"'{e}' once each for two different {p}s",
                (_t(e), _t(e, entity=OTHER_ENTITY, per=p)),
                False,
            ),
        ]

    if isinstance(rule, NeverAfter):
        e, a = rule.event, rule.after
        return [
            CanonicalExample(f"'{e}' after '{a}'", (_t(a), _t(e)), True),
            CanonicalExample(f"'{e}' before '{a}'", (_t(e), _t(a)), False),
            CanonicalExample(
                f"'{a}' for one {p}, then '{e}' for {other}",
                (_t(a), _t(e, entity=OTHER_ENTITY, per=p)),
                False,
            ),
        ]

    if isinstance(rule, MustPrecede):
        e, r = rule.event, rule.requires
        return [
            CanonicalExample(f"'{r}' then '{e}'", (_t(r), _t(e)), False),
            CanonicalExample(f"'{e}' before '{r}'", (_t(e), _t(r)), True),
            CanonicalExample(
                f"'{r}' for one {p}, then '{e}' for {other}",
                (_t(r), _t(e, entity=OTHER_ENTITY, per=p)),
                True,
            ),
        ]

    if isinstance(rule, WithinTime):
        s, e, w = rule.start, rule.event, rule.within
        zero, hour = timedelta(0), timedelta(hours=1)
        examples = [
            CanonicalExample(
                f"'{e}' exactly {fmt_duration(w)} after '{s}'", (_t(s, zero), _t(e, w)), False
            ),
            CanonicalExample(
                f"'{e}' {fmt_duration(w + hour)} after '{s}'",
                (_t(s, zero), _t(e, w + hour)),
                True,
            ),
            CanonicalExample(
                f"'{e}' before '{s}'", (_t(e, zero), _t(s, timedelta(seconds=1))), False
            ),
            CanonicalExample(
                f"'{s}' for one {p}, '{e}' only for {other} ({fmt_duration(w + hour)} later)",
                (_t(s, zero), _t(e, w + hour, entity=OTHER_ENTITY, per=p)),
                True,
            ),
        ]
        if w < _CALENDAR_GAP:
            # Owner decision (golden G3.1): calendar hours, weekends included.
            examples.append(
                CanonicalExample(
                    f"'{s}' Fri 17:00, '{e}' Mon 10:00 (weekend counts)",
                    (_t(s, zero), _t(e, _CALENDAR_GAP)),
                    True,
                )
            )
        return examples

    raise ValueError(f"no canonical examples for pattern {rule.pattern!r}")
