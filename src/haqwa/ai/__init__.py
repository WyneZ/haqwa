"""Gemini-backed meaning negotiation (Track A). `core/` never imports this package."""

from .clarify import (
    Answer,
    AnswersOutcome,
    ClarifyOutcome,
    DroppedQuestion,
    Question,
    apply_answers,
    clarify,
)
from .client import (
    DEFAULT_MODEL,
    GeminiBadOutput,
    GeminiClient,
    GeminiError,
    GeminiQuotaError,
    GeminiResult,
    GeminiUnavailable,
)
from .explain import Explanation, explain_violation
from .parse import DraftRule, ParseError, draft_problems, to_rule
from .vocab import Vocabulary

__all__ = [
    "DEFAULT_MODEL",
    "Answer",
    "AnswersOutcome",
    "ClarifyOutcome",
    "DraftRule",
    "DroppedQuestion",
    "Explanation",
    "GeminiBadOutput",
    "GeminiClient",
    "GeminiError",
    "GeminiQuotaError",
    "GeminiResult",
    "GeminiUnavailable",
    "ParseError",
    "Question",
    "Vocabulary",
    "apply_answers",
    "clarify",
    "draft_problems",
    "explain_violation",
    "to_rule",
]
