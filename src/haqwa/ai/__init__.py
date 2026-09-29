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
from .parse import DraftRule, ParseError, draft_problems, to_rule
from .vocab import Vocabulary

__all__ = [
    "DEFAULT_MODEL",
    "DraftRule",
    "GeminiBadOutput",
    "GeminiClient",
    "GeminiError",
    "GeminiQuotaError",
    "GeminiResult",
    "GeminiUnavailable",
    "ParseError",
    "Vocabulary",
    "draft_problems",
    "to_rule",
]
