# Decision Log

Format: date · decision · decided by · reason

How to add a decision (avoids merge conflicts that already deleted lines twice):
- Add your line at the **end of your own section** (Track A or Track B). Shared decisions go in **Shared**.
- Never delete or rewrite another person's line in a merge. If a decision changes, add a new line that says what it replaces.
- Before merging a PR that touches this file, check the diff has no removed (`-`) decision lines.

## Shared (both developers)

- 2026-09-21 · Hackathon project = policy → executable checks tool (formerly "intentc") · team · fits dev-tool/open-source goals; differentiated clarification loop
- 2026-09-21 · Language: Python · team · agent ecosystem (ADK, AgentProof) is Python
- 2026-09-21 · Multimodal (PDF upload) = stretch goal only · team · not required by rules; core loop first
- 2026-09-21 · Theme: Future of Work & Enterprise Productivity · team · best fit for a workflow/policy tool
- 2026-09-21 · worldkit dropped as main product; AgentProof used for demo faults · team · AgentProof already covers the fault world
- 2026-09-22 · Name: Haqwa (package `haqwa`, CLI `haqwa`) · team · `intentc` collides with pboueri/intentc
- 2026-09-22 · Single package for the hackathon (no `[ai]` extra) · team · check needs no API key anyway; simpler packaging
- 2026-09-22 · Work split = Track A (Meaning Negotiation) / Track B (Verification Engine); owners TBD · team · both developers own a hard problem
- 2026-09-23 · docs/ committed to the public repo as-is; before submission (Oct 18) remove internal sections of brief.md (competitors, judge Q&A, risks, cost, organizer questions) and add a public-facing docs/overview.md · team · repo must be public; keeps one shared source of truth until then
- 2026-09-25 · AGREED · C1: `allow_if` is structured `{field, op, value}` (eq/ne/in), never a string expression · Track A + Track B · no eval, easy for Gemini to fill and for code to validate
- 2026-09-25 · AGREED · C1: confirmed-example timelines are `{event, data}` objects, not `charged(installment)` strings · Track A + Track B · same shape as C2 events; no mini-parser
- 2026-09-25 · AGREED · C1: one Pydantic model per pattern (discriminated union on `pattern`) · Track A + Track B · invalid field combinations fail at load time
- 2026-09-25 · AGREED · C1: unsupported rules are a separate `UnsupportedRule` model; sealed specs hold only supported rules · Track A + Track B · checker never has to skip rules
- 2026-09-25 · AGREED · C2 event format `{event, ts, data, source_id?}` and event map (rule name -> system name(s)) · Track A + Track B · entity keys and conditions live in `data`
- 2026-09-25 · AGREED · `at_most_once` semantics: allow_if events not counted; reset_after resets count to 0; every counted event beyond the first is a violation · Track A + Track B · matches the brief's confirmed examples
- 2026-09-27 · AGREED · The per-pattern canonical examples live in `core/` (Track B owns them) and are shared by core pytest, compile self-test and Track A confirmation cards; Track B keeps separate hand-written edge-case tests · Track A + Track B · one source of truth for pattern semantics
- 2026-09-28 · C3 Web API LOCKED (6 endpoints under /api/v1, RFC 9457 errors + stable code, runs sync now / SSE in week 3). C1, C2, C3 all locked · Hazel + Wyne · Both tracks can build against a fixed interface.
- 2026-09-28 · Gemini: free tier only, no paid billing plan · Hazel + Wyne · Keeps cost at zero; quota limits handled by caching and pacing (see ai/client.py).
- 2026-09-28 · Track owners: Track A = Hazel (ai/, web/, deploy), Track B = Wyne (core/, cli, adapters, demo, tests) · Hazel + Wyne · Confirms the brief's split.
- 2026-09-29 · AGREED · Rule ids: code suggests an id once for a new rule (`core/spec.py` `suggest_rule_id(text, existing_ids)`), the owner may edit it, then it is frozen in the spec and never regenerated · Track A + Track B · ids appear in reports, CI output and spec diffs, so they must be stable; Gemini output varies run to run and text-derived ids change on every edit
- 2026-10-06 · PROPOSED (needs Hazel) · Un-park the `distinguish` gate: `core.compiler.distinguishes(rule, exception, timeline)`; `ai.clarify.decision_questions` drops a Gemini decision question when Yes and No give the same verdict on its timeline (reason recorded in `dropped`) · Wyne · first E2E test: R3 (within_time) questions had no `at`, so a "No" answer made `/runs` fail with compile_failed; the gate stops untestable questions before the owner sees them. Follow-up for Track A: prompt Gemini to add `at` and a closing event for within_time questions so they become testable again

## Track A (Hazel — ai/, web/, deploy)

