"""Gemini-backed meaning negotiation (Track A). `core/` never imports this package."""

from .client import (
    DEFAULT_MODEL,
    GeminiBadOutput,
    GeminiClient,
    GeminiError,
    GeminiQuotaError,
    GeminiResult,
    GeminiUnavailable,
)

__all__ = [
    "DEFAULT_MODEL",
    "GeminiBadOutput",
    "GeminiClient",
    "GeminiError",
    "GeminiQuotaError",
    "GeminiResult",
    "GeminiUnavailable",
]
