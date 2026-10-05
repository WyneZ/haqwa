"""Haqwa: turn business policies into executable controls for AI-powered workflows."""

from .core.canonical import CanonicalExample, canonical_examples
from .core.checker import check
from .core.compiler import CompiledSpec, CompileError, compile_spec, violates
from .core.errors import HaqwaError, to_problem
from .core.events import Event, EventMap, load_event_map, load_events, parse_event_map, parse_events
from .core.report import Report, format_text
from .core.spec import Spec, dump_spec, load_spec, parse_spec, save_spec, suggest_rule_id

__all__ = [
    "HaqwaError",
    "dump_spec",
    "parse_event_map",
    "parse_events",
    "parse_spec",
    "save_spec",
    "to_problem",
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
