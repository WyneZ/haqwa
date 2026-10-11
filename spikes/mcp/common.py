"""Read MCP results and check the server's AgentProof effect ledger."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from haqwa import check, compile_spec, load_spec
from haqwa.adapters.agentproof import effects_to_events

ROOT = Path(__file__).resolve().parents[2]
URL = "http://127.0.0.1:8765/mcp"


def value(result: Any) -> Any:
    """Decode one official MCP SDK call_tool result."""
    if result.isError:
        return {"error": "".join(getattr(c, "text", "") for c in result.content)}
    if result.structuredContent is not None:
        structured = result.structuredContent
        return structured.get("result", structured) if isinstance(structured, dict) else structured
    texts = [c.text for c in result.content if hasattr(c, "text")]
    return json.loads(texts[0]) if len(texts) == 1 else texts


def verdict(effect_data: list[dict]) -> tuple[list[Any], Any]:
    effects = [SimpleNamespace(**effect) for effect in effect_data]
    events = effects_to_events(effects)
    spec = compile_spec(load_spec(ROOT / "examples/shop/rules.spec.yaml"))
    return events, check(spec, events)
