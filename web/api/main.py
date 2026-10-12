"""FastAPI application, error mapping, health check and optional SPA assets."""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

from haqwa.ai.client import GeminiBadOutput, GeminiQuotaError, GeminiUnavailable
from haqwa.core.compiler import CompileError
from haqwa.core.errors import (
    GEMINI_QUOTA,
    GEMINI_UNAVAILABLE,
    INTERNAL_ERROR,
    INVALID_REQUEST,
    INVALID_SPEC,
    HaqwaError,
    to_problem,
)
from haqwa.live.server import Fault, ShopState, register_tools

from .agent_routes import router as agent_router
from .agent_sessions import AgentSessionStore
from .config import get_settings
from .rate_limit import RateLimiter, client_ip
from .routes import router
from .schemas import HealthResponse

logger = logging.getLogger(__name__)
DIST_DIR = Path(__file__).resolve().parents[1] / "frontend" / "dist"
MAX_TRACE_BODY_BYTES = 5_000_000


def _problem(error: HaqwaError, **extra: object) -> JSONResponse:
    return JSONResponse(
        {**to_problem(error), **extra},
        status_code=error.status,
        media_type="application/problem+json",
    )


def create_app() -> FastAPI:
    """Build the API with a shared lazy Gemini client and optional built frontend."""
    from haqwa.ai.client import GeminiClient

    settings = get_settings()
    sessions = AgentSessionStore(settings.agent_max_sessions, settings.agent_ttl_seconds)
    security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    timeout_mcp = FastMCP("Haqwa live shop", json_response=True, transport_security=security)
    stale_mcp = FastMCP("Haqwa live shop", json_response=True, transport_security=security)

    def resolver_for(fault: Fault) -> Callable[[Context], ShopState]:
        def resolve(ctx: Context) -> ShopState:
            try:
                token = ctx.request_context.request.query_params["session"]
                session = sessions.get(token)
            except (KeyError, HaqwaError) as exc:
                raise ToolError("Session not found or expired") from exc
            if session.fault != fault:
                raise ToolError("Session not found or expired")
            if session.calls_started >= settings.agent_max_calls:
                raise ToolError("Too many requests")
            session.calls_started += 1
            return session.shop

        return resolve

    register_tools(timeout_mcp, "timeout_after_commit", resolver_for("timeout_after_commit"))
    register_tools(stale_mcp, "stale_state", resolver_for("stale_state"))

    @asynccontextmanager
    async def lifespan(_api: FastAPI):
        async with timeout_mcp.session_manager.run(), stale_mcp.session_manager.run():
            yield

    api = FastAPI(title="Haqwa API", version="1.0.0", lifespan=lifespan)
    api.state.settings = settings
    api.state.gemini_client = GeminiClient(cache_dir=settings.cache_dir)
    api.state.rate_limiter = RateLimiter(settings.rate_per_min, settings.rate_per_day)
    api.state.agent_create_limiter = RateLimiter(
        settings.agent_create_per_min, settings.agent_create_per_day
    )
    api.state.agent_sessions = sessions

    @api.middleware("http")
    async def limit_gemini_routes(request: Request, call_next):
        if request.method == "POST" and request.url.path in (
            "/api/v1/clarify",
            "/api/v1/explain",
        ):
            try:
                api.state.rate_limiter.check(client_ip(request))
            except HaqwaError as exc:
                return _problem(exc)
        return await call_next(request)

    @api.middleware("http")
    async def trace_body_limit(request: Request, call_next):
        if request.method == "POST" and request.url.path in {"/api/v1/traces", "/api/v1/runs"}:
            length = request.headers.get("content-length")
            if length is not None:
                try:
                    too_large = int(length) > MAX_TRACE_BODY_BYTES
                except ValueError:
                    too_large = False
                if too_large:
                    return _problem(HaqwaError(INVALID_REQUEST, "Request body exceeds 5 MB"))
            if len(await request.body()) > MAX_TRACE_BODY_BYTES:
                return _problem(HaqwaError(INVALID_REQUEST, "Request body exceeds 5 MB"))
        return await call_next(request)

    if settings.dev_cors:
        api.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @api.exception_handler(HaqwaError)
    async def haqwa_error(_request: Request, exc: HaqwaError) -> JSONResponse:
        return _problem(exc, ok=False) if isinstance(exc, CompileError) else _problem(exc)

    @api.exception_handler(RequestValidationError)
    async def request_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        loc = exc.errors()[0].get("loc", ())
        code = INVALID_SPEC if "rule" in loc else INVALID_REQUEST
        errors = [
            {"loc": [str(part) for part in item.get("loc", ())], "msg": item.get("msg", "")}
            for item in exc.errors()
        ]
        return _problem(HaqwaError(code, "Request body validation failed", errors=errors))

    @api.exception_handler(GeminiQuotaError)
    async def quota_error(_request: Request, exc: GeminiQuotaError) -> JSONResponse:
        return _problem(HaqwaError(GEMINI_QUOTA, str(exc)))

    @api.exception_handler(GeminiUnavailable)
    async def unavailable_error(_request: Request, exc: GeminiUnavailable) -> JSONResponse:
        return _problem(HaqwaError(GEMINI_UNAVAILABLE, str(exc)))

    @api.exception_handler(GeminiBadOutput)
    async def bad_output_error(_request: Request, exc: GeminiBadOutput) -> JSONResponse:
        logger.warning("Gemini returned invalid output: %s", exc)
        return _problem(HaqwaError(GEMINI_UNAVAILABLE, "Gemini returned unusable output"))

    @api.exception_handler(Exception)
    async def internal_error(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unexpected API error", exc_info=exc)
        return _problem(HaqwaError(INTERNAL_ERROR, "An unexpected error occurred"))

    api.include_router(router)
    api.include_router(agent_router)

    @api.get("/healthz", response_model=HealthResponse)
    def healthz() -> HealthResponse:
        """Cloud Run health check."""
        return HealthResponse(ok=True)

    api.mount("/agent/timeout", timeout_mcp.streamable_http_app())
    api.mount("/agent/stale", stale_mcp.streamable_http_app())

    if (DIST_DIR / "index.html").is_file():

        @api.get("/{path:path}", include_in_schema=False)
        def frontend(path: str) -> FileResponse:
            """Serve built assets and use index.html for SPA navigation."""
            if path == "api" or path.startswith("api/"):
                raise HTTPException(status_code=404)
            candidate = (DIST_DIR / path).resolve()
            if candidate.is_file() and candidate.is_relative_to(DIST_DIR.resolve()):
                return FileResponse(candidate)
            return FileResponse(DIST_DIR / "index.html")

    return api


app = create_app()
