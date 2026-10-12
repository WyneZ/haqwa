"""HTTP entry points for sessions driven by an external MCP agent."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from haqwa.adapters.agentproof import effects_to_events
from haqwa.core.checker import check
from haqwa.core.compiler import compile_spec
from haqwa.core.events import parse_event_map
from haqwa.core.spec import parse_spec
from haqwa.live.agent import TASKS
from haqwa.live.server import Fault

from .rate_limit import client_ip
from .schemas import RunResponse

router = APIRouter(prefix="/api/v1/agent-sessions")


class CreateSessionRequest(BaseModel):
    fault: Fault


class CreateSessionResponse(BaseModel):
    session_id: str
    fault: Fault
    mcp_url: str
    task: str
    expires_at: datetime


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


class CheckSessionRequest(BaseModel):
    spec: Any
    event_map: Any | None = None


def _store(request: Request):
    return request.app.state.agent_sessions


@router.post("", response_model=CreateSessionResponse)
async def create_session(body: CreateSessionRequest, request: Request) -> CreateSessionResponse:
    """Create a private shop and return its MCP URL and task."""
    request.app.state.agent_create_limiter.check(client_ip(request))
    session = _store(request).create(body.fault)
    base = request.base_url
    if request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip() == "https":
        base = base.replace(scheme="https")
    mount = "timeout" if body.fault == "timeout_after_commit" else "stale"
    return CreateSessionResponse(
        session_id=session.session_id,
        fault=session.fault,
        mcp_url=f"{str(base).rstrip('/')}/agent/{mount}/mcp?session={session.session_id}",
        task=TASKS[session.fault],
        expires_at=session.expires_at,
    )


@router.get("/{session_id}", response_model=SessionStatusResponse)
async def session_status(session_id: str, request: Request) -> SessionStatusResponse:
    """Return call history for one live session."""
    session = _store(request).get(session_id)
    return SessionStatusResponse(
        session_id=session.session_id,
        fault=session.fault,
        expires_at=session.expires_at,
        calls=[ToolCallResponse.model_validate(call) for call in session.shop.calls],
    )


@router.post("/{session_id}/check", response_model=RunResponse)
async def check_session(
    session_id: str, body: CheckSessionRequest, request: Request
) -> RunResponse:
    """Check a session's shop effects with the core checker."""
    session = _store(request).get(session_id)
    spec = parse_spec(body.spec)
    event_map = parse_event_map(body.event_map) if body.event_map is not None else None
    events = effects_to_events(session.shop.effects())
    report = check(compile_spec(spec, event_map), events, event_map)
    return RunResponse(events=events, report=report)


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: str, request: Request) -> Response:
    """Remove one session and its private shop."""
    _store(request).delete(session_id)
    return Response(status_code=204)
