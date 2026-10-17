"""G2 scoring uses no Gemini calls; examples come from core make_example_v2."""

from __future__ import annotations

import json

import pytest

from haqwa.ai.clarify_v2 import AddExclude, Decision
from haqwa.ai.client import GeminiClient
from haqwa.ai.rule_wire import to_rule_v2
from spikes.clarify_v2.eval_g2 import main, score_decisions
from spikes.clarify_v2.golden_g2 import RULES, SHOP, expected_patches


def test_dry_run_finds_six_with_zero_noise(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("spikes.clarify_v2.eval_g2.RUNS", tmp_path)
    assert main(["--dry-run", "--fresh", "--label", "test"]) == 0
    report = json.loads((tmp_path / "g2_test.json").read_text(encoding="utf-8"))
    assert report["found"] == report["expected"] == 6
    assert report["noise"] == report["dropped"] == 0
    assert report["passed"]
    assert report["example_builder"].startswith("core make_example_v2")
    # Every found decision carries core's separating example, not a placeholder.
    for row in report["rules"]:
        for decision in row["decisions"]:
            assert decision["example"] and "PLACEHOLDER" not in decision["example"]["label"]
    assert len(report["rules"]) == 3


def test_partial_exclude_is_noise_and_duplicate_cannot_inflate_recall() -> None:
    text, wire = RULES["R3"]
    original = to_rule_v2(wire, rule_id="r3", source=text, vocab=SHOP)
    expected = expected_patches("R3", original)
    patch = expected["G3.6"]
    partial = AddExclude.model_validate({**patch.model_dump(), "select_ids": patch.select_ids[:1]})
    decisions = [
        Decision(id=str(i), question="Allow this?", why="Business choice", patch=p, example=None)
        for i, p in enumerate([patch, patch, partial])
    ]
    score = score_decisions("R3", original, decisions)
    assert score["found"] == ["G3.6"]
    assert len(score["noise"]) == 1


def test_invalid_report_label_is_rejected() -> None:
    with pytest.raises(SystemExit):
        main(["--dry-run", "--label", "../escape"])


@pytest.mark.parametrize("fresh", [False, True])
def test_fresh_bypasses_cache_independently_of_dry_run(monkeypatch, fresh) -> None:
    from spikes.clarify_v2.eval_g2 import _dry_answers, _DryRunSDK

    sdk = _DryRunSDK()
    sdk.answers = [answer for rule_id in RULES for answer in _dry_answers(rule_id)]
    options = []

    def client_factory(**kwargs):
        options.append(kwargs)
        return GeminiClient(**{**kwargs, "sdk": sdk, "cache_dir": None})

    monkeypatch.setattr("spikes.clarify_v2.eval_g2.GeminiClient", client_factory)
    assert main(["--fresh"] if fresh else []) == 0
    assert (options[0]["cache_dir"] is None) == fresh
