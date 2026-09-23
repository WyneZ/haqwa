# Haqwa — Project Brief v2 (Source of Truth)

Last updated: 2026-09-22. Replaces the earlier "intentc" brief.
Both developers and both Cowork/Claude Code sessions use this file. If anything here conflicts with a task, stop and ask.

---

## 0. What changed from v1

- **Name:** `intentc` → **Haqwa** (package `haqwa`, CLI `haqwa`). Reason: `pboueri/intentc` already exists (a spec-to-code generator with the same name, `src/intentc` layout and `init`/`check`/`build` commands). On 2026-09-22 `haqwa` was free on PyPI and npm, with no GitHub repo of that exact name.
- **Work split:** "Lead vs Partner" → **Track A / Track B** (see §12). Who takes which track is decided by the two developers.
- **Decision rights** updated (§13).
- Added: package decision, self-test mechanics, event sources, language-agnostic use, cost/billing rules, tooling (Cowork vs Claude Code), new competitor entries.

---

## 1. Hackathon context

**Competition:** Google Cloud AI Builder Cup 2026 (organized by Hack2skill, sponsored by Google Cloud), JAPAC. Official site: https://aibuildercup.com

| Date | Event |
|---|---|
| Oct 11, 2026 | Team formation deadline (register earlier) |
| **Oct 18, 2026** | **Prototype submission deadline** |
| Nov 7, 2026 | Shortlist announced |
| Dec 4, 2026 | Grand Finale, Singapore |

Some third-party sites say Oct 4 — ignore; the official site says Oct 18.

**Mandatory:** Gemini/Gemma (or Google agentic platform); deploy on Cloud Run or Firebase; fresh project built during the hackathon; submit deck (PDF), working deployed link, ≤3-min demo video, public GitHub repo, problem statement/theme; everything in English. Multimodal is NOT required.

**Theme:** Future of Work & Enterprise Productivity.

**Judging:** Technical Merit & Gen AI 40% · Problem Alignment & Impact 25% · Innovation & Creativity 25% · UX & Solution Design 10%.

**To confirm with organizers** (Discord / support+aibuildercup@hack2skill.com): dev tool under Future of Work OK; submission page mentions "social challenge" and other categories (likely template leftover); minimum team size; whether Google Cloud credits are provided; shortlist size (unverified reports of Top 200 → Top 50).

**Lesson from a similar past event** (Hack2skill + Google Cloud Gen AI Exchange 2025): ~4,400 prototypes → top 100; professional-track #1 was a test-automation dev tool framed inside a healthcare compliance problem. Execution and demo quality decide. No idea guarantees a shortlist; rough estimate with strong execution ~20–30%.

---

## 2. Product in one line

> **Turn business policies into executable controls for AI-powered workflows.**

Write a policy in plain English → Gemini asks clarifying questions using concrete example timelines → the policy owner answers Yes/No → the confirmed meaning is sealed into a versioned spec → deterministic code checks software and AI-agent behavior against it.

Haqwa never reads or sends application source code. It checks what a system actually did (events).

---

## 3. Problem

- Companies are letting AI agents do refunds, payments and other operations.
- Business policies live in documents; nobody continuously checks that software/agents follow them.
- Translating policies into tests is manual; edge cases get missed (e.g. "is charging again after a refund allowed?").
- Policy owners can't verify the translation because they don't read code.
- Asking an LLM to check logs directly is non-deterministic, costly at scale, and "AI checking AI".

Before: policy doc → developer interprets → tests → edge cases missed → production bug.
After: English policy → Gemini clarifies with examples → owner confirms → executable contract → automatic checks → violation timeline → fix.

---

## 4. Core thesis and design principles

**Policy meaning negotiation:** the human knows the business meaning; Gemini finds and asks about ambiguity; code enforces exactly what was confirmed.

1. **Use AI to interpret, never to decide.** Pass/fail is always deterministic code.
2. **Humans confirm via concrete example timelines** (Yes/No), not formulas or code.
3. **Confirmed meaning is a file** (`rules.spec.yaml`): readable, runnable, versioned in git.
4. **Confirmed examples are self-tests** for the compiled checker.

---

## 5. Target users

