/**
 * Demo data for screens 2-3 in mock mode. NOT hand-written:
 * - DEMO_SCENARIOS: Track B's `demo.list_scenarios()`.
 * - DEMO_RUNS: `demo.run_scenario(id, spec)` for each scenario, with the three demo rules
 *   (no-double-charge with both owner decisions = Yes; the other two with none).
 * - DEMO_EXPLANATIONS: the real Gemini answer from `spikes/explain/smoke_explain.py`
 *   (gemini-3.6-flash, 2026-10-05). Both naive scenarios produce the same violation.
 * Regenerate if core, demo or explain changes.
 */
import type { RunResponse, Scenario } from './types'

export const DEMO_SCENARIOS: Scenario[] = [
  {
    "id": "payment_timeout_naive",
    "title": "Payment timeout — naive agent",
    "fault": "timeout_after_commit",
    "agent": "naive",
    "description": "The charge succeeds, then the API times out; the agent retries without an idempotency key.",
    "expected": "violation"
  },
  {
    "id": "payment_timeout_fixed",
    "title": "Payment timeout — fixed agent",
    "fault": "timeout_after_commit",
    "agent": "fixed",
    "description": "Same timeout; the agent retries with one idempotency key.",
    "expected": "pass"
  },
  {
    "id": "duplicate_webhook_naive",
    "title": "Duplicate webhook — naive consumer",
    "fault": "duplicate_event",
    "agent": "naive",
    "description": "The charge request message is delivered twice; the consumer charges twice.",
    "expected": "violation"
  },
  {
    "id": "duplicate_webhook_fixed",
    "title": "Duplicate webhook — fixed consumer",
    "fault": "duplicate_event",
    "agent": "fixed",
    "description": "Same duplicate delivery; the consumer dedupes by message id.",
    "expected": "pass"
  }
]

