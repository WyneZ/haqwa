# Clarify v2 Track A Implementation Plan

**Goal:** Propose validated, typed business-decision patches without applying them.

**Architecture:** Keep provider wire schemas separate from proposal validation. Inject
the example builder and core patch constructors; never implement Track B semantics.

**Spec:** User attachment `862406d9-76ff-4a53-8e08-5c01a99a5210/Pasted text.txt`.

**Constraints:** Stay on `feat/ai-rule-ast`; no commits, pushes, or changes to core,
v1 clarify, CLI, adapters, demo, web, or core tests. English code and documentation.
All automated checks use fake Gemini responses.

## Tasks

- [x] Write failing tests for dynamic schema enums, individual rejection evidence,
  reset/exclude proposals, duplicate/no-op detection, injected examples and core mapping.
- [x] Implement `src/haqwa/ai/_decision_wire.py` for required typed wire models and
  per-rule enum schemas, preserving malformed individual proposals as drop evidence.
- [x] Implement `src/haqwa/ai/clarify_v2.py` for deterministic prompts, validation,
  outcomes, and the isolated `to_core_patches` adapter with injected constructors.
- [x] Add `spikes/clarify_v2/golden_g2.py` and `eval_g2.py`; test dry-run, semantic
  target matching, duplicate handling, fresh mode and report labels without API calls.
- [x] Run focused tests, the full pytest suite, ruff check, format check, and G2 dry-run.

## Review focus

- Invalid individual proposals must not erase valid siblings or disappear from evidence.
- Empty reset-target sets must omit that union branch, never fall back to free strings.
- Exemption values require closed value lists; compare `in` entries individually.
- Exclusion target order and membership order must not defeat duplicate/no-op checks.
- G2's placeholder example proves discovery only, not boundary or patch correctness.

## Open Track B contract

Core patch types, constructors and batch application are intentionally not imported.
The adapter takes constructor callables; Track B must finalize their actual API.
Track B must define restart-on-start semantics (G3.2), example verdict orientation,
and combined-patch interaction checks.

## Execution notes

The supplied implementation request authorizes inline execution of its design.
The existing virtual environment points to a missing Python 3.12 executable.
Use the bundled Python 3.12 runtime with installed project dependencies for checks;
do not recreate the shared virtual environment.

Verification: the full offline suite passed (489 tests, one existing Starlette warning).
The G2 golden dry-run found all six decisions with zero noise and zero drops.
The required full format check still flags existing formatting in
`tests/core/test_check_v2.py` and `tests/test_cli.py`; neither file was changed.
New files pass formatting. No live Gemini calls, commits, or branch changes were made.
The final read-only reviewer found no blocking contract issues; additional regression
tests cover extra keys, invalid input rules, target leakage, and fresh-cache behavior.
