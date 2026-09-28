"""Pattern evaluators. Each takes (rule, one entity's time-sorted events) -> findings."""

from __future__ import annotations

from . import at_most_once
from .base import Evaluator, Finding

# Pattern name -> evaluator. Patterns missing here fail at compile time.
REGISTRY: dict[str, Evaluator] = {
    "at_most_once": at_most_once.evaluate,
}

__all__ = ["REGISTRY", "Evaluator", "Finding"]
