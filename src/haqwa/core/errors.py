"""Stable error codes shared by the CLI and the web API (C3, AGREED 2026-09-28).

Web: `to_problem(err)` gives an RFC 9457 Problem Details body plus a machine `code`.
CLI: `err.exit_code` is the process exit code.
Track A adds its own codes (e.g. `gemini_quota`, `unsupported_rule`) by request to Track B.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PROBLEM_TYPE_BASE = "https://haqwa.dev/errors/"  # placeholder URI, see docs/contracts.md


@dataclass(frozen=True)
class ErrorCode:
    code: str
    title: str
    status: int  # HTTP status for the web API
    exit_code: int  # process exit code for the CLI


# Exit codes: 0 pass, 1 violation (not an error), 2 spec/compile, 3 bad input, 4 external service.
INVALID_SPEC = ErrorCode("invalid_spec", "The spec is not valid", 422, 2)
COMPILE_FAILED = ErrorCode("compile_failed", "The spec could not be compiled", 422, 2)
INVALID_EVENTS = ErrorCode("invalid_events", "The events are not valid", 422, 3)
INVALID_RECORDING = ErrorCode("invalid_recording", "The recording is not valid", 422, 3)
INVALID_EVENT_MAP = ErrorCode("invalid_event_map", "The event map is not valid", 422, 3)
UNKNOWN_SCENARIO = ErrorCode("unknown_scenario", "Unknown demo scenario", 404, 3)
PATTERN_NOT_IMPLEMENTED = ErrorCode("pattern_not_implemented", "Pattern not implemented", 422, 2)
UNKNOWN_EVENT = ErrorCode("unknown_event", "Unknown event", 422, 2)
INVALID_REQUEST = ErrorCode("invalid_request", "Invalid request", 422, 3)
GEMINI_QUOTA = ErrorCode("gemini_quota", "Gemini quota exceeded", 429, 4)
GEMINI_UNAVAILABLE = ErrorCode("gemini_unavailable", "Gemini unavailable", 503, 4)
INTERNAL_ERROR = ErrorCode("internal_error", "Internal server error", 500, 3)

CODES: dict[str, ErrorCode] = {
    c.code: c
    for c in (
        INVALID_SPEC,
        COMPILE_FAILED,
        INVALID_EVENTS,
        INVALID_RECORDING,
        INVALID_EVENT_MAP,
        UNKNOWN_SCENARIO,
        PATTERN_NOT_IMPLEMENTED,
        UNKNOWN_EVENT,
        INVALID_REQUEST,
        GEMINI_QUOTA,
        GEMINI_UNAVAILABLE,
        INTERNAL_ERROR,
    )
}


class HaqwaError(Exception):
    """An error with a stable machine code. `extra` holds code-specific JSON fields."""

    def __init__(self, error: ErrorCode, detail: str, **extra: Any) -> None:
        self.error = error
        self.detail = detail
        self.extra = extra
        super().__init__(detail)

    @property
    def code(self) -> str:
        return self.error.code

    @property
    def title(self) -> str:
        return self.error.title

    @property
    def status(self) -> int:
        return self.error.status

    @property
    def exit_code(self) -> int:
        return self.error.exit_code


def to_problem(err: HaqwaError) -> dict[str, Any]:
    """RFC 9457 Problem Details (`application/problem+json`) plus `code` and extras."""
    return {
        "type": PROBLEM_TYPE_BASE + err.code.replace("_", "-"),
        "title": err.error.title,
        "status": err.status,
        "detail": err.detail,
        "code": err.code,
        **err.extra,
    }


def validation_errors(exc: Exception) -> list[dict[str, Any]]:
    """Short JSON-ready list from a Pydantic ValidationError (or one generic entry)."""
    errors = getattr(exc, "errors", None)
    if callable(errors):
        return [
            {"loc": [str(p) for p in e.get("loc", ())], "msg": e.get("msg", "")}
            for e in errors(include_url=False)
        ]
    return [{"loc": [], "msg": str(exc)}]
