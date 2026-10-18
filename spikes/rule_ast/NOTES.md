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

## Gate G1 — parse_v2 accuracy (smoke) · 2026-10-16 · gemini-3.6-flash

Golden set: 16 rules (13 supported, 3 must be refused), `golden_v2.py`, reviewed by Claude
on Hazel's delegation and then by an independent GPT review. Scorer: `eval_parse_v2.py`.
Every run below used fresh Gemini calls (no cache).

| Run | Wire design | Supported correct | Refusals | Wrong | Invalid | Pass |
|---|---|---|---|---|---|---|
| 1 | one node model, all fields optional | 11/13 | 3/3 | 0 | 2 | no |
| 2 | one model per node type, required fields | 12/13 | 3/3 | 0 | 1 | no |
| 3a | + vocabulary enums, `within_seconds` | 13/13 | 3/3 | 0 | 0 | yes |
| 3b | same as 3a, second fresh run | 13/13 | 3/3 | 0 | 0 | yes |

What each failure taught (raw answers in the run files):
- Run 1: Gemini left out a field the node type needs (`by` on every_followed_within, `op` on
  field_compare). Cause: all-optional schema. Fix: anyOf of per-type models with required
  fields, so constrained decoding cannot omit them.
- Run 2: right structure, corrupted strings ("refun d_requested", "P T24H"). Fix: event and
  field names are enums built from the caller's vocabulary (`wire_schema(vocab)`), and
  durations are an integer `within_seconds`; code builds the ISO string.
- In every run, all invalid answers were caught by validation: no wrong rule was produced.
  All three refusal cases (average, one-to-one matching, prompt injection) were refused.

Limits: 16 rules, two fresh passes on the final design. 0 wrong in 32 answers bounds the
wrong rate only below ~9% (95%, one-sided). This is a smoke gate, not a claim that parse
quality equals v1. Enums cannot stop a wrong-but-existing name; the owner's review of the
rendered meaning and the v2 self-test (B4) are the guards for that.