| User | Uses Haqwa via | Stage |
|---|---|---|
| Ops/Finance manager (hero user, doesn't code) | Web UI: write policy, answer Yes/No, see reports | Demo + future business |
| AI agent developer | Rules as invariants when fault-testing agents | Hackathon + open source |
| Backend developer | pytest + CI checks | Open source |

Paying-customer hypothesis (unvalidated): ops/compliance teams paying for hosted continuous monitoring.

---

## 6. Core concepts

| Concept | Meaning | Example |
|---|---|---|
| Rule | Plain-English policy line | `A customer must not be charged twice for the same order.` |
| Event map | System event names/fields → rule vocabulary | `charged → PAYMENT_CAPTURED` |
| Pattern | Supported rule shape | `at_most_once` |
| Spec | Human-confirmed meaning (YAML) | `rules.spec.yaml` |
| Checker | Deterministic code compiled from the spec | counts charges per order |
| Report | Violation as an event timeline | "10:00:45 second charge, no refund between" |

**Patterns (MVP, exactly 4):** `at_most_once` · `never_after` · `must_precede` · `within_time`
**Exceptions (MVP, 2):** `reset_after: <event>` · `allow_if: <condition>`

```yaml
- id: no-double-charge
  source: "A customer must not be charged twice for the same order."
  pattern: at_most_once
  event: charged
  per: order_id
  except:
    - reset_after: refunded
    - allow_if: payment_type == "installment"
  confirmed_examples:
    - { timeline: [charged, refunded, charged], violation: false }
    - { timeline: [charged(installment), charged(installment)], violation: false }
    - { timeline: [charged, charged], violation: true }
```

---

## 7. Flows

**Flow 1 — Define (only flow using AI; runs when rules change)**
rules file → Gemini parse (pattern/event/entity, structured JSON) → validate (supported pattern? event in map? if not: "not supported yet") → Gemini finds ambiguities → example timelines → owner answers Yes/No (repeat if new ambiguity) → owner seals/locks → `rules.spec.yaml` committed.

**Flow 2 — Compile + self-test (no AI)**
spec → checker template by pattern → add exceptions → self-test: each confirmed example timeline is turned into a synthetic event list (synthetic entity id, increasing timestamps), run in memory, and the checker's verdict must equal the human's answer. Any mismatch → compile fails and shows the example. This catches Gemini parse errors (e.g. a missing `reset_after`) and compiler/checker bugs. No test files are generated (pytest export is a stretch goal).

**Flow 3 — Check (no AI in the verdict)**
events → event-map translation → sort by time, group by entity → run rules → PASS or VIOLATION timeline → optional Gemini explanation (advisory only).

**Flow 4 — Rule change**
edit rules → diff with previous spec → re-run Flow 1 only for changed rules → spec diff reviewed in git.

**Demo journey (web):** owner writes 3 rules → Yes/No cards ("AI interviews the policy owner") → Seal → run agent with payment-timeout fault → red `no-double-charge` with timeline + explanation → fix agent → re-run → green.

---

## 8. Events: where they come from

Haqwa reads events, never code.

| Source | Developer effort | Example |
|---|---|---|
| Existing records | none | audit tables, status history, webhook logs |
| Framework auto-capture | setup only | AgentProof effect ledger via adapter (**hackathon demo**) |
| Developer instrumentation | add `emit()` calls | systems without records |

Limits: events that aren't emitted can't be checked; wrong events → wrong verdicts. Event sourcing is the main adoption friction (roadmap: ADK callback, OpenTelemetry, DB importer adapters).

**Language-agnostic:** rule/spec/event files are text/YAML/JSON and the CLI runs in any CI, so any language's system can be checked if it emits JSON events. `import`, `emit()` and adapters are Python-only for now.

**Large codebases:** Haqwa checks key policies, not all logic. Split rules by domain (`payments`, `orders`), event maps per service, start with the 10–20 "must never happen" rules. Gemini's questions come from rule text + event vocabulary + event-log samples.

---

## 9. Architecture

```
Web UI + FastAPI (Cloud Run)   <- ops manager, judges
CLI  (haqwa init/build/check)  <- developers
Library haqwa (src/haqwa/)     <- the product
  ai/    Gemini: client, parse, clarify, explain       (uses Gemini)
  core/  spec, events, compiler, checker, report      (no AI)
  adapters/ pytest, agentproof
demo/  Google ADK agent (naive + fixed) + AgentProof faults
```

**Rules:** the library is the product; web and CLI contain no business logic. `core/` never imports `ai/`. Pass/fail is decided only by `core/`.

**Gemini usage:** `build` (parse + clarify), event-map suggestion (bonus), violation explanation (advisory), demo agent. Not used in compile or check → CI needs no API key.

**Package:** single package for the hackathon (`pip install haqwa`); may split into `haqwa[ai]` later. API key from `GEMINI_API_KEY` env; all Gemini calls in `ai/client.py`; `google-genai` supports AI Studio keys and Vertex AI. Provider interface (for other LLMs later): open decision.

### Repo layout
```
haqwa/
├── pyproject.toml
├── CLAUDE.md
├── src/haqwa/
│   ├── core/      spec.py, events.py, compiler.py, checker.py, report.py
│   ├── ai/        client.py, parse.py, clarify.py, explain.py
│   ├── adapters/  pytest.py, agentproof.py
│   └── cli.py
├── web/           FastAPI + frontend
├── demo/          ADK agent (naive + fixed) + AgentProof scenarios
├── examples/      rules file, events.map.yaml, events.json
├── docs/          brief.md (this file), decisions.md, contracts.md
└── tests/
```

### Tech stack
Python 3.11+ · uv + pyproject · Pydantic · Gemini via `google-genai` (structured output; Flash vs Pro chosen in spike) · ruamel.yaml/PyYAML · Typer + Rich · pytest · Google ADK (Python) · `agentproof-sim` (pinned; alpha, released 2026-09-03) · FastAPI · frontend TBD (Track A owner) · no DB at first (Firestore only if needed) · Cloud Run + Secret Manager · GitHub Actions.

---

## 10. MVP scope (frozen)

**In:** 4 patterns + 2 exceptions · Gemini parse + clarification loop + explain · compiler + self-test + checker + timeline report · CLI `init`/`build`/`check` · pytest helper · AgentProof adapter + ADK agent (naive fails, fixed passes) · 2 faults (`timeout_after_commit`, `duplicate_event`) · Web UI 3 screens (policy + Yes/No cards · run agent · report) · Cloud Run deploy.

**Stretch (week 4 only if time):** policy PDF/screenshot upload (Track A) · pytest export of confirmed examples (Track B).

**Out (roadmap):** CI packaging, production monitoring/hosted service, more patterns/adapters, multi-user/auth, policy coverage report, `emit()` helpers for other languages.

**Open:** include a small Python `emit()` helper in MVP? (decide together)

---

## 11. Demo (≤3 min) and evidence

| Time | Show |
|---|---|
| 0:00–0:30 | "AI agents now move money. Who checks they follow company policy?" |
| 0:30–1:15 | Owner writes policy → Gemini asks with example timelines → Yes/No → sealed |
| 1:15–2:00 | Agent + payment timeout (after commit) → double charge caught → timeline + explanation |
| 2:00–2:30 | Fix agent → re-run → pass |
| 2:30–3:00 | Evidence: Gemini-direct ×10 vs Haqwa ×10 · CLI · roadmap |

Evidence experiment (spike week): run Gemini directly on a log with a double charge 10 times; run the Haqwa checker 10 times; compare catch rate, time, cost. Report real results. Keep a naive agent that reliably fails.

---

## 12. Work split: Track A / Track B

| | Track A: Meaning Negotiation | Track B: Verification Engine |
|---|---|---|
| Owns | `ai/`, `web/` (UI + FastAPI), evidence experiment, deploy (suggested) | `core/`, `cli.py`, `adapters/`, `demo/` |
| Hardest part | prompts, structured output, question quality, clarification UX | pattern semantics, exceptions, time windows, self-test, AgentProof integration |

Contracts (lock in week 1, stored in `docs/contracts.md`):
- **C1 Spec model** (`core/spec.py`): designed together, coded by Track B.
- **C2 Event format** (`core/events.py`): Track B, reviewed by Track A.
- **C3 Web API** (`web/`): designed together, coded by Track A.

Parallel work: Track B ships `compile()`/`check()` stubs right after contracts lock; Track A builds UI against stubs. Track B tests with hand-written YAML specs. Only direct dependency: CLI `build` (B) calls `ai/parse` + `ai/clarify` (A) in week 3.

| Week | Track A | Track B |
|---|---|---|
| 1 (Sep 22–28) | Gemini clarification spike; evidence experiment; co-design C1/C3; pick frontend; wireframe | co-design C1; write `core/spec.py`; C2; `at_most_once` + tests; ADK + AgentProof spike; stubs |
| 2 (Sep 29–Oct 5) | `ai/parse` + `ai/clarify`; FastAPI skeleton; UI screen 1 | 4 patterns + 2 exceptions; compiler + self-test; report; pytest helper; naive + fixed agent; AgentProof adapter |
| **Checkpoint Oct 5** | real checker + AgentProof adapter catch the double charge in the terminal | |
| 3 (Oct 6–11) | `ai/explain`; UI screens 2–3; wire FastAPI to library; Cloud Run deploy | CLI; connect `build` to ai; 2 fault scenarios; more edge-case tests |
| **Checkpoint Oct 11** | full demo flow works on the deployed link; team registered | |
| 4 (Oct 12–18) | polish; stretch PDF upload; video + deck (both) | bug fixes; README; stretch pytest export; video + deck (both) |

Shared: deck, video, submission, README (B library / A web section), organizer questions, cross-track code review. If a checkpoint slips, cut scope (e.g. drop `within_time` or stretch goals).

---

## 13. Decision rights

| Decision | Who |
|---|---|
| Inside a track (technical) | Track owner |
| Contracts C1/C2/C3 | Both must agree |
| Scope, product direction | Discussed by both; project lead decides |

Every decision gets a dated line in `docs/decisions.md`.

---

## 14. Competitive landscape (describe accurately; no absolute claims)

| Tool | What it does | Relation |
|---|---|---|
| AgentProof (`agentproof-sim`) | Python simulated world, virtual clock, fault mutations, replay, CI; invariants in Python | We use it for demo faults |
| evanl666/agentproof | NL behavior specs → tests/policy code, imports Google ADK | NL → checks exists |
| agent-proof.dev | NL promises → executable contracts (commercial beta) | Same |
| pboueri/intentc | Specs → generated code via Claude Code, with validations | Different goal (code generation); reason for rename |
| τ-bench | Agent tasks graded by final DB state | Not policy clarification |
| nl2spec (research) | NL → temporal logic, fix sub-formulas | For verification engineers |
| Asking an LLM directly | Ad-hoc log checks/tests | Non-deterministic; AI picks meaning |

**Differentiation (narrow — prove it through UX):** among tools we checked, none resolves policy ambiguity by showing the owner concrete example timelines, stores answers as confirmed examples, and uses them to self-test a deterministic checker.

Positioning: "Tools like AgentProof let developers fault-test agents with invariants they write. Haqwa lets the policy owner state rules in plain English, resolve their meaning through examples, and turn them into checks."

---

## 15. Judge Q&A

- **Why not ask AI to check?** Varies run to run, costs per check, AI checking AI. Haqwa uses AI once to settle meaning, then code checks every time. Show ×10 evidence.
- **Why not have an AI coding tool write tests?** It silently picks an interpretation and buries it in code; owners can't verify; meanings drift across files.
- **Future of Work fit?** Removes the policy → code translation loop and makes AI workflows safe to run.
- **Isn't this AgentProof?** AgentProof provides the fault world; we integrate. Our focus is the owner side: clarifying and sealing meaning.
- **Large codebases?** Key policies, not all logic; events, not code; domain-split rules.
- **Honest weakness:** thin moat; long-term value is the spec format, engine quality and integrations.

---

## 16. Risks

| Risk | Mitigation |
|---|---|
| Clarification questions not useful | Test first in the spike |
| AgentProof alpha changes | Pin version; core stays framework-agnostic |
| Agent handles the fault in demo | Keep naive failing agent |
| Scope creep | Freeze scope; parking lot |
| Weak problem alignment | Ops manager hero; money-loss scenario |
| Event sourcing friction | Demo controls format; adapters on roadmap |
| Free-tier rate limits during judging | Cache demo Gemini results; clear retry message |

---

## 17. Cost and accounts

- Gemini: AI Studio key, free tier (Flash models reported as free-tier only since May 2026 — verify). Free-tier inputs may be used by Google → synthetic data only.
- Cloud Run: monthly free tier, but a billing account (card) is required. New accounts get a $300 / 90-day free trial.
- Rules: don't upgrade to a paid account during the hackathon; set a $5 budget alert (alerts don't stop spending); Cloud Run min instances = 0; start the trial around week 3; keep services up until after Dec 4; then shut down and close billing.
- Check early whether your card works; if not, ask organizers about credits.

---

## 18. Tooling

- **Claude Code** for code (repo, tests, CI, deploy) — reads `CLAUDE.md`.
- **Cowork** for documents, deck, research, demo script — each developer runs their own Cowork with the shared instructions + their track file.
- Work in small, test-backed tasks; review diffs; commit often.

---

## 19. Open items

- [ ] Who takes Track A / Track B; deploy owner; frontend framework
- [ ] Lock C1/C2/C3 in `docs/contracts.md` (week 1)
- [ ] Organizer questions (§1)
- [ ] Gemini model choice after spike
- [ ] Pin AgentProof version; confirm ADK + AgentProof integration
- [ ] Reserve `haqwa` on GitHub + PyPI placeholder; check domain, YouTube, Devpost
- [ ] `emit()` helper in MVP? · provider interface now?
