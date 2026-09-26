# Spike notes

## 2026-09-23 — hello.py
- 503 UNAVAILABLE twice (free tier, high demand); third try OK.
  → ai/client.py needs backoff retry (503), clear message (429), demo cache.
- "Every order must have an invoice" with Literal pattern
  → forced to must_precede, invented event "invoice".
  → Schema needs an escape hatch (supported + reason).
  → Event names must be validated in code, not trusted from Gemini.

## 2026-09-25/26 — clarify_v1.py (prompt v1)

- `dict[str, str]` in the schema made Pydantic emit `additionalProperties`;
  the Gemini Developer API rejects it before any call.
  → Wire format is now `data: [{key, value}]`; C1 unchanged (see decisions.md).
  → Lesson: after any schema change, run the offline check AND one real API call.
- 503 again: on Sep 25, R2 failed after 5 retries (~30 s). Re-run on Sep 26 OK.
  → Demo needs cached Gemini results (ai/client.py, week 2).
- Results (Sep 26 run):
  - R1: 2 ambiguities — `reset_after: refunded`, `allow_if: payment_type eq installment`.
    Same two questions on Sep 25 and Sep 26 (stable).
  - R2: 1 ambiguity — `reset_after: order_created` (re-created order).
  - R3: 1 ambiguity — `reset_after: cancelled`.
  - All event and field names are from the vocabulary (no invented names).
- Schema gap: `ParseResult` has a single `event`. never_after / within_time need
  two events (+ a window). R2 returned `event: cancelled` (lost `shipped`);
  R3 returned `event: refund_completed` (lost `refund_requested` and `24h`).
  → v2: per-pattern parse fields aligned with C1 (ties to contracts open Q5).
- R3: Gemini put `time` into event `data` to express timing.
  → Evidence for contracts open Q1 (within_time examples need time).
- Recall vs golden: R3 found 0 of 2 in-scope golden items (G3.1 clock type,
  G3.4 absence). Its cancel question is not in golden — owner to judge
  (noise or a missing golden item). R1/R2 sections are missing from golden.md,
  so R1/R2 cannot be scored yet.
