"""Haqwa: turn business policies into executable controls for AI-powered workflows."""

from .core.canonical import CanonicalExample, canonical_examples
from .core.checker import check
from .core.compiler import CompiledSpec, CompileError, compile_spec, violates
from .core.events import Event, EventMap, load_event_map, load_events
from .core.report import Report, format_text
from .core.spec import Spec, load_spec, suggest_rule_id

__all__ = [
    "CanonicalExample",
    "canonical_examples",
    "suggest_rule_id",
    "violates",
    "CompileError",
    "CompiledSpec",
    "Event",
    "EventMap",
    "Report",
    "Spec",
    "check",
    "compile_spec",
    "format_text",
    "load_event_map",
    "load_events",
    "load_spec",
]
