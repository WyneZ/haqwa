# Spike: can Gemini return a recursive rule AST?

Branch: `feat/ai-rule-ast` · Owner: Track A (Hazel) · Started 2026-10-14

**Question:** C1 v2 replaces the 4 patterns with a rule AST (nodes that contain nodes).
Can the Gemini Developer API (API key, free tier) return that shape reliably?
The answer feeds step 0 (AST contract), so it is needed before the contract is locked.

The toy AST in `probe_schema.py` is for this spike only. It is not the contract.

## Shapes compared

| Id | Shape | Recursion |
|---|---|---|
| S1 | `Node.children: list[Node]` | yes |
| S2 | Same AST unrolled to fixed depth 3 (`Top -> Mid -> Leaf`) | no |
| S3 | Flat `nodes: [{id, op, child_ids}]` + `root_id` | no |

## Step 1 — offline probe (0 quota) · 2026-10-14

`uv run python spikes/rule_ast/probe_schema.py` (google-genai 2.25.0, as in `uv.lock`)

**F1. Today's client path silently drops recursion.**
`client.py` sends `response_schema=<Pydantic model>`. The SDK inlines `$defs` and, when it
meets a cycle, replaces it with an empty schema `{}`. Result for S1: `children.items = {}`,
so Gemini gets **no structure at all** for child nodes. No error is raised.
Pydantic would still reject bad output afterwards (`GeminiBadOutput`), but Gemini is not
guided, so we would burn quota on retries.
Source: `google/genai/_transformers.py::process_schema` (`if id(sub_schema) in visited_dicts_path: return {}`).

**F2. A second path exists: `response_json_schema`.**
`GenerateContentConfig.response_json_schema` takes raw JSON Schema with `$defs`/`$ref`.
SDK docstring (2.25.0): "Cyclic references are unrolled to a limited degree and, as such,
may only be used within non-required properties." and "If `$ref` is set on a sub-schema,
no other properties, except for those starting as a `$`, may be set."
The depth of "a limited degree" is **not documented** (unverified) -> needs a live test.
Pydantic's schema for S1 passes both documented limits (checked by `ref_problems`).
Open: Pydantic emits `default: null`, which is not in the documented supported-keys list.

**F3. S2 and S3 work on today's path.** S2 keeps 2 typed child levels; S3 converts cleanly.

## Step 2 — live test · 2026-10-14 · gemini-3.6-flash · 6 requests

`uv run --env-file .env python spikes/rule_ast/live_test.py` (answers in `runs/`)

| Rule | Depth | S1 recursive (`response_json_schema`) | S3 flat (`response_schema`) |
|---|---|---|---|
| r2 count <= 3 | 2 | correct | correct |
| r3 sum <= sum | 2 | correct | correct |
| r4 or/and | 4 | **wrong**: returned only `refunded <= charged` (depth 2), dropped "charged at least once" | **correct meaning**, different form |

**F4. S1 lost meaning on the deep rule.** Valid JSON, passes Pydantic, but half the rule is
gone. Nothing in the output signals it, so only a human or an example check would catch it.
Cause not proven (1 run): it fits the documented "cyclic references are unrolled to a limited
degree", but it may also be the model simplifying.

**F5. S3 kept the full structure.** It wrote `not(count(refunded) > 0)` instead of
`count(refunded) == 0`. Same meaning (a count is never negative); the script's normal form
does not rewrite `not`, so it printed `matches_expected: false`. Checked by hand.
Also: ids were unique, no dangling or unused ids.

**Limits of this evidence:** 1 run per cell, 3 rules, 1 model. Enough to choose a direction,
not to claim reliability.

## Decision input for step 0 (Track A recommendation)

1. **Gemini wire format = S3 flat list** (works on today's `client.py` path, no SDK feature
   whose depth limit is undocumented).
2. **The C1 v2 AST contract can still be a tree.** Wire format and domain model stay separate,
   as with `DataField` in September: Track A converts flat -> tree (`flat_to_tree`) and rejects
   duplicate / unknown / cyclic / unused ids before anything reaches `core/`.
3. Deep rules need a meaning check, not only schema validation: the confirmed-example
   self-test (core) is what catches an F4-type error.
