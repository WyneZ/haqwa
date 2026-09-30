"""Pattern evaluators. Each takes (rule, one entity's time-sorted events) -> findings."""

from __future__ import annotations

from . import at_most_once, must_precede, never_after, within_time
from .base import Evaluator, Finding

# Pattern name -> evaluator. Patterns missing here fail at compile time.
REGISTRY: dict[str, Evaluator] = {
    "at_most_once": at_most_once.evaluate,
    "never_after": never_after.evaluate,
    "must_precede": must_precede.evaluate,
    "within_time": within_time.evaluate,
}

__all__ = ["REGISTRY", "Evaluator", "Finding"]