- 2026-09-26 · Track A: the Gemini wire schema for clarify uses `data: list[{key, value}]` instead of `dict[str, str]`; `ai/parse.py` will convert it to the C1 dict. C1 is unchanged · Track A (Hazel) · Gemini Developer API (API-key mode) rejects the `additionalProperties` that Pydantic emits for dict fields
- 2026-09-27 · Track A: owner "confirmation" questions (core case, event order, per-entity) are generated by a fixed per-pattern code template, not by Gemini; Gemini only asks real decision questions · Track A (Hazel) · they depend only on the pattern, so code is exact, free and stable; v1 scoring showed Gemini never asks them (0/6)
- 2026-09-28 · Logo deferred to week 4 polish (parking list) · Hazel · Not needed for the week 2–3 build; avoids spending time before the core flow works.
- 2026-09-28 · Model: stay on gemini-3.6-flash for everything (dev, demo, evidence). HAQWA_MODEL env override kept for later, default unchanged · Hazel · One model keeps prompt behaviour consistent; quota handled by mocks in tests, disk cache, and spreading live calls across days.
- 2026-09-28 · Track A: clarify parse uses a per-pattern `anyOf` union with C1 field names (clarify_v2); `oneOf` + `discriminator` is rejected client-side by google-genai 2.25.0, `anyOf` is accepted by SDK and server (contracts open Q5) · Track A (Hazel) · no rule loses its second event or window; core/spec.py still validates with its discriminated union
- 2026-09-28 · Wireframe approved: 3 screens (Define / Test / Results), teal theme, plain-language UI for non-technical policy owners, one question at a time · Hazel · Target user is an ops manager, not a developer; fewer choices per screen reduces mistakes.
- 2026-09-29 · Frontend = React + Vite + TypeScript SPA; the build is served as static files by the FastAPI app (one container, one Cloud Run service); types generated from the FastAPI OpenAPI schema · Track A (Hazel) · no SEO/SSR need; keeps FastAPI the only server so web holds no business logic; simplest deploy for Oct 11; components can move to Next.js later if a public site is needed
- 2026-09-29 · Track A: prompt v2.1 noise controls — closed field-value lists in the prompt, no generic "field value exemption" checklist, and code drops any question with an unknown event/field/value · Track A (Hazel) · removed invented values (replacement, store_credit) with no loss of decision questions over 9 runs
- 2026-09-29 · Track A: MVP web API is stateless (browser holds the draft spec); no database; Seal returns `rules.spec.yaml` for download; Firestore moves to the roadmap · Track A (Hazel), to confirm with Track B in the C3 review · brief §9 "no DB at first", §10 multi-user out of scope, principle "the spec is a file"

## Track B (Wyne — core/, cli, adapters, demo)

- 2026-09-30 · Canonical examples live in `core/canonical.py`; rule ids via `suggest_rule_id` in `core/spec.py` · Track B · implements the 2026-09-27 and 2026-09-29 agreements
- 2026-09-30 · Demo scenarios live in `src/haqwa/demo/` (importable by the web API) with deterministic native agents; `agentproof-sim==0.1.1` added to the `dev` group (and `demo`) · Track B · one package for CLI + web; no Gemini quota used by agent runs; ~1 ms per run so `/api/runs` can stay synchronous
- 2026-09-30 · PROPOSED (needs Track A agreement) · C1: optional `at` offset on example timeline items (ISO 8601 duration from the first item) · Track B · `within_time` examples need time; calendar hours make an offset enough
- 2026-09-30 · `never_after` / `must_precede` semantics: allow_if events are ignored; reset events always reset; every violating event is reported; one `requires` enables any number of later events (not consumed) · Track B · simplest reading of "must be preceded by"; change if the business needs one-to-one
- 2026-09-30 · `within_time` semantics: calendar time, on time if exactly at the deadline, next `event` fulfils all open `start`s, reset cancels, end of trace per Q2 option B (PROPOSED) · Track B · owner decision G3.1 (calendar hours); no new Report status
- 2026-10-05 · Track B CLI `build` accepts repeatable `--field` names and defaults to `order_id` for the shop starter · Track B · C2 event maps define event names but have no data-field vocabulary; this keeps the map contract unchanged while allowing other domains
- 2026-10-05 · Archived spikes and contract prose are excluded from Ruff's executable-code checks · Track B · historical spike files have pre-existing lint and formatting failures; CI checks maintained source and tests
- 2026-10-05 · Recorded demo scenarios replay only files named `gemini_YYYY_MM_DD.json`; the native sample remains a test fixture · Track B · the deployed demo can avoid live Gemini calls without mislabeling native effects as a Gemini run
- 2026-10-05 · Recorded scenarios report `expected: unknown` without a spec and derive a verdict through core when given one; malformed recordings use `invalid_recording` · Track B · a recording can pass or violate, and bad effect data must reach the web as a stable error
- 2026-10-05 · FastAPI app (web/api) written by Track B with Track A's agreement; web/frontend stays Track A · Hazel + Wyne · Track B finished early; protects the Oct 11 deployed demo
