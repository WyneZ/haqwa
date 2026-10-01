"""Evidence experiment (brief §11): Gemini-direct x10 vs Haqwa x10 on the same event log.

Question: given the SAME sealed policy, does asking Gemini directly find the right
violations as reliably as Haqwa's deterministic checker?

Fair setup (decided 2026-10-01): Gemini gets everything Haqwa knows:
- the rule text,
- the owner's decisions (the spec's exceptions, in plain English),
- the event map (system name -> rule event name),
- the full event log (spikes/evidence/log.json: 12 orders, 37 events).
The log mixes 2 real double charges (A-2, A-8) with look-alikes the owner allowed
(refund then charge, installments, card + installment, failed payment).

Ground truth = Haqwa's report. Each Gemini run is scored against it:
caught (true positives), missed, false alarms, exact match, time, tokens.
Gemini runs are NOT cached (each run is a fresh call) and paced for the free tier.

Run (repo root):
    uv run python spikes/evidence/run_evidence.py               # 10 Gemini + 10 Haqwa runs
    uv run python spikes/evidence/run_evidence.py --start 4     # resume Gemini at run 4
    uv run python spikes/evidence/run_evidence.py --haqwa-only  # no quota used
    uv run python spikes/evidence/run_evidence.py --summary     # re-print results only
Outputs: spikes/evidence/results/gemini_run<n>.json, haqwa.json, summary.md
Needs GEMINI_API_KEY in .env (never printed).
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path

from pydantic import BaseModel, Field

from haqwa import check, compile_spec, load_event_map, load_events, load_spec
from haqwa.ai import GeminiClient, GeminiError
from haqwa.core.spec import AllowIf, ResetAfter

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SPEC = ROOT / "examples" / "shop" / "rules.spec.yaml"
EVENT_MAP = ROOT / "examples" / "shop" / "events.map.yaml"
LOG = HERE / "log.json"
OUT = HERE / "results"

RUNS = 10
PACE_SECONDS = 13  # free tier: 5 requests per minute


# ---- Gemini answer format ---------------------------------------------------------------


class FoundViolation(BaseModel):
    order_id: str = Field(description="the order_id that breaks the policy")
    explanation: str = Field(description="one sentence: which events break it and why")


class GeminiVerdict(BaseModel):
    violations: list[FoundViolation] = Field(
        description="every order that breaks the policy; empty list if none"
    )


# ---- prompt -------------------------------------------------------------------------------


def owner_decisions(spec_rule) -> list[str]:  # noqa: ANN001
    """The sealed spec's exceptions in plain English (what the owner decided)."""
    lines = []
    for exc in spec_rule.exceptions:
        if isinstance(exc, ResetAfter):
            lines.append(
                f"After a '{exc.reset_after}' event, the {spec_rule.per} starts fresh: "
                f"earlier '{spec_rule.event}' events no longer count."
            )
        elif isinstance(exc, AllowIf):
            c = exc.allow_if
            lines.append(
                f"'{spec_rule.event}' events where {c.field} {c.op} {c.value!r} are allowed "
                f"and do not count."
            )
    return lines


def build_prompt(spec, event_map_text: str, log_text: str) -> str:  # noqa: ANN001
    rule = spec.rules[0]
    decisions = "\n".join(f"- {d}" for d in owner_decisions(rule))
    return f"""You are auditing an event log against a company policy.

Policy: "{rule.source}"
The policy applies per {rule.per}.

The policy owner has decided:
{decisions}

Event map (system event name -> policy event name; other events are irrelevant):
{event_map_text}

Event log (JSON, one event per line):
{log_text}

List every {rule.per} that breaks the policy, with a one-sentence explanation.
If no order breaks it, return an empty list."""


# ---- runs ---------------------------------------------------------------------------------


def ground_truth() -> tuple[set[str], float]:
    """Haqwa's verdict and the time of one compile + check (ms)."""
    spec, event_map = load_spec(SPEC), load_event_map(EVENT_MAP)
    events = load_events(LOG)
    start = time.perf_counter()
    report = check(compile_spec(spec, event_map), events, event_map)
    ms = (time.perf_counter() - start) * 1000
    return {v.entity for r in report.results for v in r.violations}, ms


def run_haqwa(truth: set[str]) -> dict:
    times = []
    for _ in range(RUNS):
        found, ms = ground_truth()
        assert found == truth  # deterministic: same answer every time
        times.append(ms)
    result = {"runs": RUNS, "found": sorted(truth), "exact_runs": RUNS, "ms": times}
    (OUT / "haqwa.json").write_text(json.dumps(result, indent=2))
    return result


