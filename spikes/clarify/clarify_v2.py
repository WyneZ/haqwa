"""Spike step 6: prompt v2 + per-pattern parse schema for the clarification loop.

Changes from v1 (see NOTES.md, 2026-09-26/27):
1. Parse is a union of per-pattern models whose field names follow C1
   (never_after: after + event, within_time: start + event + within, ...),
   so no rule loses its second event or its time window.
2. The union is a plain `anyOf`, not a discriminated `oneOf`: google-genai
   2.25.0 rejects the `discriminator` keyword client-side (contracts open Q5).
   core/spec.py still validates the converted spec with its discriminated union.
3. Gemini is asked for decision questions only. Confirmation questions
   (core case, event order, per-entity) come from the core canonical-examples
   template (decisions.md, 2026-09-27), so the prompt tells Gemini to skip them.
4. A per-pattern checklist in the prompt (e.g. within_time: clock type).

Run (all rules):      uv run python spikes/clarify/clarify_v2.py
Run (some rules):     uv run python spikes/clarify/clarify_v2.py R2 R3
Offline schema check: uv run python spikes/clarify/clarify_v2.py --check-schema
Outputs: spikes/clarify/runs/v2_<model>_<rule_id>.json
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Literal, Union

import httpx
from pydantic import BaseModel, Field

logging.getLogger("google_genai.models").setLevel(logging.ERROR)

EVENT_VOCAB = [
    "order_created", "charged", "charge_failed", "refunded",
    "cancelled", "shipped", "refund_requested", "refund_completed",
]
FIELDS = ["order_id", "customer_id", "payment_type", "amount", "time"]

MODEL = "gemini-3.6-flash"

RULES = [
    ("R1", "A customer must not be charged twice for the same order."),
    ("R2", "A cancelled order must never be shipped."),
    ("R3", "A refund must be completed within 24 hours of the request."),
]


# ---- Schema: parse (field names follow C1) ----------------------------

class AtMostOnceParse(BaseModel):
    pattern: Literal["at_most_once"]
    event: str = Field(description="the event that may happen at most once")
    per: str = Field(description="entity key field, e.g. 'order_id'")


class NeverAfterParse(BaseModel):
    pattern: Literal["never_after"]
    after: str = Field(description="once this event happened ...")
    event: str = Field(description="... this event must never happen")
    per: str = Field(description="entity key field, e.g. 'order_id'")


class MustPrecedeParse(BaseModel):
    pattern: Literal["must_precede"]
    requires: str = Field(description="this event must happen earlier ...")
    event: str = Field(description="... than this event")
    per: str = Field(description="entity key field, e.g. 'order_id'")


class WithinTimeParse(BaseModel):
    pattern: Literal["within_time"]
    start: str = Field(description="the event that starts the clock")
    event: str = Field(description="the event that must follow")
    within: str = Field(description="ISO 8601 duration, e.g. 'PT24H'")
    per: str = Field(description="entity key field, e.g. 'order_id'")


class UnsupportedParse(BaseModel):
    pattern: Literal["unsupported"]
    reason: str = Field(description="why none of the 4 patterns fits")


# Plain Union -> JSON Schema `anyOf` (accepted by the SDK). The Literal
# `pattern` field still makes Pydantic pick the right model when parsing.
Parse = Union[AtMostOnceParse, NeverAfterParse, MustPrecedeParse,
              WithinTimeParse, UnsupportedParse]


# ---- Schema: ambiguities (unchanged from v1) ---------------------------

class DataField(BaseModel):
    key: str = Field(description="field name, e.g. 'payment_type'")
    value: str = Field(description="field value as a string, e.g. 'installment'")


class EventOccurrence(BaseModel):
    event: str = Field(description="one of the event vocabulary names, e.g. 'charged'")
    data: list[DataField] = Field(
        default_factory=list,
        description="optional fields on this event as key/value pairs; empty list if none",
    )


class ExampleTimeline(BaseModel):
    events: list[EventOccurrence] = Field(description="ordered event occurrences")
    question: str = Field(description="Yes/No question to ask the policy owner about this exact timeline")


class Condition(BaseModel):
    field: str
    op: Literal["eq", "ne", "in"]
    value: str = Field(description="comma-separated list of values if op is 'in'")


class SpecChange(BaseModel):
    kind: Literal["reset_after", "allow_if", "none"]
    event: str | None = Field(default=None, description="required if kind == 'reset_after'")
    condition: Condition | None = Field(default=None, description="required if kind == 'allow_if'")


class Ambiguity(BaseModel):
    id: str = Field(description="short slug, e.g. 'refund-resets-charge'")
    description: str = Field(description="plain English, for a non-technical business owner")
    examples: list[ExampleTimeline] = Field(description="1-2 concrete example timelines")
    spec_change_if_yes: SpecChange = Field(
        description="exact deterministic spec change to apply if the owner answers Yes"
    )


class ClarifyResult(BaseModel):
    rule_id: str
    parse: Parse
    ambiguities: list[Ambiguity]


# ---- Prompt --------------------------------------------------------------

CHECKLIST = """Checklist of decisions to consider (use only the ones that apply to the chosen pattern):
- at_most_once: which event resets the count (e.g. a refund or cancellation)?
  Which field values make a repeat legitimate (e.g. a payment type)?
