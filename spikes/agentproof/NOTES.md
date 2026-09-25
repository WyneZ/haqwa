# Spike notes — AgentProof + ADK (Track B)

## 2026-09-25 — agentproof-sim 0.1.1

Versions on PyPI (checked 2026-09-25): `agentproof-sim` 0.1.1 (only release, Python >=3.11),
`google-adk` 2.9.2. Pin: `agentproof-sim==0.1.1`.

**Result: works.** `spike_double_charge.py` runs a plain-Python naive agent under AgentProof
with `TimeoutAfterCommit(target="charge_payment")`, converts the effect ledger to Haqwa events,
and `haqwa.check` reports `no-double-charge` VIOLATION. Baseline run PASSes. No LLM needed.

Findings:
- Both demo faults exist: `timeout_after_commit` (`mutations.tool_faults.TimeoutAfterCommit`) and
  `duplicate_event` (`mutations.duplication.DuplicateEvent`) — second one not tried yet.
- Effect ledger maps cleanly to C2: `Effect.type -> event`, `.data -> data`, `.id -> source_id`,
  `.committed_at` (virtual-clock float seconds) -> `ts` (anchored to a fixed UTC datetime).
- `RunResult.effects` gives the ledger per run → `adapters/agentproof.py` can be ~20 lines.
- Tools register with `world.tools.register(name, description, input_schema, handler, effect,
  idempotent)`; handlers return `ToolOutcome(value, effects=[{type, data}])`.
- Virtual clock does not advance by itself: all effects had the same timestamp. Fine for
  `at_most_once` (stable sort keeps order); `within_time` demos need `ToolLatency` or explicit
  clock advance.
- **No ADK adapter in 0.1.1** — only `native`, `langchain`, `openai_agents`. For an ADK agent we
  must write our own adapter (pattern: `adapters/openai_agents.py`, 62 lines: wrap
  `world.tools.all()` as framework tools that call `world.tools.invoke`, then run the agent).

## 2026-09-25 — duplicate_event + ADK adapter

Files: `shop.py` (shared virtual shop + effect -> event conversion), `spike_double_charge.py`
(both faults, no LLM), `spike_adk.py` (ADK agent via our own adapter).
Deps pinned in `pyproject.toml` group `demo`: `agentproof-sim==0.1.1`, `google-adk==2.9.2`
(install with `uv sync --group demo`). Adding ADK moved `websockets` 16.1.1 -> 15.0.1.

- **duplicate_event works.** It only affects events on `world.events` (the scheduled event
  queue), and something must call `world.events.deliver_due()`. The shop models this as a
  queued charge request + a naive consumer tool (`process_queue`) that doesn't dedupe by
  message id -> two `charged` effects -> Haqwa VIOLATION. Baseline PASS.
- **ADK adapter written** (`ADKAdapter` in `spike_adk.py`, ~30 lines): wraps shop tools as ADK
  `FunctionTool`s with explicit typed signatures (ADK builds the schema from the signature),
  runs `LlmAgent` via `InMemoryRunner`. Injected tool errors are returned to the model as
  `{"error": ...}` instead of raising, like a real API timeout response.
- **Offline check passes** (`--offline`): imports, tool wrapping and the timeout fault work
  without an LLM; calling charge twice as the model would -> VIOLATION.
- **Live run NOT done**: needs `GEMINI_API_KEY` (read only from the environment). Unverified:
  model name `gemini-3.6-flash` (taken from Track A's spike run file), whether the naive
  instruction makes Gemini actually retry, and how ADK behaves if a tool raises.

Open for week 2 (`adapters/agentproof.py`):
- Generic tool wrapping (build ADK signatures from `input_schema`) vs explicit wrappers per tool.
- Each AgentProof suite runs baseline + each mutation. Each run costs one Gemini request per
  agent step (every tool call + the final answer), not one per run. With a scripted fake model:
  baseline 3 requests, timeout run 4 -> **7 requests per suite run**. Mind free-tier limits;
  cache demo runs. `spike_adk.py` prints a request count (`GeminiRequestCounter`, via ADK
  before/after model callbacks) after every live run.
- ADK pipeline verified end to end with a fake `BaseLlm` (no network): adapter, tool wrapping,
  timeout fault, retry, Haqwa VIOLATION all work. Only the real Gemini behaviour is unverified.

## 2026-09-25 — first live ADK runs (developer's Mac, gemini-3.6-flash, free tier)

- Run 1: baseline PASS (3 requests). Fault run: effects `order_created, charged, charged`
  -> **Gemini did retry after the injected timeout -> real double charge -> Haqwa VIOLATION.**
  The run then died on the final-answer request with **429** (`limit: 5` requests/minute/model,
  free tier, `retryDelay` ~55 s).
- Run 2: baseline PASS, fault run died on its first request with **503** (model overloaded).
  Effects were empty, so the old spike printed PASS — misleading.
- Fixes in the spike: requests paced to one per 13 s (`--min-interval`), google-genai retries
  429/503 with backoff (`HttpRetryOptions`), and a run where the agent crashed without any
  violation now prints `INCONCLUSIVE` instead of PASS. Verified with a fake model.
- Implications: one baseline + one fault run needs ~7 requests ≈ 1.5 min with pacing.
  For the recorded demo and judging, don't depend on live Gemini for the agent: record a good
  run (AgentProof has `replay/`) or use the native agent. `adapters/agentproof.py` (week 2)
  must report "agent error" separately from pass/fail.

## 2026-09-25 — live ADK run with pacing: SUCCESS

- Baseline: PASS, 3 requests. Fault (`timeout_after_commit`): effects
  `order_created, charged, charged` -> Haqwa **VIOLATION**, 4 requests. Total 7, no 429/503.
- Gemini retries the charge after the injected timeout on its own (instruction says "call again
  on error"), so the ADK naive agent reliably fails — at least in the 2 runs that reached it.
- Next (week 2): fixed agent (idempotency key / check before retry) must PASS the same fault;
  move the adapter from spike to `src/haqwa/adapters/agentproof.py` + `demo/`.

## Not done yet
- Repeat live runs a few times to see how stable the naive failure is (n=2 so far).

## Risk / fallback for Oct 5
If the live ADK run is flaky (model doesn't retry, rate limits), the Oct 5 terminal demo uses
the native Python agents in `spike_double_charge.py` (deterministic, no API calls).
