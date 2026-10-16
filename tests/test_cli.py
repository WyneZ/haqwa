"""CLI behavior without network or Gemini calls."""

import json
from datetime import timedelta
from pathlib import Path

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
                    timeline=[
                        TimelineEvent(event="charged", at=timedelta(0)),
                        TimelineEvent(
                            event="charged",
                            data={"payment_type": "installment"},
                            at=timedelta(hours=65),
                        ),
                    ],
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
    assert "payment_type" in result.output and "installment" in result.output
    assert "at +65 hours from the first event" in result.output


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


def test_inspect_json_map_and_bad_input(shop_dir, tmp_path):
    path = shop_dir / "events.json"
    result = runner.invoke(app, ["inspect", str(path), "--json"])
    assert result.exit_code == 0, result.output
    summary = json.loads(result.output)
    assert summary["event_count"] > 0
    assert "events" in summary["vocabulary"]
    mapped = runner.invoke(
        app, ["inspect", str(path), "--map", str(shop_dir / "events.map.yaml"), "--json"]
    )
    assert mapped.exit_code == 0, mapped.output
    assert set(json.loads(mapped.output)["event_counts"]) <= {
        "charged",
        "refunded",
        "order_created",
    }
    assert runner.invoke(app, ["inspect", str(tmp_path / "missing.json")]).exit_code == 3


def test_build_trace_vocabulary_and_field_conflict(tmp_path, monkeypatch):
    from haqwa.ai import ClarifyOutcome

    seen = []

    def fake_clarify(text, *, rule_id, vocab, client):
        seen.append(vocab.model_dump())
        return ClarifyOutcome(source=text, status="unsupported", reason="test", questions=[])

    monkeypatch.setattr("haqwa.ai.clarify", fake_clarify)
    rules = tmp_path / "rules.txt"
    rules.write_text("A rule\n")
    events = tmp_path / "events.json"
    events.write_text(
        json.dumps(
            [
                {
                    "event": "paid",
                    "ts": "2026-01-01T00:00:00Z",
                    "data": {"employee_id": "E1", "state": "done"},
                }
            ]
        )
    )
    result = runner.invoke(app, ["build", str(rules), "--trace", str(events)])
    assert result.exit_code == 2  # fake clarify marks the only rule unsupported
    assert seen == [
        {
            "events": ["paid"],
            "fields": ["employee_id", "state"],
            "field_values": {"state": ["done"]},
            "numeric_fields": [],
        }
        
    ]
    conflict = runner.invoke(app, ["build", str(rules), "--trace", str(events), "--field", "state"])
    assert conflict.exit_code == 3


def test_build_trace_accepts_event_declared_only_in_map(tmp_path, monkeypatch):
    from haqwa.ai import ClarifyOutcome
    from haqwa.core.spec import AtMostOnce

    def fake_clarify(text, *, rule_id, vocab, client):
        assert "payroll_run" in vocab.events
        assert vocab.event_problem("payroll_run", "rule") is None
        return ClarifyOutcome(
            source=text,
            status="supported",
            rule=AtMostOnce(
                id=rule_id,
                source=text,
                pattern="at_most_once",
                event="payroll_run",
                per="employee_period",
            ),
            questions=[],
        )

    monkeypatch.setattr("haqwa.ai.clarify", fake_clarify)
    rules = tmp_path / "rules.txt"
    rules.write_text("Run payroll once per employee and period.\n")
    output = tmp_path / "rules.spec.yaml"
    hr = Path(__file__).resolve().parents[1] / "examples" / "hr"
    result = runner.invoke(
        app,
        [
            "build",
            str(rules),
            "--trace",
            str(hr / "events.json"),
            "--map",
            str(hr / "events.map.yaml"),
            "-o",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "event: payroll_run" in output.read_text()


def test_build_trace_map_uses_only_rule_names(shop_dir, tmp_path, monkeypatch):
    from haqwa.ai import ClarifyOutcome

    seen = []

    def fake_clarify(text, *, rule_id, vocab, client):
        seen.append(vocab.events)
        return ClarifyOutcome(source=text, status="unsupported", reason="test", questions=[])

    monkeypatch.setattr("haqwa.ai.clarify", fake_clarify)
    rules = tmp_path / "rules.txt"
    rules.write_text("A rule\n")
    result = runner.invoke(
        app,
        [
            "build",
            str(rules),
            "--trace",
            str(shop_dir / "events.json"),
            "--map",
            str(shop_dir / "events.map.yaml"),
        ],
    )
    assert result.exit_code == 2  # fake clarify marks the only rule unsupported
    assert seen == [["cancelled", "charged", "order_created", "refunded", "shipped"]]
    assert "PAYMENT_CAPTURED" not in seen[0]
    assert "EMAIL_SENT" not in seen[0]