- never_after: which later event lifts the ban (e.g. the entity is re-opened or re-created)?
  Which field values make the forbidden event acceptable?
- must_precede: can a different earlier event satisfy the requirement?
  Which field values make the requirement unnecessary?
- within_time: is the window calendar time or business hours?
  Which event removes the obligation (e.g. a cancellation)?
  If the start event happens again, does the clock restart?"""


def build_prompt(rule_id: str, rule_text: str) -> str:
    return f"""You are helping a non-technical business/policy owner turn one English
policy rule into a precise, testable specification.

Supported rule patterns (exactly these 4, no others exist), with their fields:
- at_most_once(event, per): event happens at most once per entity
- never_after(after, event, per): once `after` happened, `event` must never happen
- must_precede(requires, event, per): `event` only if `requires` happened earlier
- within_time(start, event, within, per): after `start`, `event` must happen
  within the ISO 8601 duration `within` (e.g. PT24H)
If none fits, use pattern "unsupported" with a reason. Do not force a pattern.

Supported exceptions (exactly these 2):
- reset_after: <event>  (an event resets what the rule has seen for the entity)
- allow_if: {{field, op, value}}  (a structured condition, op is eq/ne/in, that
  makes a matching event invisible to the rule; never code or a string expression)

Event vocabulary (use ONLY these event names, never invent new ones):
{", ".join(EVENT_VOCAB)}

Available fields on events: {", ".join(FIELDS)}

Rule ({rule_id}): "{rule_text}"

Step 1 - Parse: choose the pattern and fill its fields from the vocabulary.

Step 2 - Find DECISION questions: business decisions the owner must make,
where the Yes/No answer changes whether some real timeline is a violation.
Give 2-5 of them if the rule has that many; do not pad with weak questions.
Do NOT ask confirmation questions; they are generated separately:
- the core case (e.g. the forbidden sequence itself is a violation),
- the order of events (e.g. the events in reverse order),
- whether the rule applies per entity (e.g. two different order ids).

{CHECKLIST}

For each question give 1-2 concrete example timelines (each event is
{{event, data}}, where data is a list of {{key, value}} pairs, using only the
event vocabulary and fields above) and phrase it as a Yes/No question about
whether that timeline is allowed. Also give the exact spec_change_if_yes:
kind "reset_after" with an event, kind "allow_if" with a structured condition,
or kind "none" if it cannot be captured that way."""


# ---- Code-side checks (Gemini is not trusted) ---------------------------

def find_problems(result: ClarifyResult) -> list[str]:
    """Return names/fields Gemini used that are outside the vocabulary."""
    problems: list[str] = []
    p = result.parse
    for name in ("event", "after", "requires", "start"):
        value = getattr(p, name, None)
        if value is not None and value not in EVENT_VOCAB:
            problems.append(f"parse.{name}={value!r} not in vocabulary")
    per = getattr(p, "per", None)
    if per is not None and per not in FIELDS:
        problems.append(f"parse.per={per!r} not in fields")
    for a in result.ambiguities:
        for ex in a.examples:
            for occ in ex.events:
                if occ.event not in EVENT_VOCAB:
                    problems.append(f"{a.id}: event {occ.event!r} not in vocabulary")
                for f in occ.data:
                    if f.key not in FIELDS:
                        problems.append(f"{a.id}: field {f.key!r} not in fields")
    return problems


# ---- Gemini call -----------------------------------------------------------

def call_with_retry(client, prompt: str, max_attempts: int = 5):
    """Call Gemini with the v2 schema; retry 503 / network drops, not 429."""
    from google.genai import errors as genai_errors

    transient = (genai_errors.ServerError, httpx.TransportError)
    delay = 2
    for attempt in range(1, max_attempts + 1):
        try:
            return client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config={"response_mime_type": "application/json", "response_schema": ClarifyResult},
            )
        except transient as e:
            if attempt == max_attempts:
                raise
            print(f"  {type(e).__name__} ({e}), retry {attempt}/{max_attempts} in {delay}s...")
            time.sleep(delay)
            delay *= 2


def load_env() -> None:
    for line in Path(".env").read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def main(argv: list[str]) -> None:
    if "--check-schema" in argv:
        schema = json.dumps(ClarifyResult.model_json_schema())
        for key in ("additionalProperties", "discriminator", "oneOf"):
            print(f"{key:22} present: {key in schema}")
        return

    from google import genai

    load_env()
    wanted = [a for a in argv if not a.startswith("--")]
    rules = [r for r in RULES if not wanted or r[0] in wanted]

    client = genai.Client()
    out_dir = Path("spikes/clarify/runs")
    out_dir.mkdir(parents=True, exist_ok=True)

    for rule_id, rule_text in rules:
        response = call_with_retry(client, build_prompt(rule_id, rule_text))
        out_path = out_dir / f"v2_{MODEL}_{rule_id}.json"
        out_path.write_text(response.text)
        result = ClarifyResult.model_validate_json(response.text)
        print(f"--- {rule_id} -> {out_path} ---")
        print(f"parse: {result.parse.model_dump()}")
        for a in result.ambiguities:
            print(f"  - {a.id}: {a.spec_change_if_yes.model_dump(exclude_none=True)}")
        for problem in find_problems(result):
            print(f"  ! {problem}")
        print()


if __name__ == "__main__":
    main(sys.argv[1:])
