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


def _words(name: str) -> str:
    """Event or field name as plain words: "refund_requested" -> "refund requested"."""
    return name.replace("_", " ").strip()


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:]


def _noun(per: str) -> str:
    """Entity key as a noun: "order_id" -> "order"."""
    return _words(per.removesuffix("_id")) or "item"


def _duration(d: timedelta) -> str:
    """Owner-facing duration: "24 hours", "1 hour"; falls back to "1h30m"."""
    seconds = int(d.total_seconds())
    if seconds and seconds % 3600 == 0:
        hours = seconds // 3600
        return f"{hours} hour" if hours == 1 else f"{hours} hours"
    return fmt_duration(d)


def canonical_examples(rule: Rule) -> list[CanonicalExample]:
    """Minimum set per pattern: core case, reversed order (two-event patterns), other entity.

    Labels are short plain-English situations for the policy owner (the confirmation
    card asks "<label>. Is this allowed?"), so they use words, not raw event names.
    """
    p = rule.per
    noun = _noun(p)
    other = f"a different {noun}"

    if isinstance(rule, AtMostOnce):
        e = rule.event
        we = _words(e)
        return [
            CanonicalExample(_sentence(f"{we} once"), (_t(e),), False),
            CanonicalExample(_sentence(f"{we} twice for the same {noun}"), (_t(e), _t(e)), True),
            CanonicalExample(
                _sentence(f"{we} once each for two different {noun}s"),
                (_t(e), _t(e, entity=OTHER_ENTITY, per=p)),
                False,
            ),
        ]

    if isinstance(rule, NeverAfter):
        e, a = rule.event, rule.after
        we, wa = _words(e), _words(a)
        return [
            CanonicalExample(_sentence(f"{we} after {wa}"), (_t(a), _t(e)), True),
            CanonicalExample(_sentence(f"{we} before {wa}"), (_t(e), _t(a)), False),
            CanonicalExample(
                _sentence(f"{wa} for one {noun}, then {we} for {other}"),
                (_t(a), _t(e, entity=OTHER_ENTITY, per=p)),
                False,
            ),
        ]

    if isinstance(rule, MustPrecede):
        e, r = rule.event, rule.requires
        we, wr = _words(e), _words(r)
        return [
            CanonicalExample(_sentence(f"{wr}, then {we}"), (_t(r), _t(e)), False),
            CanonicalExample(_sentence(f"{we} before {wr}"), (_t(e), _t(r)), True),
            CanonicalExample(
                _sentence(f"{wr} for one {noun}, but {we} for {other}"),
                (_t(r), _t(e, entity=OTHER_ENTITY, per=p)),
                True,
            ),
        ]

    if isinstance(rule, WithinTime):
        s, e, w = rule.start, rule.event, rule.within
        ws, we = _words(s), _words(e)
        zero, hour = timedelta(0), timedelta(hours=1)
        late = _duration(w + hour)
        examples = [
            CanonicalExample(
                _sentence(f"{we} exactly {_duration(w)} after {ws}"),
                (_t(s, zero), _t(e, w)),
                False,
            ),
            CanonicalExample(
                _sentence(f"{we} {late} after {ws} (1 hour too late)"),
                (_t(s, zero), _t(e, w + hour)),
                True,
            ),
            CanonicalExample(
                _sentence(f"{we} before {ws}"),
                (_t(e, zero), _t(s, timedelta(seconds=1))),
                False,
            ),
            CanonicalExample(
                _sentence(f"{ws} for one {noun}; {we} only for {other}, {late} later"),
                (_t(s, zero), _t(e, w + hour, entity=OTHER_ENTITY, per=p)),
                True,
            ),
        ]
        if w < _CALENDAR_GAP:
            # Owner decision (golden G3.1): calendar hours, weekends included.
            examples.append(
                CanonicalExample(
                    _sentence(f"{ws} on Fri 17:00, {we} on Mon 10:00 (the weekend counts)"),
                    (_t(s, zero), _t(e, _CALENDAR_GAP)),
                    True,
                )
            )
        return examples

    raise ValueError(f"no canonical examples for pattern {rule.pattern!r}")
