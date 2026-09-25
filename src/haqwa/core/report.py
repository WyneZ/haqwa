"""Check results: PASS, or VIOLATION with the entity's event timeline."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from .events import Event


class Violation(BaseModel):
    """One broken rule for one entity."""

    model_config = ConfigDict(frozen=True)

    rule_id: str
    entity: str  # value of data[rule.per], as text
    message: str
    timeline: list[Event]  # entity's events up to and including the offending one
    offending_index: int  # index of the offending event in `timeline`


class RuleResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule_id: str
    source: str
    status: Literal["pass", "violation"]
    violations: list[Violation] = []


class Report(BaseModel):
    model_config = ConfigDict(frozen=True)

    results: list[RuleResult]

    @property
    def passed(self) -> bool:
        return all(r.status == "pass" for r in self.results)


def format_text(report: Report) -> str:
    """Plain-text report for terminals and logs."""
    lines: list[str] = []
    for r in report.results:
        lines.append(f"[{'PASS' if r.status == 'pass' else 'VIOLATION'}] {r.rule_id}: {r.source}")
        for v in r.violations:
            lines.append(f"  entity {v.entity}: {v.message}")
            for i, e in enumerate(v.timeline):
                mark = ">>" if i == v.offending_index else "  "
                lines.append(f"    {mark} {e.ts.isoformat()}  {e.event}")
    lines.append("RESULT: " + ("PASS" if report.passed else "VIOLATION"))
    return "\n".join(lines)
