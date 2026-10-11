"""The browser sample is the same trace used by the Python examples."""

from pathlib import Path

from fastapi.testclient import TestClient

from web.api import main as api_main

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "examples/hr/events.json"
PUBLIC_SAMPLE = ROOT / "web/frontend/public/samples/hr-events.json"


def test_hr_sample_matches_example() -> None:
    assert PUBLIC_SAMPLE.read_bytes() == SAMPLE.read_bytes()


def test_sample_is_served_without_spa_fallback(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "index.html").write_text("frontend", encoding="utf-8")
    sample_path = tmp_path / "samples/hr-events.json"
    sample_path.parent.mkdir()
    sample_path.write_bytes(PUBLIC_SAMPLE.read_bytes())
    monkeypatch.setattr(api_main, "DIST_DIR", tmp_path)
    response = TestClient(api_main.create_app()).get("/samples/hr-events.json")
    assert response.status_code == 200
    assert response.content == SAMPLE.read_bytes()
