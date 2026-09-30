"""pytest helper: fail a test with a readable timeline when a policy is broken.

from haqwa.adapters.pytest import assert_policies

def test_checkout_follows_policy(recorded_events):
    assert_policies("rules.spec.yaml", recorded_events, event_map="events.map.yaml")
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ..core.checker import check
from ..core.compiler import compile_spec
from ..core.events import Event, EventMap, load_event_map
from ..core.report import Report, format_text
from ..core.spec import Spec, load_spec


def assert_policies(
    spec: Spec | str | Path,
    events: Iterable[Event],
    event_map: EventMap | str | Path | None = None,
) -> Report:
    """Compile (with self-test) and check; raise AssertionError with the timeline on violation."""
    if not isinstance(spec, Spec):
        spec = load_spec(spec)
    if event_map is not None and not isinstance(event_map, EventMap):
        event_map = load_event_map(event_map)
    report = check(compile_spec(spec, event_map), events, event_map)
    if not report.passed:
        raise AssertionError("Policy violation\n" + format_text(report))
    return report
