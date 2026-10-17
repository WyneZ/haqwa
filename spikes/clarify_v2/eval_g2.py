"""G2 gate: parse -> typed business decisions, each with core's separating example.

Run from the repository root:
    uv run python spikes/clarify_v2/eval_g2.py --dry-run
    uv run --env-file .env python spikes/clarify_v2/eval_g2.py --fresh-clarify --label run4a

`--fresh` bypasses the cache for every Gemini call. `--fresh-clarify` reuses cached parse
answers (parse is gated by G1) and asks Gemini fresh only for decisions: 3 calls per run.
Examples come from core `make_example_v2`; a decision without one is dropped (not found).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# Support direct script execution and import by the offline tests.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from haqwa.ai.clarify_v2 import (  # noqa: E402
    AddReset,
    Decision,
    Patch,
    propose_decisions,
)
from haqwa.ai.client import GeminiClient, GeminiError  # noqa: E402
from haqwa.ai.core_v2_ports import core_ports  # noqa: E402
from haqwa.ai.parse import ParseError  # noqa: E402
from haqwa.ai.parse_v2 import parse_v2  # noqa: E402
from haqwa.ai.rule_wire import to_rule_v2  # noqa: E402
from haqwa.core.rules_v2 import RuleV2  # noqa: E402
from spikes.clarify_v2.golden_g2 import (  # noqa: E402
    EXPECTED_IDS,
    RULES,
    SHOP,
    expected_patches,
)

RUNS = Path(__file__).resolve().parent / "runs"
EXAMPLE_BUILDER = "core make_example_v2 (separating witness; no example -> decision dropped)"


def _patch_key(patch: Patch) -> tuple:
    if isinstance(patch, AddReset):
        return patch.op, patch.node_id, patch.event
    condition = patch.condition
    values = condition.values if condition.op == "in" else [condition.value]
    values = tuple(sorted(set(values)))
    op = "eq" if condition.op == "in" and len(values) == 1 else condition.op
    return patch.op, tuple(sorted(patch.select_ids)), condition.field, op, values


def score_decisions(rule_id: str, rule: RuleV2, decisions: list[Decision]) -> dict[str, Any]:
    """Match exact typed patch meaning, including every target, without comparing prose."""
    expected = {_patch_key(p): gid for gid, p in expected_patches(rule_id, rule).items()}
    found: set[str] = set()
    noise: list[dict[str, Any]] = []
    for decision in decisions:
        if gid := expected.get(_patch_key(decision.patch)):
            found.add(gid)
        else:
            noise.append(decision.model_dump(mode="json"))
    return {
        "found": sorted(found),
        "missing": sorted(set(EXPECTED_IDS[rule_id]) - found),
        "noise": noise,
    }


class _DryRunSDK:
    def __init__(self) -> None:
        self.models = self
        self.answers: list[dict[str, Any]] = []

    def generate_content(self, **kwargs: Any) -> Any:
        class Response:
            text = json.dumps(self.answers.pop(0))

        return Response()


def _dry_answers(rule_id: str) -> list[dict[str, Any]]:
    text, wire = RULES[rule_id]
    rule = to_rule_v2(wire, rule_id=rule_id.lower(), source=text, vocab=SHOP)
    assert isinstance(rule, RuleV2)
    decisions = [
        {
            "id": gid,
            "question": "Should this business exception be allowed?",
            "why": "Golden dry-run proposal; no model quality is being measured.",
            "patch": patch.model_dump(),
        }
        for gid, patch in expected_patches(rule_id, rule).items()
    ]
    return [wire.model_dump(exclude_defaults=True), {"decisions": decisions}]


def main(argv: list[str] | None = None) -> int:
    """Run G2, print discovery evidence and optionally save a labelled JSON report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="golden FakeSDK, no quota")
    parser.add_argument("--fresh", action="store_true", help="bypass the application cache")
    parser.add_argument(
        "--fresh-clarify",
        action="store_true",
        help="reuse cached parse answers; ask Gemini fresh only for decisions",
    )
    parser.add_argument("--label", help="save runs/g2_<label>.json")
    args = parser.parse_args(argv)
    if args.label and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", args.label):
        parser.error("label must be 1-64 letters, digits, underscores or hyphens")
    dry = _DryRunSDK() if args.dry_run else None
    client = GeminiClient(
        model="g2-dry-run" if dry else None,
        sdk=dry,
        cache_dir=None if args.fresh or dry else Path(".haqwa_cache"),
    )
    # Same SDK and model; only the cache differs, so decisions are sampled fresh.
    clarify_client = (
        GeminiClient(model=client.model, sdk=dry, cache_dir=None)
        if args.fresh_clarify and not dry
        else client
    )
    ports = core_ports()
    rows = []
    for rule_id, (text, _) in RULES.items():
        if dry:
            dry.answers = _dry_answers(rule_id)
        row: dict[str, Any] = {
            "id": rule_id,
            "source": text,
            "expected": EXPECTED_IDS[rule_id],
            "found": [],
            "missing": EXPECTED_IDS[rule_id],
            "noise": [],
            "dropped": [],
        }
        try:
            parsed = parse_v2(text, rule_id=rule_id.lower(), vocab=SHOP, client=client)
            row["parse_cached"] = parsed.cached
            if parsed.rule is None:
                raise ValueError(f"parse refused: {parsed.reason}")
            outcome = propose_decisions(
                parsed.rule,
                vocab=SHOP,
                client=clarify_client,
                make_example=ports.make_example,
            )
            row.update(
                {
                    "meaning": outcome.meaning,
                    "clarify_cached": outcome.cached,
                    "decisions": [d.model_dump(mode="json") for d in outcome.decisions],
                    "dropped": [d.model_dump() for d in outcome.dropped],
                }
            )
            row.update(score_decisions(rule_id, parsed.rule, outcome.decisions))
        except (GeminiError, ParseError, ValueError) as exc:
            row["error"] = str(exc)
        rows.append(row)
    found = sum(len(r["found"]) for r in rows)
    noise = sum(len(r["noise"]) for r in rows)
    errors = sum("error" in r for r in rows)
    report = {
        "gate": "G2",
        "dry_run": args.dry_run,
        "fresh": args.fresh,
        "fresh_clarify": args.fresh_clarify,
        "model": client.model,
        "example_builder": EXAMPLE_BUILDER,
        "limitations": [
            "Discovery smoke gate only; dry-run tests plumbing, not Gemini quality.",
            "Question wording and its consistency with the patch require human review.",
        ],
        "found": found,
        "expected": 6,
        "recall": found / 6,
        "noise": noise,
        "dropped": sum(len(r["dropped"]) for r in rows),
        "errors": errors,
        "passed": found == 6 and noise == 0 and errors == 0,
        "rules": rows,
    }
    print(json.dumps(report, indent=2))
    if args.label:
        RUNS.mkdir(parents=True, exist_ok=True)
        path = RUNS / f"g2_{args.label}.json"
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"Report: {path}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
