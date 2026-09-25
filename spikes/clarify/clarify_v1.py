"""Spike step 4: prompt v1 + schema for the clarification loop.

Given a rule, ask Gemini to:
1. parse it into pattern/event/per (or mark unsupported), and
2. find ambiguities a business owner must decide, each with 1-2 example
   timelines and a candidate spec change to apply on a "Yes" answer
   (design option (b) from the spike notes: deterministic apply, not a
   Gemini regenerate).

Run: uv run python spikes/clarify/clarify_v1.py
Outputs: spikes/clarify/runs/v1_<model>_<rule_id>.json
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Literal

import httpx
from google import genai
from google.genai import errors as genai_errors
from pydantic import BaseModel, Field

logging.getLogger("google_genai.models").setLevel(logging.ERROR)

for line in Path(".env").read_text().splitlines():
    if "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

PATTERNS = ("at_most_once", "never_after", "must_precede", "within_time")

EVENT_VOCAB = [
    "order_created", "charged", "charge_failed", "refunded",
    "cancelled", "shipped", "refund_requested", "refund_completed",
]
FIELDS = ["order_id", "customer_id", "payment_type", "amount", "time"]


# ---- Schema ----------------------------------------------------------
# Aligned to C1 (docs/contracts.md, locked 2026-09-25): allow_if is a
# structured condition (no string expressions, no eval), and timeline
# events use the same {event, data} shape as C2 events - no mini-parser
# needed to turn "charged(installment)" back into structured data.

class EventOccurrence(BaseModel):
    event: str = Field(description="one of the event vocabulary names, e.g. 'charged'")
    data: dict[str, str] = Field(
        default_factory=dict,
        description="extra fields on this occurrence, e.g. {'payment_type': 'installment'}",
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


class ParseResult(BaseModel):
    pattern: Literal["at_most_once", "never_after", "must_precede", "within_time"] | None = None
    event: str | None = None
    per: str | None = None
    supported: bool
    unsupported_reason: str | None = Field(
        default=None, description="Required if supported=false: why no pattern fits"
    )


class ClarifyResult(BaseModel):
    rule_id: str
    parse: ParseResult
    ambiguities: list[Ambiguity]


# ---- Prompt ------------------------------------------------------------

def build_prompt(rule_id: str, rule_text: str) -> str:
    return f"""You are helping a non-technical business/policy owner turn one English
policy rule into a precise, testable specification.

Supported rule patterns (exactly these 4, no others exist):
- at_most_once: X happens at most once per entity
- never_after: after X, Y must never happen
- must_precede: X must happen before Y
- within_time: after X, Y must happen within a time window

Supported exceptions (exactly these 2):
- reset_after: <event>  (an event resets an at_most_once/never_after counter)
- allow_if: {{field, op, value}}  (a structured condition, op is eq/ne/in, that
  makes an otherwise-matching event allowed; never write it as code or a
  string expression)

Event vocabulary (use ONLY these event names, never invent new ones):
{", ".join(EVENT_VOCAB)}

Available fields on events: {", ".join(FIELDS)}

Rule ({rule_id}): "{rule_text}"

Step 1 - Parse: Which of the 4 patterns fits this rule? If none fits, set
supported=false and explain why in unsupported_reason (do not force a
pattern that does not really match).

Step 2 - Find ambiguities: List the specific business decisions a policy
owner (not a developer) must make to fully pin down this rule's meaning.
For each ambiguity, give 1-2 concrete example event timelines (each event is
{{event, data}}, using only the event vocabulary and fields above) that would
resolve it, phrased as a yes/no question about whether that timeline is a
violation. Also give the exact deterministic spec_change_if_yes: kind
"reset_after" with an event, kind "allow_if" with a structured condition, or
kind "none" if the ambiguity cannot be captured that way.

Only include ambiguities that would change whether some real timeline counts
as a violation. Do not ask questions the developer should already know the
answer to from the event vocabulary alone."""


RULES = [
    ("R1", "A customer must not be charged twice for the same order."),
    ("R2", "A cancelled order must never be shipped."),
    ("R3", "A refund must be completed within 24 hours of the request."),
]

MODEL = "gemini-3.6-flash"


# Transient == worth retrying: 503 from Gemini itself (ServerError), and
# network-level drops from the underlying httpx client (connection reset,
# server closing the socket mid-response, timeouts, ...). A 429 (quota) is
# NOT included: retrying will not help, that needs the caching / clear
# message handling planned for ai/client.py in week 2.
TRANSIENT = (genai_errors.ServerError, httpx.TransportError)


def call_with_retry(client, prompt, max_attempts=5):
    delay = 2
    for attempt in range(1, max_attempts + 1):
        try:
            return client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config={"response_mime_type": "application/json", "response_schema": ClarifyResult},
            )
        except TRANSIENT as e:
            if attempt == max_attempts:
                raise
            print(f"  {type(e).__name__} ({e}), retry {attempt}/{max_attempts} in {delay}s...")
            time.sleep(delay)
            delay *= 2


def main() -> None:
    client = genai.Client()
    out_dir = Path("spikes/clarify/runs")
    out_dir.mkdir(parents=True, exist_ok=True)

    for rule_id, rule_text in RULES:
        prompt = build_prompt(rule_id, rule_text)
        response = call_with_retry(client, prompt)
        out_path = out_dir / f"v1_{MODEL}_{rule_id}.json"
        out_path.write_text(response.text)
        print(f"--- {rule_id} -> {out_path} ---")
        print(response.text)
        print()


if __name__ == "__main__":
    main()
