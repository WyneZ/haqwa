import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from haqwa.core.errors import HaqwaError, to_problem
from haqwa.demo.recording import load_effects, save_effects


def test_sample_recording_replays_without_network():
    path = Path(__file__).parents[2] / "src/haqwa/demo/recordings/sample_native.json"
    events = load_effects(path)
    assert [event.event for event in events] == ["order_created", "charged", "charged"]
    assert [event.source_id for event in events] == ["sample-1", "sample-2", "sample-3"]


def test_save_and_load_effects(tmp_path):
    effects = [SimpleNamespace(type="charged", data={"order_id": "A-1"}, committed_at=1, id="x")]
    path = tmp_path / "run.json"
    save_effects(effects, path)
    assert load_effects(path)[0].event == "charged"


def test_bad_recording_rejected(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"effects": []}', encoding="utf-8")
    with pytest.raises(HaqwaError) as exc:
        load_effects(path)
    assert exc.value.code == "invalid_recording"
    assert to_problem(exc.value)["status"] == 422


@pytest.mark.parametrize("contents", ["{broken", '[{"type": "charged"}]'])
def test_malformed_recording_is_stable_error(tmp_path, contents):
    path = tmp_path / "bad.json"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(HaqwaError) as exc:
        load_effects(path)
    assert exc.value.code == "invalid_recording"


def test_bad_recording_reaches_runner_as_haqwa_error(tmp_path, monkeypatch):
    from haqwa import load_spec
    from haqwa.demo import run_scenario, scenarios

    (tmp_path / "gemini_2026_10_05.json").write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(scenarios, "RECORDINGS_DIR", tmp_path)
    spec = load_spec(Path(__file__).parents[2] / "examples/shop/rules.spec.yaml")
    with pytest.raises(HaqwaError) as exc:
        run_scenario("recorded_gemini_2026_10_05", spec)
    assert to_problem(exc.value)["code"] == "invalid_recording"


def test_recorded_scenario_from_saved_file(tmp_path, monkeypatch):
    from haqwa import load_spec
    from haqwa.demo import list_scenarios, run_scenario, scenarios

    sample = Path(__file__).parents[2] / "src/haqwa/demo/recordings/sample_native.json"
    (tmp_path / "gemini_2026_10_05.json").write_bytes(sample.read_bytes())
    monkeypatch.setattr(scenarios, "RECORDINGS_DIR", tmp_path)
    listed = list_scenarios()
    recorded = next(s for s in listed if s["id"] == "recorded_gemini_2026_10_05")
    assert recorded["title"] == "Recorded Gemini agent run (2026-10-05)"
    assert recorded["expected"] == "unknown"
    spec = load_spec(Path(__file__).parents[2] / "examples/shop/rules.spec.yaml")
    listed_with_spec = list_scenarios(spec)
    assert next(s for s in listed_with_spec if s["id"] == recorded["id"])["expected"] == "violation"
    events, report = run_scenario(recorded["id"], spec)
    assert len(events) == 3
    assert not report.passed


def test_passing_recording_is_not_labeled_violation(tmp_path, monkeypatch):
    from haqwa import load_spec
    from haqwa.demo import list_scenarios, run_scenario, scenarios

    sample = Path(__file__).parents[2] / "src/haqwa/demo/recordings/sample_native.json"
    effects = json.loads(sample.read_text(encoding="utf-8"))[:2]
    (tmp_path / "gemini_2026_10_06.json").write_text(json.dumps(effects), encoding="utf-8")
    monkeypatch.setattr(scenarios, "RECORDINGS_DIR", tmp_path)
    spec = load_spec(Path(__file__).parents[2] / "examples/shop/rules.spec.yaml")
    recorded = next(s for s in list_scenarios(spec) if s["fault"] == "recorded")
    assert recorded["expected"] == "pass"
    assert run_scenario(recorded["id"], spec)[1].passed
