"""Required patch wire models and rule-specific structured-output schemas."""

from __future__ import annotations

from typing import Any, Literal, Union, get_args

from pydantic import (
    BaseModel,
    Field,
    ModelWrapValidatorHandler,
    PrivateAttr,
    ValidationError,
    create_model,
    model_validator,
)

from haqwa.core.rules_v2 import (
    CountNode,
    EveryFollowedWithinNode,
    EveryPrecededByNode,
    NoneAfterNode,
    RuleV2,
    SelectNode,
)

from .vocab import Vocabulary

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


class WireDecision(_Wire):
    id: str = Field(min_length=1, description="short proposal identifier")
    question: str = Field(min_length=1, description="plain-English Yes/No; Yes adds the patch")
    why: str = Field(min_length=1, description="why this is a real business choice")
    patch: Patch


class DroppedDecision(BaseModel):
    """One rejected proposal, retained as evidence rather than silently repaired."""

    gemini_id: str
    reasons: list[str]


class WireDecisions(_Wire):
    decisions: list[WireDecision] = Field(max_length=3, description="0 to 3 real decisions")
    _dropped: list[DroppedDecision] = PrivateAttr(default_factory=list)

    @model_validator(mode="wrap")
    @classmethod
    def _retain_invalid_proposals(
        cls, value: Any, handler: ModelWrapValidatorHandler
    ) -> WireDecisions:
        # The schema still constrains every proposal. At the local trust boundary, a
        # bad member becomes evidence without hiding valid siblings. Raw cached JSON
        # passes through this same validator, so drop evidence survives cache hits.
        if not isinstance(value, dict) or not isinstance(value.get("decisions"), list):
            return handler(value)
        if len(value["decisions"]) > 3:
            return handler(value)
        item_model = get_args(cls.model_fields["decisions"].annotation)[0]
        valid, dropped = [], []
        for index, proposal in enumerate(value["decisions"]):
            try:
                valid.append(item_model.model_validate(proposal))
            except ValidationError as exc:
                identifier = (
                    proposal.get("id", f"proposal-{index + 1}")
                    if isinstance(proposal, dict)
                    else f"proposal-{index + 1}"
                )
                dropped.append(
                    DroppedDecision(
                        gemini_id=str(identifier),
                        reasons=[
                            f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()
                        ],
                    )
                )
        result = handler({**value, "decisions": valid})
        result._dropped = dropped
        return result


def decision_schema(rule: RuleV2, vocab: Vocabulary) -> type[WireDecisions]:
    """Build a nonrecursive anyOf schema with vocabulary and eligible target enums."""
    targets = tuple(n.id for n in rule.nodes if isinstance(n, RESETTABLE))
    selects = tuple(n.id for n in rule.nodes if isinstance(n, SelectNode))
    patches: list[Any] = []
    if targets:
        patches.append(
            create_model(
                "DecisionAddReset",
                __base__=AddReset,
                node_id=(Literal[targets], Field(description="resettable check id")),
                event=(Literal[tuple(vocab.events)], Field(description="reset event name")),
            )
        )
    if selects and vocab.fields:
        field = Literal[tuple(vocab.fields)]
        scalar = create_model(
            "DecisionScalarCondition",
            __base__=ScalarCondition,
            field=(field, Field(description="closed-value field name")),
        )
        membership = create_model(
            "DecisionMembershipCondition",
            __base__=MembershipCondition,
            field=(field, Field(description="closed-value field name")),
        )
        patches.append(
            create_model(
                "DecisionAddExclude",
                __base__=AddExclude,
                select_ids=(list[Literal[selects]], Field(min_length=1)),
                condition=(scalar | membership, Field(description="exemption condition")),
            )
        )
    if not patches:
        # A valid rule normally has selectors. An empty capability set must never
        # widen to arbitrary targets; an empty decisions list is its only response.
        return create_model(
            "DecisionResponse",
            __base__=WireDecisions,
            decisions=(list[WireDecision], Field(max_length=0)),
        )
    patch_type = patches[0] if len(patches) == 1 else Union[tuple(patches)]  # noqa: UP007
    decision = create_model(
        "WireDecision",
        __base__=WireDecision,
        patch=(patch_type, Field(description="typed change if the owner answers Yes")),
    )
    return create_model(
        "DecisionResponse",
        __base__=WireDecisions,
        decisions=(list[decision], Field(max_length=3, description="0 to 3 real decisions")),
    )