export const DEMO_RUNS: Record<string, RunResponse> = {
  "payment_timeout_naive": {
    "events": [
      {
        "event": "order_created",
        "ts": "2026-01-01T00:00:00Z",
        "data": {
          "order_id": "A-1",
          "amount": 50
        },
        "source_id": "eff_001"
      },
      {
        "event": "charged",
        "ts": "2026-01-01T00:00:00Z",
        "data": {
          "order_id": "A-1",
          "amount": 50
        },
        "source_id": "eff_002"
      },
      {
        "event": "charged",
        "ts": "2026-01-01T00:00:00Z",
        "data": {
          "order_id": "A-1",
          "amount": 50
        },
        "source_id": "eff_003"
      }
    ],
    "report": {
      "results": [
        {
          "rule_id": "no-double-charge",
          "source": "A customer must not be charged twice for the same order.",
          "status": "violation",
          "violations": [
            {
              "rule_id": "no-double-charge",
              "entity": "A-1",
              "message": "'charged' happened 2 times with no refunded in between",
              "timeline": [
                {
                  "event": "order_created",
                  "ts": "2026-01-01T00:00:00Z",
                  "data": {
                    "order_id": "A-1",
                    "amount": 50
                  },
                  "source_id": "eff_001"
                },
                {
                  "event": "charged",
                  "ts": "2026-01-01T00:00:00Z",
                  "data": {
                    "order_id": "A-1",
                    "amount": 50
                  },
                  "source_id": "eff_002"
                },
                {
                  "event": "charged",
                  "ts": "2026-01-01T00:00:00Z",
                  "data": {
                    "order_id": "A-1",
                    "amount": 50
                  },
                  "source_id": "eff_003"
                }
              ],
              "offending_index": 2
            }
          ]
        },
        {
          "rule_id": "no-ship-after-cancel",
          "source": "A cancelled order must never be shipped.",
          "status": "pass",
          "violations": []
        },
        {
          "rule_id": "refund-within-24h",
          "source": "A refund must be completed within 24 hours of the request.",
          "status": "pass",
          "violations": []
        }
      ]
    }
  },
  "payment_timeout_fixed": {
    "events": [
      {
        "event": "order_created",
        "ts": "2026-01-01T00:00:00Z",
        "data": {
          "order_id": "A-1",
          "amount": 50
        },
        "source_id": "eff_001"
      },
      {
        "event": "charged",
        "ts": "2026-01-01T00:00:00Z",
        "data": {
          "order_id": "A-1",
          "amount": 50
        },
        "source_id": "eff_002"
      }
    ],
    "report": {
      "results": [
        {
          "rule_id": "no-double-charge",
          "source": "A customer must not be charged twice for the same order.",
          "status": "pass",
          "violations": []
        },
        {
          "rule_id": "no-ship-after-cancel",
          "source": "A cancelled order must never be shipped.",
          "status": "pass",
          "violations": []
        },
        {
          "rule_id": "refund-within-24h",
          "source": "A refund must be completed within 24 hours of the request.",
          "status": "pass",
          "violations": []
        }
      ]
    }
  },
  "duplicate_webhook_naive": {
    "events": [
      {
        "event": "order_created",
        "ts": "2026-01-01T00:00:00Z",
        "data": {
          "order_id": "A-1",
          "amount": 50
        },
        "source_id": "eff_001"
      },
      {
        "event": "charged",
        "ts": "2026-01-01T00:00:00Z",
        "data": {
          "order_id": "A-1",
          "amount": 50
        },
        "source_id": "eff_002"
      },
      {
        "event": "charged",
        "ts": "2026-01-01T00:00:00Z",
        "data": {
          "order_id": "A-1",
          "amount": 50
        },
        "source_id": "eff_003"
      }
    ],
    "report": {
      "results": [
        {
          "rule_id": "no-double-charge",
          "source": "A customer must not be charged twice for the same order.",
          "status": "violation",
          "violations": [
            {
              "rule_id": "no-double-charge",
              "entity": "A-1",
              "message": "'charged' happened 2 times with no refunded in between",
              "timeline": [
                {
                  "event": "order_created",
                  "ts": "2026-01-01T00:00:00Z",
                  "data": {
                    "order_id": "A-1",
                    "amount": 50
                  },
                  "source_id": "eff_001"
                },
                {
                  "event": "charged",
                  "ts": "2026-01-01T00:00:00Z",
                  "data": {
                    "order_id": "A-1",
                    "amount": 50
                  },
                  "source_id": "eff_002"
                },
                {
                  "event": "charged",
                  "ts": "2026-01-01T00:00:00Z",
                  "data": {
                    "order_id": "A-1",
                    "amount": 50
                  },
                  "source_id": "eff_003"
                }
              ],
              "offending_index": 2
            }
          ]
        },
        {
          "rule_id": "no-ship-after-cancel",
          "source": "A cancelled order must never be shipped.",
          "status": "pass",
          "violations": []
        },
        {
          "rule_id": "refund-within-24h",
          "source": "A refund must be completed within 24 hours of the request.",
          "status": "pass",
          "violations": []
        }
      ]
    }
  },
  "duplicate_webhook_fixed": {
    "events": [
      {
        "event": "order_created",
        "ts": "2026-01-01T00:00:00Z",
        "data": {
          "order_id": "A-1",
          "amount": 50
        },
        "source_id": "eff_001"
      },
      {
        "event": "charged",
        "ts": "2026-01-01T00:00:00Z",
        "data": {
          "order_id": "A-1",
          "amount": 50
        },
        "source_id": "eff_002"
      }
    ],
    "report": {
      "results": [
        {
          "rule_id": "no-double-charge",
          "source": "A customer must not be charged twice for the same order.",
          "status": "pass",
          "violations": []
        },
        {
          "rule_id": "no-ship-after-cancel",
          "source": "A cancelled order must never be shipped.",
          "status": "pass",
          "violations": []
        },
        {
          "rule_id": "refund-within-24h",
          "source": "A refund must be completed within 24 hours of the request.",
          "status": "pass",
          "violations": []
        }
      ]
    }
  }
}

/** Key: `${rule_id}|${entity}|${message}` of the violation. */
export const DEMO_EXPLANATIONS: Record<string, string> = {
  "no-double-charge|A-1|'charged' happened 2 times with no refunded in between": "Order A-1 was charged twice for amount 50 without a refund occurring in between. This was likely caused by a duplicate payment request being processed at the exact same time."
}
