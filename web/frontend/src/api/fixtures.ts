/**
 * Demo data for mock mode: the REAL Gemini answers from spike v2.1 (runs/v21_*_run1.json),
 * passed through ai.clarify() and dumped in C3 shape. Regenerate if clarify changes.
 */
import type { ClarifyResult } from './types'

export const DEMO_RESULTS: ClarifyResult[] = [
  {
    "source": "A customer must not be charged twice for the same order.",
    "status": "supported",
    "rule": {
      "id": "no-double-charge",
      "source": "A customer must not be charged twice for the same order.",
      "per": "order_id",
      "except": [],
      "confirmed_examples": [],
      "pattern": "at_most_once",
      "event": "charged"
    },
    "questions": [
      {
        "id": "d1",
        "kind": "decision",
        "text": "If an order has been charged and then refunded, is a second charge allowed on the same order?",
        "timeline": [
          {
            "event": "charged",
            "data": {}
          },
          {
            "event": "refunded",
            "data": {}
          },
          {
            "event": "charged",
            "data": {}
          }
        ],
        "if_yes": {
          "reset_after": "refunded"
        }
      },
      {
        "id": "d2",
        "kind": "decision",
        "text": "Is charging an order multiple times allowed when the payment type is installment?",
        "timeline": [
          {
            "event": "charged",
            "data": {
              "payment_type": "installment"
            }
          },
          {
            "event": "charged",
            "data": {
              "payment_type": "installment"
            }
          }
        ],
        "if_yes": {
          "allow_if": {
            "field": "payment_type",
            "op": "eq",
            "value": "installment"
          }
        }
      }
    ]
  },
  {
    "source": "A cancelled order must never be shipped.",
    "status": "supported",
    "rule": {
      "id": "no-ship-after-cancel",
      "source": "A cancelled order must never be shipped.",
      "per": "order_id",
      "except": [],
      "confirmed_examples": [],
      "pattern": "never_after",
      "event": "shipped",
      "after": "cancelled"
    },
    "questions": [
      {
        "id": "d1",
        "kind": "decision",
        "text": "If an order is cancelled and then re-created, is it allowed to be shipped?",
        "timeline": [
          {
            "event": "cancelled",
            "data": {}
          },
          {
            "event": "order_created",
            "data": {}
          },
          {
            "event": "shipped",
            "data": {}
          }
        ],
        "if_yes": {
          "reset_after": "order_created"
        }
      }
    ]
  },
  {
    "source": "A refund must be completed within 24 hours of the request.",
    "status": "supported",
    "rule": {
      "id": "refund-within-24h",
      "source": "A refund must be completed within 24 hours of the request.",
      "per": "order_id",
      "except": [],
      "confirmed_examples": [],
      "pattern": "within_time",
      "start": "refund_requested",
      "event": "refund_completed",
      "within": "P1D"
    },
    "questions": [
      {
        "id": "d1",
        "kind": "decision",
        "text": "If an order is cancelled after a refund request, is it allowed for no refund to be completed within 24 hours?",
        "timeline": [
          {
            "event": "refund_requested",
            "data": {}
          },
          {
            "event": "cancelled",
            "data": {}
          }
        ],
        "if_yes": {
          "reset_after": "cancelled"
        }
      },
      {
        "id": "d2",
        "kind": "decision",
        "text": "If a second refund request is submitted, does the 24-hour window restart from the time of the second request?",
        "timeline": [
          {
            "event": "refund_requested",
            "data": {}
          },
          {
            "event": "refund_requested",
            "data": {}
          },
          {
            "event": "refund_completed",
            "data": {}
          }
        ],
        "if_yes": {
          "reset_after": "refund_requested"
        }
      },
      {
        "id": "d3",
        "kind": "decision",
        "text": "Is it allowed for an installment payment refund request to remain uncompleted past 24 hours?",
        "timeline": [
          {
            "event": "refund_requested",
            "data": {
              "payment_type": "installment"
            }
          }
        ],
        "if_yes": {
          "allow_if": {
            "field": "payment_type",
            "op": "eq",
            "value": "installment"
          }
        }
      }
    ]
  }
]
