"""Check private shop effects against a sealed spec."""

from __future__ import annotations

from pathlib import Path

from haqwa.adapters.agentproof import effects_to_events
from haqwa.core.checker import check
from haqwa.core.compiler import compile_spec
from haqwa.core.events import Event
from haqwa.core.report import Report
from haqwa.core.spec import load_spec

DEFAULT_SPEC = Path(__file__).resolve().parents[3] / "examples/shop/rules.spec.yaml"


def verdict(effects: list, spec_path: Path = DEFAULT_SPEC) -> tuple[list[Event], Report]:
    """Convert committed effects and run the deterministic policy checker."""
    events = effects_to_events(effects)
    return events, check(compile_spec(load_spec(spec_path)), events)
