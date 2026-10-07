from haqwa import Spec, check, compile_spec, format_text, load_event_map, load_events, load_spec

from .helpers import ev


def run_shop(shop_dir):
    compiled = compile_spec(
        load_spec(shop_dir / "rules.spec.yaml"), load_event_map(shop_dir / "events.map.yaml")
    )
    return check(
        compiled,
        load_events(shop_dir / "events.json"),
        load_event_map(shop_dir / "events.map.yaml"),
    )


def test_double_charge_caught_with_timeline(shop_dir):
    report = run_shop(shop_dir)
    assert not report.passed
    result = next(r for r in report.results if r.rule_id == "no-double-charge")
    shipping_rule = next(r for r in report.results if r.rule_id == "never-ship-after-cancel")
    assert shipping_rule.status == "pass"
    (v,) = result.violations  # only A-1; B-2 was refunded in between
    assert v.entity == "A-1"
    assert [e.event for e in v.timeline] == ["order_created", "charged", "charged"]
    assert v.offending_index == 2


def test_clean_events_pass(shop_dir):
    compiled = compile_spec(load_spec(shop_dir / "rules.spec.yaml"))
    events = [
        e
        for e in load_events(shop_dir / "events.json")
        if not (e.data["order_id"] == "A-1" and e.ts.second == 45)
    ]
    report = check(compiled, events, load_event_map(shop_dir / "events.map.yaml"))
    assert report.passed


def test_input_order_does_not_matter(shop_dir):
    compiled = compile_spec(load_spec(shop_dir / "rules.spec.yaml"))
    emap = load_event_map(shop_dir / "events.map.yaml")
    events = load_events(shop_dir / "events.json")
    assert check(compiled, events, emap) == check(compiled, list(reversed(events)), emap)


def test_deterministic_across_runs(shop_dir):
    reports = {run_shop(shop_dir).model_dump_json() for _ in range(10)}
    assert len(reports) == 1


def test_text_report_marks_offending_event(shop_dir):
    text = format_text(run_shop(shop_dir))
    assert "[VIOLATION] no-double-charge" in text
    assert ">> 2026-10-01T10:00:45+00:00  charged" in text


def test_requires_of_one_entity_does_not_enable_another():
    spec = Spec.model_validate(
        {
            "rules": [
                {
                    "id": "approve-before-ship",
                    "source": "An order must be approved before it is shipped.",
                    "pattern": "must_precede",
                    "event": "shipped",
                    "requires": "approved",
                    "per": "order_id",
                }
            ]
        }
    )
    events = [ev("approved", 0, "o1"), ev("shipped", 1, "o2"), ev("shipped", 2, "o1")]
    (result,) = check(compile_spec(spec), events).results
    assert [v.entity for v in result.violations] == ["o2"]


# ---- coverage: was the rule exercised at all? --------------------------------------------


def test_rule_with_none_of_its_events_is_not_tested():
    from .helpers import nav

    compiled = compile_spec(Spec(rules=[nav()]))  # shipped never after cancelled
    report = check(compiled, [ev("order_created", 0), ev("charged", 1)])
    (r,) = report.results
    assert r.status == "pass" and r.checked_events == 0 and not r.tested
    assert "[NOT TESTED]" in format_text(report)


def test_checked_events_counts_only_pattern_events():
    from .helpers import amo

    rule = amo(**{"except": [{"reset_after": "refunded"}]})
    report = check(compile_spec(Spec(rules=[rule])), [ev("refunded", 0), ev("charged", 1)])
    (r,) = report.results
    # "refunded" is only the reset event; one "charged" is what the rule is about.
    assert r.checked_events == 1 and r.tested
    assert "[PASS]" in format_text(report)


def test_checked_events_use_translated_names(shop_dir):
    r = next(x for x in run_shop(shop_dir).results if x.rule_id == "no-double-charge")
    assert r.checked_events > 0 and r.tested


def test_violation_is_always_tested():
    from .helpers import amo

    report = check(compile_spec(Spec(rules=[amo()])), [ev("charged", 0), ev("charged", 1)])
    (r,) = report.results
    assert r.status == "violation" and r.checked_events == 2 and r.tested