def score(found: set[str], truth: set[str]) -> dict:
    return {
        "found": sorted(found),
        "caught": sorted(found & truth),
        "missed": sorted(truth - found),
        "false_alarms": sorted(found - truth),
        "exact": found == truth,
    }


def run_gemini(truth: set[str], start: int) -> None:
    load_env()
    spec = load_spec(SPEC)
    prompt = build_prompt(spec, EVENT_MAP.read_text(encoding="utf-8"), LOG.read_text("utf-8"))
    client = GeminiClient(cache_dir=None)  # no cache: every run is a fresh Gemini call
    print(f"model: {client.model} · runs {start}..{RUNS}")
    for n in range(start, RUNS + 1):
        if n > start:
            time.sleep(PACE_SECONDS)
        t0 = time.perf_counter()
        try:
            result = client.generate(prompt, GeminiVerdict)
        except GeminiError as e:
            print(f"run {n}: stopped: {type(e).__name__}: {e}")
            print(f"resume later with: --start {n}")
            return
        seconds = time.perf_counter() - t0
        found = {v.order_id for v in result.value.violations}
        record = {
            "run": n,
            "model": result.model,
            "seconds": round(seconds, 2),
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            **score(found, truth),
            "raw": result.value.model_dump(),
        }
        (OUT / f"gemini_run{n}.json").write_text(json.dumps(record, indent=2))
        mark = "EXACT" if record["exact"] else "WRONG"
        print(
            f"run {n}: {mark} found={record['found']} missed={record['missed']} "
            f"false_alarms={record['false_alarms']} {seconds:.1f}s"
        )


def summary(truth: set[str]) -> str:
    runs = [json.loads(p.read_text()) for p in sorted(OUT.glob("gemini_run*.json"))]
    haqwa = json.loads((OUT / "haqwa.json").read_text())
    n = len(runs)
    if n == 0:
        return "No Gemini runs yet."
    exact = sum(r["exact"] for r in runs)
    caught = sum(len(r["caught"]) for r in runs)
    alarms = sum(len(r["false_alarms"]) for r in runs)
    secs = [r["seconds"] for r in runs]
    tokens_in = [r["input_tokens"] for r in runs if r["input_tokens"]]
    tokens_out = [r["output_tokens"] for r in runs if r["output_tokens"]]
    alarm_orders = sorted({o for r in runs for o in r["false_alarms"]})
    missed_orders = sorted({o for r in runs for o in r["missed"]})
    lines = [
        "# Evidence: Gemini-direct vs Haqwa",
        "",
        f"Log: {LOG.name} (12 orders, 37 events). Real violations: {', '.join(sorted(truth))}.",
        f"Gemini model: {runs[0]['model']}. Gemini got the rule, the owner's decisions, the "
        "event map and the full log.",
        "",
        "| | Gemini direct | Haqwa checker |",
        "|---|---|---|",
        f"| Runs | {n} | {haqwa['runs']} |",
        f"| Exactly right (all violations, no false alarms) | {exact}/{n} | "
        f"{haqwa['exact_runs']}/{haqwa['runs']} |",
        f"| Violations caught | {caught}/{n * len(truth)} | "
        f"{haqwa['runs'] * len(truth)}/{haqwa['runs'] * len(truth)} |",
        f"| False alarms (allowed orders flagged) | {alarms} | 0 |",
        f"| Time per run (median) | {statistics.median(secs):.1f} s | "
        f"{statistics.median(haqwa['ms']):.1f} ms |",
        f"| Tokens per run (median, in / out) | "
        f"{statistics.median(tokens_in) if tokens_in else 'n/a'} / "
        f"{statistics.median(tokens_out) if tokens_out else 'n/a'} | 0 / 0 |",
        "| Same answer every run | "
        f"{'yes' if len({tuple(r['found']) for r in runs}) == 1 else 'no'} | yes |",
        "",
        f"Orders Gemini flagged wrongly at least once: {', '.join(alarm_orders) or 'none'}.",
        f"Real violations Gemini missed at least once: {', '.join(missed_orders) or 'none'}.",
    ]
    text = "\n".join(lines) + "\n"
    (OUT / "summary.md").write_text(text, encoding="utf-8")
    return text


def load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        raise SystemExit("No .env file at the repo root.")
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def main(argv: list[str]) -> None:
    OUT.mkdir(exist_ok=True)
    truth, _ = ground_truth()
    print(f"Haqwa ground truth: {sorted(truth)}")
    if "--summary" not in argv:
        run_haqwa(truth)
        if "--haqwa-only" not in argv:
            start = int(argv[argv.index("--start") + 1]) if "--start" in argv else 1
            run_gemini(truth, start)
    print()
    print(summary(truth))


if __name__ == "__main__":
    main(sys.argv[1:])
