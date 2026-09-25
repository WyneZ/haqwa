"""Types shared by pattern evaluators."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..events import Event


@dataclass(frozen=True)
class Finding:
    """A violation inside one entity's event stream."""

    index: int  # position of the offending event in the stream
    message: str


Evaluator = Callable[[Any, list[Event]], list[Finding]]
