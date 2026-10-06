"""C3 transport models built from the existing library models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from haqwa.ai.clarify import Answer, Question
from haqwa.core.events import Event
from haqwa.core.report import Report, Violation
from haqwa.core.spec import Rule


class ClarifyRequest(BaseModel):
    rules: list[str] = Field(min_length=1, max_length=10)

    @field_validator("rules")
    @classmethod
    def non_empty_rules(cls, rules: list[str]) -> list[str]:
        if any(not rule.strip() for rule in rules):
            raise ValueError("rules must contain non-empty text")
        return rules


class ClarifyResult(BaseModel):
    source: str
    status: str
    rule: Rule | None = None
    questions: list[Question] | None = None
    reason: str | None = None


class ClarifyResponse(BaseModel):
    cached: bool
    results: list[ClarifyResult]


class AnswersRequest(BaseModel):
    rule: Rule
    answers: list[Answer]


class AnswersResponse(BaseModel):
    rule: Rule
    mismatches: list[str]


class SealRequest(BaseModel):
    spec: Any
    event_map: Any | None = None


class SealResponse(BaseModel):
    ok: bool
    spec_yaml: str


class ScenarioResponse(BaseModel):
    id: str
    title: str
    agent: str
    fault: str
    description: str
    expected: str


class RunRequest(BaseModel):
    spec: Any
    scenario_id: str
    event_map: Any | None = None


class RunResponse(BaseModel):
    events: list[Event]
    report: Report


class ExplainRequest(BaseModel):
    rule: Rule
    violation: Violation


class ExplainResponse(BaseModel):
    text: str
    advisory: bool
    cached: bool


class HealthResponse(BaseModel):
    ok: bool
