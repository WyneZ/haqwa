"""Track A's single integration point for the Track B v2 functions (B5).

Routes and tests depend on `CoreV2Ports`, so tests can inject fakes and the web layer
never imports core patch internals directly.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from haqwa.core.canonical import CanonicalExample
from haqwa.core.canonical_v2 import canonical_examples_v2, make_example_v2
from haqwa.core.patches_v2 import apply_patch_v2
from haqwa.core.rules_v2 import RuleV2

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


def core_ports() -> CoreV2Ports:
    """The real Track B v2 operations (B5), adapted to Track A's patch models.

    Core validates patches with its own strict models, so Track A's patch is passed as
    plain data (same shape: decision 2026-10-16 "B5 interface").
    """
    return CoreV2Ports(
        apply_patch=lambda rule, patch: apply_patch_v2(rule, patch.model_dump()),
        canonical_examples=canonical_examples_v2,
        make_example=lambda rule, patch: make_example_v2(rule, patch.model_dump()),
    )
