"""Spike step 7: prompt v2.1 — reduce noise (invented field values).

Same schema and parse as v2 (clarify_v2.py). Noise fixes (NOTES.md, 2026-09-28):
A. The prompt lists the allowed VALUES for fields that have a closed set
   (FIELD_VALUES), so Gemini does not invent values like 'replacement'.
B. The generic "which field values make ... acceptable?" checklist lines are
   removed; they pushed Gemini to pad with invented exemptions.
C. Code drops any question that uses an event, field or value outside the
   vocabulary (Gemini is not trusted). The raw answer is kept for evidence.
Also: the within_time clock-type question is removed from the checklist; it is
a fixed confirmation from the core template now (golden G3.1, D3).

Run (all rules, once):     uv run python spikes/clarify/clarify_v21.py
Run (some rules):          uv run python spikes/clarify/clarify_v21.py R2 R3
Run each rule 3 times:     uv run python spikes/clarify/clarify_v21.py --repeat 3
Continue from run 2:       uv run python spikes/clarify/clarify_v21.py --repeat 2 --start 2
Offline schema check:      uv run python spikes/clarify/clarify_v21.py --check-schema
Outputs: spikes/clarify/runs/v21_<model>_<rule_id>_run<n>.json
         = {"raw": <Gemini answer>, "kept": [ids], "dropped": [{id, reasons}]}
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

# Closed value sets (demo: written by the owner; product: from event-log samples).
# Fields not listed here (ids, amount, time) take free values.
FIELD_VALUES: dict[str, list[str]] = {
    "payment_type": ["card", "installment"],
}

# Default model. Override with HAQWA_MODEL in .env (e.g. a Flash Lite model
# with a higher free-tier daily quota) without editing this file.
MODEL = "gemini-3.6-flash"

# Free tier allows 5 requests per minute for this model (429 seen on
# 2026-09-28, quotaId GenerateRequestsPerMinutePerProjectPerModel-FreeTier).
# Wait between calls so a multi-run stays under the limit.
PACE_SECONDS = 13

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
- never_after: which later event lifts the ban (e.g. the entity is re-opened or re-created)?
- must_precede: can a different earlier event satisfy the requirement?
- within_time: which event removes the obligation (e.g. a cancellation)?
  If the start event happens again, does the clock restart?
- any pattern: an exemption based on a field value, ONLY if that value is in
  the allowed values list below and a real business would plausibly use it."""


def values_text() -> str:
    return "; ".join(f"{k}: {', '.join(v)}" for k, v in FIELD_VALUES.items())


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
Allowed values (use ONLY these values for these fields, never invent others):
{values_text()}

Rule ({rule_id}): "{rule_text}"

Step 1 - Parse: choose the pattern and fill its fields from the vocabulary.

Step 2 - Find DECISION questions: business decisions the owner must make,
where the Yes/No answer changes whether some real timeline is a violation.
Give 2-5 of them if the rule has that many; do not pad with weak questions.
Do NOT ask confirmation questions; they are generated separately:
- the core case (e.g. the forbidden sequence itself is a violation),
- the order of events (e.g. the events in reverse order),
- whether the rule applies per entity (e.g. two different order ids),
- whether a time window means calendar hours (it always does).
Asking fewer, real questions is better than inventing exemptions.

{CHECKLIST}

For each question give 1-2 concrete example timelines (each event is
{{event, data}}, where data is a list of {{key, value}} pairs, using only the
event vocabulary and fields above) and phrase it as a Yes/No question about
whether that timeline is allowed. Also give the exact spec_change_if_yes:
kind "reset_after" with an event, kind "allow_if" with a structured condition,
or kind "none" if it cannot be captured that way."""


# ---- Code-side checks (Gemini is not trusted) ---------------------------

def _value_problem(field: str, value: str) -> str | None:
    allowed = FIELD_VALUES.get(field)
    if allowed is None:
        return None
    bad = [v.strip() for v in value.split(",") if v.strip() not in allowed]
    return f"value {bad} for {field!r} not in {allowed}" if bad else None


def parse_problems(result: ClarifyResult) -> list[str]:
    """Names Gemini used in the parse that are outside the vocabulary."""
    problems: list[str] = []
    p = result.parse
    for name in ("event", "after", "requires", "start"):
        value = getattr(p, name, None)
        if value is not None and value not in EVENT_VOCAB:
            problems.append(f"parse.{name}={value!r} not in vocabulary")
    per = getattr(p, "per", None)
    if per is not None and per not in FIELDS:
        problems.append(f"parse.per={per!r} not in fields")
    return problems


def ambiguity_problems(a: Ambiguity) -> list[str]:
    """Reasons to drop one question: unknown event, field or value."""
    problems: list[str] = []
    for ex in a.examples:
        for occ in ex.events:
            if occ.event not in EVENT_VOCAB:
                problems.append(f"event {occ.event!r} not in vocabulary")
            for f in occ.data:
                if f.key not in FIELDS:
                    problems.append(f"field {f.key!r} not in fields")
                elif (msg := _value_problem(f.key, f.value)):
                    problems.append(msg)
    sc = a.spec_change_if_yes
    if sc.kind == "reset_after" and sc.event not in EVENT_VOCAB:
        problems.append(f"reset_after event {sc.event!r} not in vocabulary")
    if sc.kind == "allow_if" and sc.condition is not None:
        if sc.condition.field not in FIELDS:
            problems.append(f"allow_if field {sc.condition.field!r} not in fields")
        elif (msg := _value_problem(sc.condition.field, sc.condition.value)):
            problems.append(f"allow_if {msg}")
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
    global MODEL
    MODEL = os.environ.get("HAQWA_MODEL", MODEL)
    print(f"model: {MODEL}")
    repeat = int(argv[argv.index("--repeat") + 1]) if "--repeat" in argv else 1
    start = int(argv[argv.index("--start") + 1]) if "--start" in argv else 1
    wanted = [a for a in argv if a.startswith("R")]
    rules = [r for r in RULES if not wanted or r[0] in wanted]

    client = genai.Client()
    out_dir = Path("spikes/clarify/runs")
    out_dir.mkdir(parents=True, exist_ok=True)

    first_call = True
    for n in range(start, start + repeat):
        for rule_id, rule_text in rules:
            if not first_call:
                time.sleep(PACE_SECONDS)
            first_call = False
            response = call_with_retry(client, build_prompt(rule_id, rule_text))
            result = ClarifyResult.model_validate_json(response.text)
            kept, dropped = [], []
            for a in result.ambiguities:
                reasons = ambiguity_problems(a)
                if reasons:
                    dropped.append({"id": a.id, "reasons": reasons})
                else:
                    kept.append(a.id)
            out_path = out_dir / f"v21_{MODEL}_{rule_id}_run{n}.json"
            out_path.write_text(json.dumps(
                {"raw": json.loads(response.text), "kept": kept, "dropped": dropped},
                indent=2,
            ))
            print(f"--- {rule_id} run {n} -> {out_path} ---")
            print(f"parse: {result.parse.model_dump()}")
            for problem in parse_problems(result):
                print(f"  ! {problem}")
            for a in result.ambiguities:
                mark = "KEEP" if a.id in kept else "DROP"
                print(f"  {mark} {a.id}: {a.spec_change_if_yes.model_dump(exclude_none=True)}")
            for d in dropped:
                print(f"       dropped {d['id']}: {'; '.join(d['reasons'])}")
            print()


if __name__ == "__main__":
    main(sys.argv[1:])
