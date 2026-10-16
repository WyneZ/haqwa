"""Track A's single integration point for the pending Track B v2 functions.

When B5 lands, replace the provisional implementations with core imports in this
file only. Keep patch conversion here if Track B's final patch types differ.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from haqwa.core.canonical import CanonicalExample
from haqwa.core.rules_v2 import RuleV2, SelectNode
from haqwa.core.spec import TimelineEvent

from .clarify_v2 import Patch

type ApplyPatch = Callable[[RuleV2, Patch], RuleV2]
type CanonicalExamples = Callable[[RuleV2], list[CanonicalExample]]
type MakeExample = Callable[[RuleV2, Patch], CanonicalExample | None]


@dataclass(frozen=True)
class CoreV2Ports:
    """Injected deterministic core operations; none of these calls Gemini."""

    apply_patch: ApplyPatch
    canonical_examples: CanonicalExamples
    make_example: MakeExample


def provisional_ports() -> CoreV2Ports:
    """Return explicit stage 1 placeholders until B5 supplies the core imports."""

    def make_example(rule: RuleV2, patch: Patch) -> CanonicalExample:
        event = next(node.event for node in rule.nodes if isinstance(node, SelectNode))
        return CanonicalExample(
            label="PLACEHOLDER: no boundary timeline or verdict has been checked",
            timeline=(TimelineEvent(event=event),),
            violation=False,
        )

    def canonical_examples(rule: RuleV2) -> list[CanonicalExample]:
        return []

    def apply_patch(rule: RuleV2, patch: Patch) -> RuleV2:
        raise NotImplementedError("core apply_patch_v2 not merged yet")

    return CoreV2Ports(
        apply_patch=apply_patch, canonical_examples=canonical_examples, make_example=make_example
    )
