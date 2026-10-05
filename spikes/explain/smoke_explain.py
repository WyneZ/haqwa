"""Live smoke test: explain the demo double charge with the real Gemini (1 request).

Runs the naive-agent payment-timeout scenario (no Gemini), takes the violation core
found, and asks ai.explain_violation() to explain it. A second run is served from the
cache (0 requests).

Run:  uv run python spikes/explain/smoke_explain.py
Needs GEMINI_API_KEY in .env (never printed).
"""

from __future__ import annotations

import os
from pathlib import Path

from haqwa import format_text, load_spec
from haqwa.ai import GeminiClient, GeminiError, explain_violation
from haqwa.demo import run_scenario

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "examples" / "shop" / "rules.spec.yaml"


def load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        raise SystemExit("No .env file at the repo root.")
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def main() -> None:
    load_env()
    spec = load_spec(SPEC)
    _, report = run_scenario("payment_timeout_naive", spec)
    print(format_text(report))
    print()

    rules = {r.id: r for r in spec.rules}
    client = GeminiClient()
    print(f"model: {client.model}")
    for result in report.results:
        for violation in result.violations:
            try:
                explanation = explain_violation(rules[violation.rule_id], violation, client=client)
            except GeminiError as e:
                raise SystemExit(f"Gemini error: {type(e).__name__}: {e}") from e
            print(f"cached: {explanation.cached} · advisory: {explanation.advisory}")
            print(f"[{violation.rule_id} · {violation.entity}] {explanation.text}")


if __name__ == "__main__":
    main()
