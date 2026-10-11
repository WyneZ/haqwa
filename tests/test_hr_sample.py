"""The HR sample exercises two violations, pass and not-tested verdicts."""

import json
from pathlib import Path

from typer.testing import CliRunner

from haqwa.cli import app

HR = Path(__file__).resolve().parents[1] / "examples" / "hr"


def test_hr_check_exact_verdicts():
    result = CliRunner().invoke(
        app, ["check", str(HR / "rules.spec.yaml"), str(HR / "events.json"), "--json"]
    )
    assert result.exit_code == 1, result.output
    results = {item["rule_id"]: item for item in json.loads(result.output)["results"]}
    assert {key: item["status"] for key, item in results.items()} == {
        "decide-leave-within-48-hours": "violation",
        "no-approval-after-cancellation": "violation",
        "approve-timesheet-before-pay": "pass",
        "one-payroll-run": "pass",
    }
    assert {key: [v["entity"] for v in item["violations"]] for key, item in results.items()} == {
        "decide-leave-within-48-hours": ["L-15"],
        "no-approval-after-cancellation": ["L-07"],
        "approve-timesheet-before-pay": [],
        "one-payroll-run": [],
    }
    assert results["one-payroll-run"]["checked_events"] == 0


def test_hr_inspect_event_count():
    result = CliRunner().invoke(app, ["inspect", str(HR / "events.json")])
    assert result.exit_code == 0, result.output
    assert "Events: 85" in result.output
    assert "Entity candidates: employee_id" in result.output
    events = json.loads((HR / "events.json").read_text())
    assert len({item["data"]["employee_id"] for item in events}) == 15
    assert {item["data"]["department"] for item in events} == {"operations", "finance", "support"}
    assert {item["data"]["decision"] for item in events if item["event"] == "leave_decided"} == {
        "approved",
        "rejected",
    }
    assert {item["data"]["leave_type"] for item in events if "leave_type" in item["data"]} == {
        "annual",
        "sick",
        "unpaid",
    }
    assert sum(item["event"] == "leave_cancelled" for item in events) == 3
