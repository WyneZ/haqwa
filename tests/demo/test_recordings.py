from pathlib import Path
from types import SimpleNamespace

import pytest

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
    with pytest.raises(ValueError, match="JSON array"):
        load_effects(path)


def test_recorded_scenario_from_saved_file(tmp_path, monkeypatch):
    from haqwa import load_spec
    from haqwa.demo import list_scenarios, run_scenario, scenarios

    sample = Path(__file__).parents[2] / "src/haqwa/demo/recordings/sample_native.json"
    (tmp_path / "gemini_2026_10_05.json").write_bytes(sample.read_bytes())
    monkeypatch.setattr(scenarios, "RECORDINGS_DIR", tmp_path)
    listed = list_scenarios()
    recorded = next(s for s in listed if s["id"] == "recorded_gemini_2026_10_05")
    assert recorded["title"] == "Recorded Gemini agent run (2026-10-05)"
    spec = load_spec(Path(__file__).parents[2] / "examples/shop/rules.spec.yaml")
    events, report = run_scenario(recorded["id"], spec)
    assert len(events) == 3
    assert not report.passed
