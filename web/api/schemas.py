"""C3 transport models built from the existing library models."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from haqwa.ai.answers_v2 import AnswerV2, QuestionV2
from haqwa.core.events import Event
from haqwa.core.report import Report, Violation
from haqwa.core.rules_v2 import RuleV2
from haqwa.core.spec import ConfirmedExample
from haqwa.core.trace import TraceSummary

NAME = r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$"


class VocabularyIn(BaseModel):
    events: list[Annotated[str, StringConstraints(pattern=NAME)]] = Field(
        min_length=1, max_length=100
    )
    fields: list[Annotated[str, StringConstraints(pattern=NAME)]] = Field(
        default_factory=list, max_length=100
    )
    field_values: dict[
        str, Annotated[list[Annotated[str, StringConstraints(max_length=64)]], Field(max_length=50)]
    ] = Field(default_factory=dict, max_length=100)
    numeric_fields: list[Annotated[str, StringConstraints(pattern=NAME)]] = Field(
        default_factory=list, max_length=100
    )


class ClarifyRequest(BaseModel):
    rules: list[str] = Field(min_length=1, max_length=10)
    vocabulary: VocabularyIn | None = None

    @field_validator("rules")
    @classmethod
    def non_empty_rules(cls, rules: list[str]) -> list[str]:
        if any(not rule.strip() for rule in rules):
            raise ValueError("rules must contain non-empty text")
        return rules


class ClarifyResult(BaseModel):
    source: str
    status: Literal["supported", "unsupported"]
    rule: RuleV2 | None = None
    meaning: str | None = None
    questions: list[QuestionV2] | None = None
    reason: str | None = None


class ClarifyResponse(BaseModel):
    cached: bool
    results: list[ClarifyResult]


class AnswersRequest(BaseModel):
    rule: RuleV2
    answers: list[AnswerV2]
    vocabulary: VocabularyIn | None = None


class AnswersResponse(BaseModel):
    rule: RuleV2
    meaning: str
    confirmed_examples: list[ConfirmedExample]
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
    kind: str


class RunRequest(BaseModel):
    spec: Any
    scenario_id: str | None = None
    events: Any | None = None
    event_map: Any | None = None

    @model_validator(mode="after")
    def one_source(self) -> RunRequest:
        if (self.scenario_id is None) == (self.events is None):
            raise ValueError("provide exactly one of scenario_id or events")
        return self


class RunResponse(BaseModel):
    events: list[Event]
    report: Report


class TraceRequest(BaseModel):
    events: Any
    extra_events: list[str] = Field(default_factory=list)


class TraceResponse(BaseModel):
    summary: TraceSummary


class ExplainRequest(BaseModel):
    rule: RuleV2
    violation: Violation


class ExplainResponse(BaseModel):
    text: str
    advisory: bool
    cached: bool


class HealthResponse(BaseModel):
    ok: bool
