"""The names Gemini is allowed to use: events, fields and closed field values.

The caller (web, CLI, demo) builds a `Vocabulary` for its own system, so the library
works for any domain, not only the shop demo. Gemini is never trusted to stay inside
it: `parse` and `clarify` check every name it returns against this list.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Vocabulary(BaseModel):
    """Allowed event names, event fields, and closed value sets for some fields.

    Fields missing from `field_values` (ids, amounts, times) take free values.
    """

    model_config = ConfigDict(frozen=True)

    events: list[str] = Field(min_length=1)
    fields: list[str] = Field(default_factory=list)
    field_values: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _values_belong_to_fields(self) -> Vocabulary:
        unknown = sorted(set(self.field_values) - set(self.fields))
        if unknown:
            raise ValueError(f"field_values for unknown fields: {unknown}")
        return self

    def event_problem(self, name: str | None, where: str) -> str | None:
        """A problem message if `name` is not an allowed event, else None."""
        if name in self.events:
            return None
        return f"{where}: event {name!r} is not in the vocabulary"

    def field_problem(self, name: str | None, where: str) -> str | None:
        """A problem message if `name` is not an allowed field, else None."""
        if name in self.fields:
            return None
        return f"{where}: field {name!r} is not in the vocabulary"

    def value_problem(self, field: str, value: str, where: str) -> str | None:
        """A problem message if `value` (comma-separated for `in`) is outside a closed set."""
        allowed = self.field_values.get(field)
        if allowed is None:
            return None
        bad = [v.strip() for v in value.split(",") if v.strip() not in allowed]
        if not bad:
            return None
        return f"{where}: value {bad} for field {field!r} is not in {allowed}"

    def values_text(self) -> str:
        """Closed value sets as prompt text, e.g. 'payment_type: card, installment'."""
        return "; ".join(f"{k}: {', '.join(v)}" for k, v in self.field_values.items())
