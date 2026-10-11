# HR trace sample

`events.json` contains 85 C2 events for 15 employees in operations, finance and
support. Leave decisions include approvals and rejections; leave types include
annual, sick and unpaid. Three leaves are cancelled. One decision is late (L-15),
and one approval happens after cancellation (L-07). The timesheet rule passes.
No `payroll_run` event occurs, so that rule is reported as NOT TESTED.

`events.map.yaml` declares every observed event plus `payroll_run`. It lets rule
creation consider payroll rules even though this trace never exercises them.

Run `haqwa inspect examples/hr/events.json` to see observed events, then
`haqwa check examples/hr/rules.spec.yaml examples/hr/events.json` to check it.
For rule creation, use `haqwa build RULES --trace examples/hr/events.json
--map examples/hr/events.map.yaml -o SPEC`.

"Approver must differ from requester" is not expressible by the four supported
patterns because it needs a field-to-field comparison. It is expected to show as
unsupported during rule creation.
