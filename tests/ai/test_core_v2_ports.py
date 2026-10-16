"""Track B placeholders expose explicit limitations without calling Gemini."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from haqwa.ai.clarify_v2 import AddReset
from haqwa.ai.core_v2_ports import provisional_ports

from .test_clarify_v2 import reset, rule


def test_provisional_ports_are_frozen_and_explicit() -> None:
    ports = provisional_ports()
    original = rule()
    patch = AddReset.model_validate(reset())
    snapshot = original.model_dump_json()
    example = ports.make_example(original, patch)
    assert example is not None and example.label.startswith("PLACEHOLDER")
    assert example.timeline and ports.canonical_examples(original) == []
    assert original.model_dump_json() == snapshot
    with pytest.raises(NotImplementedError, match="core apply_patch_v2 not merged yet"):
        ports.apply_patch(original, patch)
    with pytest.raises(FrozenInstanceError):
        ports.apply_patch = lambda *_: original
