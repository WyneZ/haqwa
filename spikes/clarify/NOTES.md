# Spike notes

## 2026-09-23 — hello.py
- 503 UNAVAILABLE twice (free tier, high demand); third try OK.
  → ai/client.py needs backoff retry (503), clear message (429), demo cache.
- "Every order must have an invoice" with Literal pattern
  → forced to must_precede, invented event "invoice".
  → Schema needs an escape hatch (supported + reason).
  → Event names must be validated in code, not trusted from Gemini.