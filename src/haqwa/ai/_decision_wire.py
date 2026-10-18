"""Patch models (owner-answer edits) and the Gemini schema for choosing candidates."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, create_model, model_validator

from haqwa.core.rules_v2 import (
    CountNode,
    EveryFollowedWithinNode,
    EveryPrecededByNode,
    NoneAfterNode,
)

RESETTABLE = (CountNode, NoneAfterNode, EveryPrecededByNode, EveryFollowedWithinNode)


class _Wire(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def _reject_extra_fields(cls, value: Any) -> Any:
        # Enforce locally without emitting the provider-incompatible additionalProperties.
        if isinstance(value, dict) and (extra := set(value) - cls.model_fields.keys()):
            raise ValueError(f"unexpected fields: {sorted(extra)}")
        return value


class ScalarCondition(_Wire):
    field: str = Field(description="field with a closed list of allowed values")
    op: Literal["eq", "ne"]
    value: str = Field(description="one exact member of the field's closed value list")


class MembershipCondition(_Wire):
    field: str = Field(description="field with a closed list of allowed values")
    op: Literal["in"]
    values: list[str] = Field(min_length=1, description="members of the closed value list")


class AddReset(_Wire):
    op: Literal["add_reset"]
    node_id: str = Field(description="id of a checking node that accepts resets")
    event: str = Field(description="event that clears the checking node's state")


class AddExclude(_Wire):
    op: Literal["add_exclude"]
    select_ids: list[str] = Field(
        min_length=1, description="select ids to exempt; target every select of a check"
    )
    condition: ScalarCondition | MembershipCondition


Patch = AddReset | AddExclude


MAX_DECISIONS = 4


class WireChoice(_Wire):
    candidate: str = Field(description="id of one listed candidate change, e.g. 'p3'")
    question: str = Field(description="plain-English Yes/No; Yes applies it")
    why: str = Field(description="why the owner must decide this")


class WireChoices(_Wire):
    decisions: list[WireChoice] = Field(max_length=MAX_DECISIONS)


class DroppedDecision(BaseModel):
    """One rejected choice, retained as evidence rather than silently repaired."""

    gemini_id: str
    reasons: list[str]


def choice_schema(candidate_ids: tuple[str, ...]) -> type[WireChoices]:
    """Gemini may only name a listed candidate: ids are an enum built per rule."""
    choice = create_model(
        "WireChoice",
        __base__=WireChoice,
        candidate=(Literal[candidate_ids], Field(description="id of one listed candidate")),
    )
    return create_model(
        "ChoiceResponse",
        __base__=WireChoices,
        decisions=(
            list[choice],
            Field(max_length=MAX_DECISIONS, description="0 to 4 real owner decisions"),
        ),
    )
