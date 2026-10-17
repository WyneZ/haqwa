"""Expand a sealed v1 pattern into its proposed v2 rule form.

This module is not called by the production checker. It supports parity testing before
the old pattern evaluators are replaced.
"""

from __future__ import annotations

from typing import Any

from .rules_v2 import RuleV2
from .spec import (
    AllowIf,
    AtMostOnce,
    MustPrecede,
    NeverAfter,
    ResetAfter,
    Rule,
    WithinTime,
    iso_duration,
)


def expand_v1(rule: Rule) -> RuleV2:
    """Return a flat v2 preset with the v1 exceptions on every relevant select."""
    since = [
        exception.reset_after for exception in rule.exceptions if isinstance(exception, ResetAfter)
    ]
    exclude = [
        exception.allow_if.model_dump(mode="json")
        for exception in rule.exceptions
        if isinstance(exception, AllowIf)
    ]

    def select(node_id: str, event: str) -> dict[str, Any]:
        return {"id": node_id, "type": "select", "event": event, "where": [], "exclude": exclude}

    if isinstance(rule, AtMostOnce):
        nodes = [
            select("target", rule.event),
            {"id": "rule", "type": "count", "of": "target", "op": "le", "value": 1, "since": since},
        ]
    elif isinstance(rule, NeverAfter):
        nodes = [
            select("target", rule.event),
            select("trigger", rule.after),
            {
                "id": "rule",
                "type": "none_after",
                "of": "target",
                "after": "trigger",
                "since": since,
            },
        ]
    elif isinstance(rule, MustPrecede):
        nodes = [
            select("target", rule.event),
            select("prerequisite", rule.requires),
            {
                "id": "rule",
                "type": "every_preceded_by",
                "of": "target",
                "by": "prerequisite",
                "since": since,
            },
        ]
    elif isinstance(rule, WithinTime):
        nodes = [
            select("start", rule.start),
            select("finish", rule.event),
            {
                "id": "rule",
                "type": "every_followed_within",
                "start": "start",
                "by": "finish",
                "within": iso_duration(rule.within),
                "since": since,
            },
        ]
    else:
        raise TypeError(f"unsupported v1 rule type: {type(rule).__name__}")

    return RuleV2.model_validate(
        {
            "id": rule.id,
            "source": rule.source,
            "per": rule.per,
            "version": 2,
            "nodes": nodes,
            "root": "rule",
        }
    )
