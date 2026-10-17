"""core_ports() wires Track A patch models to Track B's real v2 functions (B5)."""

from __future__ import annotations

from haqwa.ai.clarify_v2 import AddExclude, AddReset
from haqwa.ai.core_v2_ports import core_ports

from .test_clarify_v2 import exclude, reset, rule


def test_apply_patch_accepts_track_a_reset_model() -> None:
    patched = core_ports().apply_patch(rule(), AddReset.model_validate(reset()))
    assert patched.nodes[-1].since == ["refunded"]


def test_apply_patch_accepts_track_a_exclude_model() -> None:
    patched = core_ports().apply_patch(rule(), AddExclude.model_validate(exclude()))
    select = next(n for n in patched.nodes if n.id == "charges")
    assert [(c.field, c.op, c.value) for c in select.exclude] == [
        ("payment_type", "eq", "installment")
    ]


def test_make_example_separates_yes_from_no() -> None:
    example = core_ports().make_example(rule(), AddReset.model_validate(reset()))
    assert example is not None
    assert [e.event for e in example.timeline].count("refunded") == 1
    assert example.violation is True  # No keeps the rule: this timeline breaks it


def test_canonical_examples_come_from_core() -> None:
    examples = core_ports().canonical_examples(rule())
    assert 1 <= len(examples) <= 3
