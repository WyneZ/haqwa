# Golden ambiguity list (written before running Gemini)

Drafted by Claude on the developer's request; the developer must review and
correct the "My expected answer" column before this is used to score Gemini.

Event vocabulary (provisional, C2 not locked):
order_created, charged, charge_failed, refunded, cancelled,
shipped, refund_requested, refund_completed
Fields: order_id, customer_id, payment_type, amount, time

Scope key: `in` = expressible with the 4 patterns + reset_after/allow_if.
`out` = a real ambiguity but not solvable in the MVP spec shape.

---

## R1: "A customer must not be charged twice for the same order."
Expected parse: `at_most_once` · event=`charged` · per=`order_id`

| # | Ambiguity | Timeline that decides it | My expected answer | Spec effect | Scope |
|---|---|---|---|---|---|
| G1.1 | Charging again after a refund | charged → refunded → charged | not a violation | `reset_after: refunded` | in |
| G1.2 | Installment payments | charged(installment) → charged(installment) | not a violation | `allow_if: payment_type == "installment"` | in |
| G1.3 | Failed charge followed by a retry | charge_failed → charged | not a violation (charge_failed is not "charged") | none needed if event map only counts successful charges | in |
| G1.4 | Two charges with no refund between them | charged → charged | violation | (base rule, no exception) | in |
| G1.5 | "Customer" scope: same customer, two different orders | charged(order=1) → charged(order=2), same customer_id | not a violation (rule is per order_id, not per customer_id) | confirms `per: order_id` is correct, not `per: customer_id` | in |
| G1.6 | Partial refund then re-charge for the remaining amount | charged(amount=100) → refunded(amount=40) → charged(amount=60) | ambiguous — depends on whether "refunded" resets on any refund or only a full refund | needs an amount-aware exception; not expressible with `reset_after` alone | out |

## R2: "A cancelled order must never be shipped."
Expected parse: `never_after` · event=`shipped` · after=`cancelled` · per=`order_id`

| # | Ambiguity | Timeline that decides it | My expected answer | Spec effect | Scope |
|---|---|---|---|---|---|
| G2.1 | Order is re-opened/reinstated after cancellation, then shipped | cancelled → order_created (reinstate) → shipped | not a violation, if a reinstatement event exists | `reset_after: <reinstated>` (needs the event to exist first) | out (no reinstated event in current vocabulary) |
| G2.2 | Shipped, then cancelled afterward | shipped → cancelled | not a violation of this rule (already shipped before cancellation) | base rule already handles this: never_after only checks shipped occurring after cancelled | in |
| G2.3 | Cancelled twice, then shipped | cancelled → cancelled → shipped | violation (any cancelled before a shipped is a violation) | base rule | in |
| G2.4 | Partial shipment (some items) after cancellation | cancelled → shipped(partial) | violation — no reason to treat partial differently without an explicit exception | base rule, unless the team wants an allow_if on shipment type | in |

## R3: "A refund must be completed within 24 hours of the request."
Expected parse: `within_time` · after=`refund_requested` · before=`refund_completed` · window=`24h` · per=`order_id`

| # | Ambiguity | Timeline that decides it | My expected answer | Spec effect | Scope |
|---|---|---|---|---|---|
| G3.1 | 24 hours calendar time vs business hours | refund_requested at Fri 5pm → refund_completed Mon 10am (>24h calendar, <24h business) | ambiguous — needs the team to pick one; assume calendar hours for MVP unless told otherwise | `within_time` window definition must state which clock it uses | in (once decided) |
| G3.2 | Multiple refund requests for the same order before any completes | refund_requested → refund_requested → refund_completed | ambiguous — does the completion satisfy the first request, the second, or both? | needs a rule for "which request does a completion resolve" | out (not expressible with per: order_id alone if two requests are in flight) |
| G3.3 | Partial refund completed within 24h, remainder later | refund_requested(amount=100) → refund_completed(amount=40) within 24h → refund_completed(amount=60) later | ambiguous — is a partial completion "completed" for this rule? | needs an amount-aware definition of "completed" | out |
| G3.4 | No refund_completed event at all within the window (silence, not a wrong event) | refund_requested, nothing else, >24h elapses | violation (this is the entire point of within_time — the checker must detect absence, not just a wrong event order) | base rule; confirms `within_time` must be able to fire on absence, evaluated at report-generation time or window-close time | in |
