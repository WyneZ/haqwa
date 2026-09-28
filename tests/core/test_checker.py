from haqwa import check, compile_spec, format_text, load_event_map, load_events, load_spec


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
    (result,) = report.results
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
