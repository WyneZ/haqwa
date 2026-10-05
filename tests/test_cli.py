"""CLI behavior without network or Gemini calls."""

import json

from typer.testing import CliRunner

from haqwa.cli import app

runner = CliRunner()


def test_init_creates_files_and_refuses_overwrite(tmp_path):
    target = tmp_path / "new"
    result = runner.invoke(app, ["init", str(target)])
    assert result.exit_code == 0, result.output
    assert "charged: PAYMENT_CAPTURED" in (target / "events.map.yaml").read_text()
    assert "charged twice" in (target / "rules.haqwa").read_text()
    assert runner.invoke(app, ["init", str(target)]).exit_code == 3


def test_check_exit_codes_and_json(shop_dir, tmp_path):
    spec = shop_dir / "rules.spec.yaml"
    events = shop_dir / "events.json"
    mapping = shop_dir / "events.map.yaml"
    result = runner.invoke(app, ["check", str(spec), str(events), "--map", str(mapping), "--json"])
    assert result.exit_code in (0, 1), result.output
    report = json.loads(result.output)
    assert result.exit_code == (0 if all(r["status"] == "pass" for r in report["results"]) else 1)

    bad_spec = tmp_path / "bad.yaml"
    bad_spec.write_text("rules: [", encoding="utf-8")
    assert runner.invoke(app, ["check", str(bad_spec), str(events)]).exit_code == 2
    assert runner.invoke(app, ["check", str(spec), str(tmp_path / "missing.json")]).exit_code == 3


def test_check_pass_and_violation(shop_dir, tmp_path):
    spec = shop_dir / "rules.spec.yaml"
    mapping = shop_dir / "events.map.yaml"
    events = json.loads((shop_dir / "events.json").read_text())
    passing = tmp_path / "pass.json"
    violating = tmp_path / "violation.json"
    passing.write_text(json.dumps(events[:1]), encoding="utf-8")
    violating.write_text(
        json.dumps(
            [
                {
                    "event": "PAYMENT_CAPTURED",
                    "ts": "2026-01-01T00:00:00Z",
                    "data": {"order_id": "a"},
                },
                {
                    "event": "PAYMENT_CAPTURED",
                    "ts": "2026-01-01T00:00:01Z",
                    "data": {"order_id": "a"},
                },
            ]
        ),
        encoding="utf-8",
    )
    assert (
        runner.invoke(app, ["check", str(spec), str(passing), "--map", str(mapping)]).exit_code == 0
    )
    assert (
        runner.invoke(app, ["check", str(spec), str(violating), "--map", str(mapping)]).exit_code
        == 1
    )


def test_build_uses_fake_clarify(shop_dir, tmp_path, monkeypatch):
    from haqwa.ai import ClarifyOutcome, Question
    from haqwa.core.spec import AtMostOnce, TimelineEvent

    def fake_clarify(text, *, rule_id, vocab, client):
        assert "charged" in vocab.events
        assert "order_id" in vocab.fields
        return ClarifyOutcome(
            source=text,
            status="supported",
            rule=AtMostOnce(
                id=rule_id, source=text, pattern="at_most_once", event="charged", per="order_id"
            ),
            questions=[
                Question(
                    id="c1",
                    kind="confirmation",
                    text="Is this allowed?",
                    timeline=[TimelineEvent(event="charged"), TimelineEvent(event="charged")],
                    expected_violation=True,
                )
            ],
        )

    monkeypatch.setattr("haqwa.ai.clarify", fake_clarify)
    rules = tmp_path / "rules.haqwa"
    rules.write_text("A customer must not be charged twice for the same order.\n")
    output = tmp_path / "sealed.yaml"
    result = runner.invoke(
        app,
        ["build", str(rules), "--map", str(shop_dir / "events.map.yaml"), "-o", str(output)],
        input="n\n",
    )
    assert result.exit_code == 0, result.output
    assert "at_most_once" in output.read_text()
    assert "violation: true" in output.read_text()


def test_build_quota_exit_code(shop_dir, tmp_path, monkeypatch):
    from haqwa.ai import GeminiQuotaError

    def quota(*args, **kwargs):
        raise GeminiQuotaError("daily limit", per_day=True)

    monkeypatch.setattr("haqwa.ai.clarify", quota)
    rules = tmp_path / "rules.haqwa"
    rules.write_text("A customer must not be charged twice.\n")
    result = runner.invoke(app, ["build", str(rules), "--map", str(shop_dir / "events.map.yaml")])
    assert result.exit_code == 4
    assert "daily limit" in result.output
