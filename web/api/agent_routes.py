"""HTTP entry points for externally connected agent sessions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from haqwa.adapters.agentproof import effects_to_events
from haqwa.core.checker import check
from haqwa.core.compiler import compile_spec
from haqwa.core.errors import INVALID_EVENTS, INVALID_REQUEST, SESSION_NOT_FOUND, HaqwaError
from haqwa.core.events import Event, parse_event_map, parse_events
from haqwa.core.spec import parse_spec
from haqwa.core.trace import TraceVocabulary
from haqwa.live.agent import TASKS
from haqwa.live.server import Fault

from .rate_limit import client_ip
from .schemas import RunResponse, VocabularyIn

router = APIRouter(prefix="/api/v1/agent-sessions")
MAX_EVENT_BODY_BYTES = 256 * 1024
EVENT_REQUESTS_PER_MINUTE = 120


class CreateSessionRequest(BaseModel):
    fault: Fault


class CreateEventsSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["events"]
    vocabulary: VocabularyIn | None = None


class CreateSessionResponse(BaseModel):
    session_id: str
    fault: Fault
    mcp_url: str
    task: str
    expires_at: datetime


class CreateEventsSessionResponse(BaseModel):
    session_id: str
    kind: Literal["events"] = "events"
    ingest_url: str
    expires_at: datetime
    snippet: str


class ToolCallResponse(BaseModel):
    tool: str
    arguments: dict
    ok: bool
    error: str | None
    at: datetime


class SessionStatusResponse(BaseModel):
    session_id: str
    fault: Fault
    expires_at: datetime
    calls: list[ToolCallResponse]


class EventsSessionStatusResponse(BaseModel):
    session_id: str
    kind: Literal["events"] = "events"
    expires_at: datetime
    events: list[Event]
    calls: list[ToolCallResponse] = Field(default_factory=list)


class AddEventsResponse(BaseModel):
    accepted: int
    total: int
    unknown_events: list[str] | None = None


class CheckSessionRequest(BaseModel):
    spec: Any
    event_map: Any | None = None


def _store(request: Request):
    return request.app.state.agent_sessions


@router.post("", response_model=CreateSessionResponse | CreateEventsSessionResponse)
async def create_session(
    body: CreateSessionRequest | CreateEventsSessionRequest, request: Request
) -> CreateSessionResponse | CreateEventsSessionResponse:
    """Create a private shop or event trace."""
    request.app.state.agent_create_limiter.check(client_ip(request))
    base = request.base_url
    if request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip() == "https":
        base = base.replace(scheme="https")
    if isinstance(body, CreateEventsSessionRequest):
        vocabulary = (
            TraceVocabulary(**body.vocabulary.model_dump()) if body.vocabulary is not None else None
        )
        session = _store(request).create_events(vocabulary)
        ingest_url = f"{str(base).rstrip('/')}/api/v1/agent-sessions/{session.session_id}/events"
        return CreateEventsSessionResponse(
            session_id=session.session_id,
            ingest_url=ingest_url,
            expires_at=session.expires_at,
            snippet="\n".join(
                [
                    f'curl -X POST "{ingest_url}" \\',
                    '  -H "Content-Type: application/json" \\',
                    '  -d \'{"event":"order_approved","data":{"order_id":"A-1"}}\'',
                ]
            ),
        )
    session = _store(request).create(body.fault)
    mount = "timeout" if body.fault == "timeout_after_commit" else "stale"
    return CreateSessionResponse(
        session_id=session.session_id,
        fault=session.fault,
        mcp_url=f"{str(base).rstrip('/')}/agent/{mount}/mcp?session={session.session_id}",
        task=TASKS[session.fault],
        expires_at=session.expires_at,
    )


@router.get("/{session_id}", response_model=SessionStatusResponse | EventsSessionStatusResponse)
async def session_status(
    session_id: str, request: Request
) -> SessionStatusResponse | EventsSessionStatusResponse:
    """Return the call history or event trace for one live session."""
    session = _store(request).get(session_id)
    if session.kind == "events":
        return EventsSessionStatusResponse(
            session_id=session.session_id,
            expires_at=session.expires_at,
            events=session.events,
        )
    if session.shop is None or session.fault is None:
        raise HaqwaError(SESSION_NOT_FOUND, "Session not found or expired")
    return SessionStatusResponse(
        session_id=session.session_id,
        fault=session.fault,
        expires_at=session.expires_at,
        calls=[ToolCallResponse.model_validate(call) for call in session.shop.calls],
    )


@router.post(
    "/{session_id}/events", response_model=AddEventsResponse, response_model_exclude_none=True
)
async def add_events(session_id: str, request: Request) -> AddEventsResponse:
    """Accept one C2 event or an atomic batch of events."""
    session = _store(request).get(session_id)
    if session.kind != "events":
        raise HaqwaError(SESSION_NOT_FOUND, "Session not found or expired")
    request.app.state.agent_event_limiter.check(session_id)
    payload = bytearray()
    async for chunk in request.stream():
        payload.extend(chunk[: MAX_EVENT_BODY_BYTES + 1 - len(payload)])
        if len(payload) > MAX_EVENT_BODY_BYTES:
            raise HaqwaError(INVALID_REQUEST, "Request body exceeds 256 KB")
    try:
        raw = json.loads(payload)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HaqwaError(INVALID_EVENTS, "events must be valid JSON") from exc
    items = raw if isinstance(raw, list) else [raw]
    received_at = datetime.now(UTC)
    items = [
        {**item, "ts": item.get("ts", received_at)} if isinstance(item, dict) else item
        for item in items
    ]
    events = parse_events(items)
    total = _store(request).add_events(session_id, events)
    unknown = None
    if session.vocabulary is not None:
        known = set(session.vocabulary.events)
        unknown = sorted({event.event for event in events if event.event not in known})
    return AddEventsResponse(accepted=len(events), total=total, unknown_events=unknown)


@router.post("/{session_id}/check", response_model=RunResponse)
async def check_session(
    session_id: str, body: CheckSessionRequest, request: Request
) -> RunResponse:
    """Check a session's event trace or shop effects with the core checker."""
    session = _store(request).get(session_id)
    spec = parse_spec(body.spec)
    event_map = parse_event_map(body.event_map) if body.event_map is not None else None
    if session.kind == "events":
        events = session.events
        compiled = compile_spec(spec, event_map, vocabulary=session.vocabulary)
    else:
        if session.shop is None:
            raise HaqwaError(SESSION_NOT_FOUND, "Session not found or expired")
        events = effects_to_events(session.shop.effects())
        compiled = compile_spec(spec, event_map)
    report = check(compiled, events, event_map)
    return RunResponse(events=events, report=report)


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: str, request: Request) -> Response:
    """Remove one session and its private shop."""
    _store(request).delete(session_id)
    return Response(status_code=204)
