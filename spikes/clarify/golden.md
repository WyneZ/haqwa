# Golden ambiguity list (written before running Gemini)

Drafted by Claude on the developer's request; the developer must review and
correct the "My expected answer" column before this is used to score Gemini.

Review status: R3 reviewed by Hazel (policy owner) on 2026-09-26.
R1/R2 sections are missing in this file; to be recovered from Wyne.

Event vocabulary (provisional, C2 not locked):
order_created, charged, charge_failed, refunded, cancelled,
shipped, refund_requested, refund_completed
Fields: order_id, customer_id, payment_type, amount, time

Scope key: `in` = expressible with the 4 patterns + reset_after/allow_if.
`out` = a real ambiguity but not solvable in the MVP spec shape.

---

## R3: "A refund must be completed within 24 hours of the request."
Expected parse: `within_time` · after=`refund_requested` · before=`refund_completed` · window=`24h` · per=`order_id`

| # | Ambiguity | Timeline that decides it | My expected answer | Spec effect | Scope |
|---|---|---|---|---|---|
| G3.1 | 24 hours calendar time vs business hours | refund_requested at Fri 5pm → refund_completed Mon 10am (>24h calendar, <24h business) | no — calendar hours (decided 2026-09-26); Fri 5pm → Mon 10am is a violation | `within_time` window is measured in calendar hours | in |
| G3.2 | Multiple refund requests for the same order before any completes | refund_requested → refund_requested → refund_completed | ambiguous — does the completion satisfy the first request, the second, or both? | needs a rule for "which request does a completion resolve" | out (not expressible with per: order_id alone if two requests are in flight) |
| G3.3 | Partial refund completed within 24h, remainder later | refund_requested(amount=100) → refund_completed(amount=40) within 24h → refund_completed(amount=60) later | ambiguous — is a partial completion "completed" for this rule? | needs an amount-aware definition of "completed" | out |
| G3.4 | No refund_completed event at all within the window (silence, not a wrong event) | refund_requested, nothing else, >24h elapses | violation (this is the entire point of within_time — the checker must detect absence, not just a wrong event order) | base rule; confirms `within_time` must be able to fire on absence, evaluated at report-generation time or window-close time | in |
| G3.5 | Cancelling the order after a refund request removes the 24h obligation | refund_requested → cancelled (2h later) → no refund_completed within 24h | ambiguous — owner must decide (added 2026-09-26 from Gemini run v1, Sep 26) | if Yes: `reset_after: cancelled` | in |
