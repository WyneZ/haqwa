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

## 2026-09-27 — scoring v1 against golden (manual, option A labels)

R1/R2 golden items were rewritten by Hazel from a pattern checklist (after
seeing the v1 runs, so some bias risk). Matching Gemini question -> golden id
was done by meaning and confirmed by the owner.

| Rule | Gemini question -> golden | Recall (all `in`) | Noise |
|---|---|---|---|
| R1 | refund-resets-charge -> G1.1; allow-installment-payments -> G1.2 | 2/4 | 0 |
| R2 | recreation-resets-cancellation -> G2.1 | 1/4 | 0 |
| R3 | cancellation-resets-refund-window -> G3.5 | 1/3 | 0 |
| Total | | 4/11 = 36% | 0 |

Split by type:
- Decision questions (answer changes the spec: G1.1, G1.2, G2.1, G3.1, G3.5):
  Gemini found 4/5 = 80%. Missed G3.1 (calendar vs business hours).
- Confirmation questions (core case, event order, per-entity, absence:
  G1.3, G1.4, G2.2, G2.3, G2.4, G3.4): Gemini found 0/6. The prompt tells it
  not to ask what the developer already knows, which likely suppresses them.

Decision: confirmations come from a per-pattern code template (see
decisions.md, 2026-09-27). Prompt v2 focuses Gemini on decision questions and
adds a per-pattern checklist (e.g. within_time: clock type).

## 2026-09-28 — prompt v2 (clarify_v2.py)

- Parse is a per-pattern union with C1 field names. Parse correct: v1 1/3 -> v2 3/3
  (v1 lost `shipped` in R2 and `refund_requested` + 24h in R3).
- Q5 answered: `oneOf` + `discriminator` is rejected client-side by
  google-genai 2.25.0 (tested offline with a fake key); `anyOf` passes the SDK
  and the server (real runs OK).
- Decision questions 4/5 as in v1; confirmation questions no longer asked (by design).
- Noise 2: Gemini invented payment_type values `replacement` (R2) and
  `store_credit` (R3), pushed by the checklist line "which field values make
  ... acceptable?". Code checked field names only, not values.
- Owner decisions: D1 invented-value exemptions = noise; D2 G3.2 reframed as
  "new request restarts the clock?" (in, decision); D3 G3.1 clock type moves to
  the within_time confirmation template.

## 2026-09-28/29 — prompt v2.1 (clarify_v21.py), 3 runs per rule

Changes: closed value list (`payment_type: card, installment`), generic
field-value checklist lines removed, code drops questions with unknown
event/field/value (raw answer kept in the run file).

| Rule | Decision questions found (run1/run2/run3) | Dropped by code | Other |
|---|---|---|---|
| R1 | G1.1, G1.2 / same / same | 0 | — |
| R2 | G2.1 / same / same | 0 | — |
| R3 | G3.2, G3.5 / same / same | 0 | installment exemption in 3/3 runs |

- Parse correct 9/9. No invented values: the prompt change alone removed them
  (code filter C had nothing to drop, but stays as a safety net).
- R3 installment exemption asked in all 3 runs; owner (Hazel) judged it a valid
  question -> golden G3.6. Final: decision questions 6/6 in every run, noise 0.
- Results are stable across runs (same questions, different wording/ids).

## 2026-09-28/29 — Gemini free-tier limits (seen in 429 errors)

- gemini-3.6-flash free tier: 5 requests/minute and 20 requests/day per project
  (quotaIds ...PerMinute... = 5, ...PerDay... = 20). 503 retries also count.
- 503 "high demand" happened on every run day (Sep 23, 25, 26, 28, 29).
- Impact: development, the evidence experiment and judges using the demo all
  share 20/day. -> ai/client.py needs a cache and a clear 429 message; use
  saved run files as test fixtures; separate keys per developer; paid tier is a
  team decision (brief §17 says no upgrade during the hackathon).
