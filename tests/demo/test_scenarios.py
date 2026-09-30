import time

import pytest

pytest.importorskip("agentproof")

from haqwa import load_spec  # noqa: E402
from haqwa.demo import list_scenarios, run_scenario  # noqa: E402


@pytest.fixture
def spec(shop_dir):
    return load_spec(shop_dir / "rules.spec.yaml")


@pytest.mark.parametrize("scenario", list_scenarios(), ids=lambda s: s["id"])
def test_scenario_gives_expected_verdict(scenario, spec):
    events, report = run_scenario(scenario["id"], spec)
    assert ("pass" if report.passed else "violation") == scenario["expected"]
    charges = [e for e in events if e.event == "charged"]
    assert len(charges) == (1 if scenario["expected"] == "pass" else 2)


def test_every_fault_has_a_naive_and_a_fixed_agent():
    pairs = {(s["fault"], s["agent"]) for s in list_scenarios()}
    for fault in {s["fault"] for s in list_scenarios()}:
        assert {(fault, "naive"), (fault, "fixed")} <= pairs


def test_scenarios_are_fast_enough_for_a_synchronous_api(spec):
    start = time.perf_counter()
    for s in list_scenarios():
        run_scenario(s["id"], spec)
    assert time.perf_counter() - start < 5


def test_unknown_scenario(spec):
    with pytest.raises(KeyError):
        run_scenario("nope", spec)
