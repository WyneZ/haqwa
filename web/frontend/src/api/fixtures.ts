/**
 * MOCK ONLY: question/why/patch and code-generated meaning copied verbatim from
 * spikes/clarify_v2/runs/g2_run3a.json. Base ASTs retain that run's referenced node ids.
 * Placeholder timelines were replaced by hand-written boundaries and confirmations.
 * These fixtures do not evaluate patches or establish production core behavior.
 */
import type { ClarifyResult } from './types'

export const DEMO_RESULTS: ClarifyResult[] = [
  {
    "source": "A customer must not be charged twice for the same order.",
    "status": "supported",
    "rule": {
      "id": "no-double-charge",
      "source": "A customer must not be charged twice for the same order.",
      "version": 2,
      "per": "order_id",
      "root": "rule",
      "nodes": [
        {
          "id": "charged",
          "type": "select",
          "event": "charged",
          "where": [],
          "exclude": []
        },
        {
          "id": "rule",
          "type": "count",
          "of": "charged",
          "op": "le",
          "value": 1,
          "since": []
        }
      ]
    },
    "meaning": "For each order: there must be at most 1 charged event.",
    "questions": [
      {
        "id": "c1",
        "kind": "confirmation",
        "text": "Is this allowed?",
        "why": null,
        "patch": null,
        "timeline": [
          {
            "event": "charged",
            "data": {}
          }
        ],
        "expected_violation": false
      },
      {
        "id": "c2",
        "kind": "confirmation",
        "text": "Is this allowed?",
        "why": null,
        "patch": null,
        "timeline": [
          {
            "event": "charged",
            "data": {}
          },
          {
            "event": "charged",
            "data": {}
          }
        ],
        "expected_violation": true
      },
      {
        "id": "d1",
        "kind": "decision",
        "text": "Does refunding a charge reset the charge count so the customer can be charged again for the order?",
        "why": "If a charge is fully refunded, a business may need to re-charge the customer for the same order without triggering a rule violation.",
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
        "patch": {
          "op": "add_reset",
          "node_id": "rule",
          "event": "refunded"
        },
        "expected_violation": null
      },
      {
        "id": "d2",
        "kind": "decision",
        "text": "Should installment payment charges be exempt from the single-charge rule?",
        "why": "Installment payments legitimately require multiple scheduled charges for a single order.",
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
        "patch": {
          "op": "add_exclude",
          "select_ids": [
            "charged"
          ],
          "condition": {
            "field": "payment_type",
            "op": "eq",
            "value": "installment"
          }
        },
        "expected_violation": null
      }
    ],
    "reason": null
  },
  {
    "source": "A cancelled order must never be shipped.",
    "status": "supported",
    "rule": {
      "id": "no-ship-after-cancel",
      "source": "A cancelled order must never be shipped.",
      "version": 2,
      "per": "order_id",
      "root": "rule",
      "nodes": [
        {
          "id": "shipped",
          "type": "select",
          "event": "shipped",
          "where": [],
          "exclude": []
        },
        {
          "id": "cancelled",
          "type": "select",
          "event": "cancelled",
          "where": [],
          "exclude": []
        },
        {
          "id": "rule",
          "type": "none_after",
          "of": "shipped",
          "after": "cancelled",
          "since": []
        }
      ]
    },
    "meaning": "For each order: once a cancelled event has happened, a shipped event must never happen.",
    "questions": [
      {
        "id": "c1",
        "kind": "confirmation",
        "text": "Is this allowed?",
        "why": null,
        "patch": null,
        "timeline": [
          {
            "event": "cancelled",
            "data": {}
          },
          {
            "event": "shipped",
            "data": {}
          }
        ],
        "expected_violation": true
      },
      {
        "id": "c2",
        "kind": "confirmation",
        "text": "Is this allowed?",
        "why": null,
        "patch": null,
        "timeline": [
          {
            "event": "shipped",
            "data": {}
          },
          {
            "event": "cancelled",
            "data": {}
          }
        ],
        "expected_violation": false
      },
      {
        "id": "d1",
        "kind": "decision",
        "text": "If an order is created again after being cancelled, does that lift the ban on shipping it?",
        "why": "Re-opening or re-creating an order generates a new order_created event that could reset the cancellation state and allow subsequent shipping.",
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
        "patch": {
          "op": "add_reset",
          "node_id": "rule",
          "event": "order_created"
        },
        "expected_violation": null
      }
    ],
    "reason": null
  },
  {
    "source": "A refund must be completed within 24 hours of the request.",
    "status": "supported",
    "rule": {
      "id": "refund-within-24h",
      "source": "A refund must be completed within 24 hours of the request.",
      "version": 2,
      "per": "order_id",
      "root": "rule",
      "nodes": [
        {
          "id": "start",
          "type": "select",
          "event": "refund_requested",
          "where": [],
          "exclude": []
        },
        {
          "id": "finish",
          "type": "select",
          "event": "refund_completed",
          "where": [],
          "exclude": []
        },
        {
          "id": "rule",
          "type": "every_followed_within",
          "start": "start",
          "by": "finish",
          "within": "PT24H",
          "since": []
        }
      ]
    },
    "meaning": "For each order: every refund requested event must be followed by a refund completed event within 24 hours (one refund completed event covers every earlier open refund requested event).",
    "questions": [
      {
        "id": "c1",
        "kind": "confirmation",
        "text": "Is this allowed?",
        "why": null,
        "patch": null,
        "timeline": [
          {
            "event": "refund_requested",
            "data": {},
            "at": "PT0S"
          },
          {
            "event": "refund_completed",
            "data": {},
            "at": "PT24H"
          }
        ],
        "expected_violation": false
      },
      {
        "id": "c2",
        "kind": "confirmation",
        "text": "Is this allowed?",
        "why": null,
        "patch": null,
        "timeline": [
          {
            "event": "refund_requested",
            "data": {},
            "at": "PT0S"
          },
          {
            "event": "refund_completed",
            "data": {},
            "at": "PT25H"
          }
        ],
        "expected_violation": true
      },
      {
        "id": "d1",
        "kind": "decision",
        "text": "If an order is cancelled, does that remove the obligation to complete a pending refund request within 24 hours?",
        "why": "Order cancellation may render open refund requests void or handle them through a different process.",
        "timeline": [
          {
            "event": "refund_requested",
            "data": {},
            "at": "PT0S"
          },
          {
            "event": "cancelled",
            "data": {},
            "at": "PT2H"
          },
          {
            "event": "refund_completed",
            "data": {},
            "at": "PT25H"
          }
        ],
        "patch": {
          "op": "add_reset",
          "node_id": "rule",
          "event": "cancelled"
        },
        "expected_violation": null
      },
      {
        "id": "d2",
        "kind": "decision",
        "text": "If a new refund request is submitted before the previous one is completed, does the 24-hour completion deadline restart from the new request?",
        "why": "A revised or repeated request might reset the SLA timer for processing.",
        "timeline": [
          {
            "event": "refund_requested",
            "data": {},
            "at": "PT0S"
          },
          {
            "event": "refund_requested",
            "data": {},
            "at": "PT20H"
          },
          {
            "event": "refund_completed",
            "data": {},
            "at": "PT40H"
          }
        ],
        "patch": {
          "op": "add_reset",
          "node_id": "rule",
          "event": "refund_requested"
        },
        "expected_violation": null
      },
      {
        "id": "d3",
        "kind": "decision",
        "text": "Should installment payment orders be exempt from the 24-hour refund completion rule?",
        "why": "Installment refunds often depend on external financing partners and cannot meet standard 24-hour processing timelines.",
        "timeline": [
          {
            "event": "refund_requested",
            "data": {
              "payment_type": "installment"
            },
            "at": "PT0S"
          },
          {
            "event": "refund_completed",
            "data": {
              "payment_type": "installment"
            },
            "at": "PT25H"
          }
        ],
        "patch": {
          "op": "add_exclude",
          "select_ids": [
            "start",
            "finish"
          ],
          "condition": {
            "field": "payment_type",
            "op": "eq",
            "value": "installment"
          }
        },
        "expected_violation": null
      }
    ],
    "reason": null
  }
]
