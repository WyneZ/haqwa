"""Persist AgentProof effect ledgers for offline, deterministic demo replay."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ..adapters.agentproof import effects_to_events
from ..core.events import Event

RECORDINGS_DIR = Path(__file__).with_name("recordings")


def save_effects(effects: Iterable[Any], path: str | Path) -> None:
    """Save committed effects without prompts, model output, credentials or network access."""
    records = [
        {
            "type": effect.type,
            "data": dict(effect.data),
            "committed_at": float(effect.committed_at),
            "id": effect.id,
        }
        for effect in effects
    ]
    Path(path).write_text(
        json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def load_effects(path: str | Path) -> list[Event]:
    """Load a saved list of effects and convert it to C2 events."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("recording must be a JSON array")
    for item in raw:
        if not isinstance(item, dict) or set(item) != {"type", "data", "committed_at", "id"}:
            raise ValueError("recording effect must have type, data, committed_at and id")
        if not isinstance(item["type"], str) or not isinstance(item["data"], dict):
            raise ValueError("recording effect has invalid type or data")
        if not isinstance(item["id"], str):
            raise ValueError("recording effect id must be a string")
        if not isinstance(item["committed_at"], int | float):
            raise ValueError("recording effect committed_at must be a number")
    effects = [type("RecordedEffect", (), item) for item in raw]
    return effects_to_events(effects)
