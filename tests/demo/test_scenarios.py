import asyncio
import time

import pytest

pytest.importorskip("agentproof")

from agentproof.core.world import World  # noqa: E402

from haqwa import load_spec  # noqa: E402
from haqwa.core.errors import HaqwaError  # noqa: E402
from haqwa.demo import iter_scenario, list_scenarios, run_scenario  # noqa: E402
from haqwa.demo.shop import setup_shop  # noqa: E402


@pytest.fixture
def spec(shop_dir):
    return load_spec(shop_dir / "rules.spec.yaml")


@pytest.mark.parametrize(
    "scenario", [s for s in list_scenarios() if s["fault"] != "recorded"], ids=lambda s: s["id"]
)
def test_scenario_gives_expected_verdict(scenario, spec):
    events, report = run_scenario(scenario["id"], spec)
    assert ("pass" if report.passed else "violation") == scenario["expected"]
    if scenario["fault"] != "stale_state":
        charges = [e for e in events if e.event == "charged"]
        assert len(charges) == (1 if scenario["expected"] == "pass" else 2)


def test_stale_status_naive_violates_never_ship_after_cancel(spec):
    events, report = run_scenario("stale_status_naive", spec)
    assert [event.event for event in events] == ["order_created", "charged", "cancelled", "shipped"]
    rule = next(result for result in report.results if result.rule_id == "never-ship-after-cancel")
    assert rule.status == "violation"
    assert len(rule.violations) == 1
    assert [event.event for event in rule.violations[0].timeline][-2:] == ["cancelled", "shipped"]


def test_stale_status_fixed_checks_rule_without_shipping(spec):
    events, report = run_scenario("stale_status_fixed", spec)
    checked_events = [event for event in events if event.event in {"cancelled", "shipped"}]
    assert len(checked_events) > 0
    assert [event.event for event in checked_events] == ["cancelled"]
    rule = next(result for result in report.results if result.rule_id == "never-ship-after-cancel")
    assert rule.status == "pass"
    assert report.passed


def test_ship_precondition_rejects_cancelled_order_without_effect():
    world = World()
    setup_shop(world)

    async def exercise():
        await world.tools.invoke("create_order", {"order_id": "A-1", "amount": 50})
        await world.tools.invoke("charge_payment", {"order_id": "A-1", "amount": 50})
        await world.tools.invoke("cancel_order", {"order_id": "A-1"})
        before = world.effects.snapshot()
        result = await world.tools.invoke("ship_order", {"order_id": "A-1", "if_status": "paid"})
        assert result == {"status": "rejected"}
        assert world.effects.snapshot() == before
        assert await world.tools.invoke("get_order", {"order_id": "A-1"}) == {
            "order_id": "A-1",
            "status": "cancelled",
        }
        assert world.effects.snapshot() == before

    asyncio.run(exercise())


def test_every_fault_has_a_naive_and_a_fixed_agent():
    pairs = {(s["fault"], s["agent"]) for s in list_scenarios()}
    for fault in {s["fault"] for s in list_scenarios() if s["fault"] != "recorded"}:
        assert {(fault, "naive"), (fault, "fixed")} <= pairs


def test_scenarios_are_fast_enough_for_a_synchronous_api(spec):
    start = time.perf_counter()
    for s in list_scenarios():
        run_scenario(s["id"], spec)
    assert time.perf_counter() - start < 5


def test_unknown_scenario(spec):
    with pytest.raises(HaqwaError) as exc:
        run_scenario("nope", spec)
    assert exc.value.code == "unknown_scenario"


def test_stream_matches_run_scenario(spec):
    for scenario in list_scenarios():
        items = list(iter_scenario(scenario["id"], spec))
        events, report = run_scenario(scenario["id"], spec)
        assert [value for kind, value in items if kind == "event"] == events
        assert items[-1] == ("report", report)


def test_rules_the_scenario_never_touches_are_not_tested(spec):
    # The demo shop only creates orders and charges; a "never ship after cancel" rule
    # passes trivially and must be reported as not tested, not as a real pass.
    from haqwa.core.spec import NeverAfter, Spec

    ship_rule = NeverAfter.model_validate(
        {
            "id": "no-ship-after-cancel",
            "source": "A cancelled order must never be shipped.",
            "pattern": "never_after",
            "event": "shipped",
            "after": "cancelled",
            "per": "order_id",
        }
    )
    _, report = run_scenario("payment_timeout_naive", Spec(rules=[*spec.rules, ship_rule]))
    by_id = {r.rule_id: r for r in report.results}
    assert by_id[spec.rules[0].id].tested
    assert not by_id["no-ship-after-cancel"].tested
