"""Persist AgentProof effect ledgers for offline, deterministic demo replay."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from ..adapters.agentproof import effects_to_events
from ..core.errors import INVALID_RECORDING, HaqwaError, validation_errors
from ..core.events import Event

RECORDINGS_DIR = Path(__file__).with_name("recordings")


class _RecordedEffect(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1)
    data: dict[str, Any]
    committed_at: float = Field(ge=0, allow_inf_nan=False)
    id: str = Field(min_length=1)


_EFFECTS = TypeAdapter(list[_RecordedEffect])


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
    """Load saved effects as C2 events, raising `invalid_recording` on bad input."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        effects = _EFFECTS.validate_python(raw)
        return effects_to_events(effects)
    except (OSError, json.JSONDecodeError, ValidationError, ValueError, OverflowError) as exc:
        extra = {"errors": validation_errors(exc)} if isinstance(exc, ValidationError) else {}
        raise HaqwaError(INVALID_RECORDING, str(exc), **extra) from exc
