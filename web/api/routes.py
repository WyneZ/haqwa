"""Thin C3 HTTP routes over the Haqwa library."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError

from haqwa.ai import GeminiBadOutput, GeminiClient, ParseError
from haqwa.ai.answers_v2 import apply_answers_v2, build_questions
from haqwa.ai.clarify_v2 import propose_decisions
from haqwa.ai.core_v2_ports import CoreV2Ports
from haqwa.ai.explain import explain_violation
from haqwa.ai.parse_v2 import parse_v2
from haqwa.ai.vocab import Vocabulary
from haqwa.core.checker import check
from haqwa.core.compiler import compile_spec
from haqwa.core.errors import INVALID_REQUEST, INVALID_SPEC, HaqwaError
from haqwa.core.events import parse_event_map, parse_events
from haqwa.core.spec import dump_spec, parse_spec, suggest_rule_id
from haqwa.core.trace import summarize_trace
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
    TraceRequest,
    TraceResponse,
    VocabularyIn,
)

router = APIRouter(prefix="/api/v1")


def get_client(request: Request) -> GeminiClient:
    """Return the app's shared Gemini client; overridden in isolated API tests."""
    return request.app.state.gemini_client


def get_settings(request: Request) -> Settings:
    """Return the app's settings."""
    return request.app.state.settings


def get_core_v2_ports(request: Request) -> CoreV2Ports:
    """Return injected Track B operations, provisional until their implementation lands."""
    return request.app.state.core_v2_ports


def _vocabulary(value: VocabularyIn | None, settings: Settings) -> Vocabulary:
    if value is None:
        return settings.vocab
    try:
        return Vocabulary(**value.model_dump())
    except (ValueError, ValidationError) as exc:
        first_error = exc.errors()[0]["msg"] if isinstance(exc, ValidationError) else str(exc)
        raise HaqwaError(INVALID_REQUEST, f"Invalid vocabulary: {first_error}") from exc


@router.post("/clarify", response_model=ClarifyResponse)
def clarify_rules(
    request: ClarifyRequest,
    client: Annotated[GeminiClient, Depends(get_client)],
    settings: Annotated[Settings, Depends(get_settings)],
    ports: Annotated[CoreV2Ports, Depends(get_core_v2_ports)],
) -> ClarifyResponse:
    """Clarify up to ten policies, continuing past an unsupported individual rule."""
    results: list[ClarifyResult] = []
    ids: set[str] = set()
    cached = True
    vocab = _vocabulary(request.vocabulary, settings)
    for source in request.rules:
        rule_id = suggest_rule_id(source, ids)
        ids.add(rule_id)
        try:
            parsed = parse_v2(source, rule_id=rule_id, vocab=vocab, client=client)
            cached &= parsed.cached
            if parsed.status == "unsupported":
                results.append(
                    ClarifyResult(source=source, status="unsupported", reason=parsed.reason)
                )
                continue
            assert parsed.rule is not None
            outcome = propose_decisions(
                parsed.rule, vocab=vocab, client=client, make_example=ports.make_example
            )
            questions = build_questions(outcome, ports.canonical_examples(parsed.rule))
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
                status="supported",
                rule=outcome.rule,
                meaning=outcome.meaning,
                questions=questions,
            )
        )
    return ClarifyResponse(cached=cached, results=results)


@router.post("/answers", response_model=AnswersResponse)
def answers(
    request: AnswersRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    ports: Annotated[CoreV2Ports, Depends(get_core_v2_ports)],
) -> AnswersResponse:
    """Apply owner answers without contacting Gemini."""
    vocab = _vocabulary(request.vocabulary, settings)
    try:
        outcome = apply_answers_v2(
            request.rule, request.answers, vocab=vocab, apply_patch=ports.apply_patch
        )
    except ParseError as exc:
        raise HaqwaError(INVALID_SPEC, str(exc)[:240]) from exc
    return AnswersResponse.model_validate(outcome.model_dump())


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
    """Check uploaded events or run one deterministic demo scenario."""
    spec = parse_spec(request.spec)
    event_map = parse_event_map(request.event_map) if request.event_map is not None else None
    if request.events is not None:
        events = parse_events(request.events)
        summarize_trace(events)  # enforce the trace event limit
        report = check(compile_spec(spec, event_map), events, event_map)
    else:
        assert request.scenario_id is not None
        events, report = run_scenario(request.scenario_id, spec, event_map)
    return RunResponse(events=events, report=report)


@router.post("/traces", response_model=TraceResponse)
def traces(request: TraceRequest) -> TraceResponse:
    """Summarize an uploaded trace without storing it."""
    return TraceResponse(
        summary=summarize_trace(parse_events(request.events), extra_events=request.extra_events)
    )


@router.post("/explain", response_model=ExplainResponse)
def explain(
    request: ExplainRequest, client: Annotated[GeminiClient, Depends(get_client)]
) -> ExplainResponse:
    """Explain a checker violation without changing its verdict."""
    result = explain_violation(request.rule, request.violation, client=client)
    return ExplainResponse.model_validate(result.model_dump())
