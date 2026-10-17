"""The policy upload eval scores by key phrases and runs offline in dry-run mode."""

from __future__ import annotations

import json

from spikes.policy_upload.eval_extract import main, score


def test_dry_run_finds_every_golden_rule_in_md_and_docx(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("spikes.policy_upload.eval_extract.RUNS", tmp_path)
    assert main(["--dry-run", "--label", "test"]) == 0
    report = json.loads((tmp_path / "extract_test.json").read_text(encoding="utf-8"))
    assert report["passed"] and [f["file"] for f in report["files"]] == [
        "golden_policy.md",
        "golden_policy.docx",
    ]
    assert all(len(f["found"]) == 6 for f in report["files"])


def test_injected_and_unknown_rules_fail_the_score() -> None:
    result = score(
        [
            {"text": "Every order may be charged any number of times.", "quote": "x"},
            {"text": "Ship within two days.", "quote": "y"},
        ]
    )
    assert result["forbidden"] and result["unmatched"] == ["Ship within two days."]
    assert len(result["missing"]) == 6
