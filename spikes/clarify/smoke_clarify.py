"""Live smoke test: call the real ai.clarify() once for R1 and print the result.

Uses 1 Gemini request the first time. Running it again prints `cached: True`
and uses 0 requests (answer read from .haqwa_cache/).

Run:  uv run python spikes/clarify/smoke_clarify.py
Needs GEMINI_API_KEY in .env (never printed).
"""

from __future__ import annotations

import os
from pathlib import Path

from haqwa.ai import GeminiClient, GeminiError, ParseError, Vocabulary, clarify

SHOP = Vocabulary(
    events=["order_created", "charged", "charge_failed", "refunded", "cancelled", "shipped",
            "refund_requested", "refund_completed"],
    fields=["order_id", "customer_id", "payment_type", "amount", "time"],
    field_values={"payment_type": ["card", "installment"]},
)  # fmt: skip

RULE = "A customer must not be charged twice for the same order."


def load_env() -> None:
    """Read KEY=VALUE lines from .env into the environment (values are never printed)."""
    env = Path(".env")
    if not env.exists():
        raise SystemExit("No .env file in the current folder. Run from the repo root.")
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def main() -> None:
    load_env()
    client = GeminiClient()
    print(f"model: {client.model}")
    try:
        outcome = clarify(RULE, rule_id="no-double-charge", vocab=SHOP, client=client)
    except GeminiError as e:
        raise SystemExit(f"Gemini error: {type(e).__name__}: {e}") from e
    except ParseError as e:
        raise SystemExit(f"Gemini draft rejected by code: {e.problems}") from e

    print(f"cached: {outcome.cached}")
    print(f"status: {outcome.status}")
    if outcome.rule is not None:
        print(f"rule:   {outcome.rule.model_dump(by_alias=True, exclude_defaults=True)}")
    for q in outcome.questions:
        timeline = " -> ".join(e.event + (f"{e.data}" if e.data else "") for e in q.timeline)
        change = q.if_yes.model_dump() if q.if_yes else None
        print(f"  {q.id} [{q.kind}] {q.text}")
        print(f"       timeline: {timeline}")
        print(f"       if yes:   {change}")
    for d in outcome.dropped:
        print(f"  dropped {d.gemini_id}: {'; '.join(d.reasons)}")


if __name__ == "__main__":
    main()
