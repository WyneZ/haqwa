"""Thin C3 HTTP routes over the Haqwa library."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from haqwa.ai import GeminiBadOutput, GeminiClient, ParseError, apply_answers, clarify
from haqwa.ai.explain import explain_violation
from haqwa.core.compiler import compile_spec
from haqwa.core.events import parse_event_map
from haqwa.core.spec import dump_spec, parse_spec, suggest_rule_id
from haqwa.demo import list_scenarios, run_scenario

from .config import Settings
from .schemas import (
    AnswersRequest,
    AnswersResponse,
    ClarifyRequest,
    ClarifyResponse,
    ClarifyResult,
    ExplainRequest,
    ExplainResponse,
    RunRequest,
    RunResponse,
    ScenarioResponse,
    SealRequest,
    SealResponse,
)

router = APIRouter(prefix="/api/v1")


def get_client(request: Request) -> GeminiClient:
    """Return the app's shared Gemini client; overridden in isolated API tests."""
    return request.app.state.gemini_client


def get_settings(request: Request) -> Settings:
    """Return the app's settings."""
    return request.app.state.settings


@router.post("/clarify", response_model=ClarifyResponse, response_model_exclude_none=True)
def clarify_rules(
    request: ClarifyRequest,
    client: Annotated[GeminiClient, Depends(get_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ClarifyResponse:
    """Clarify up to ten policies, continuing past an unsupported individual rule."""
    results: list[ClarifyResult] = []
    ids: set[str] = set()
    cached = True
    for source in request.rules:
        rule_id = suggest_rule_id(source, ids)
        ids.add(rule_id)
        try:
            outcome = clarify(source, rule_id=rule_id, vocab=settings.vocab, client=client)
        except (ParseError, GeminiBadOutput) as exc:
            results.append(
                ClarifyResult(source=source, status="unsupported", reason=str(exc)[:240])
            )
            cached = False
            continue
        cached &= outcome.cached
        results.append(
            ClarifyResult(
                source=source,
                status=outcome.status,
                rule=outcome.rule,
                questions=outcome.questions if outcome.status == "supported" else None,
                reason=outcome.reason,
            )
        )
    return ClarifyResponse(cached=cached, results=results)


@router.post("/answers", response_model=AnswersResponse)
def answers(request: AnswersRequest) -> AnswersResponse:
    """Apply owner answers without contacting Gemini."""
    outcome = apply_answers(request.rule, request.answers)
    return AnswersResponse(rule=outcome.rule, mismatches=outcome.mismatches)


@router.post("/seal", response_model=SealResponse)
def seal(request: SealRequest) -> SealResponse:
    """Validate and self-test a spec, then produce its deterministic YAML."""
    spec = parse_spec(request.spec)
    event_map = parse_event_map(request.event_map) if request.event_map is not None else None
    compile_spec(spec, event_map)
    return SealResponse(ok=True, spec_yaml=dump_spec(spec))


@router.get("/scenarios", response_model=list[ScenarioResponse])
def scenarios() -> list[dict[str, str]]:
    """List native and recorded demo scenarios."""
    return list_scenarios()


@router.post("/runs", response_model=RunResponse)
def runs(request: RunRequest) -> RunResponse:
    """Run one deterministic scenario and return its events and checker report."""
    spec = parse_spec(request.spec)
    event_map = parse_event_map(request.event_map) if request.event_map is not None else None
    events, report = run_scenario(request.scenario_id, spec, event_map)
    return RunResponse(events=events, report=report)


@router.post("/explain", response_model=ExplainResponse)
def explain(
    request: ExplainRequest, client: Annotated[GeminiClient, Depends(get_client)]
) -> ExplainResponse:
    """Explain a checker violation without changing its verdict."""
    result = explain_violation(request.rule, request.violation, client=client)
    return ExplainResponse.model_validate(result.model_dump())
