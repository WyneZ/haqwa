"""FastAPI application, error mapping, health check and optional SPA assets."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

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

from .config import get_settings
from .routes import router
from .schemas import HealthResponse

logger = logging.getLogger(__name__)
DIST_DIR = Path(__file__).resolve().parents[1] / "frontend" / "dist"


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
    api = FastAPI(title="Haqwa API", version="1.0.0")
    api.state.settings = settings
    api.state.gemini_client = GeminiClient(cache_dir=settings.cache_dir)

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

    @api.get("/healthz", response_model=HealthResponse)
    def healthz() -> HealthResponse:
        """Cloud Run health check."""
        return HealthResponse(ok=True)

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
