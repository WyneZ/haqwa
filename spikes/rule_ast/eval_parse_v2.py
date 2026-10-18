"""Gate G1 (smoke): score parse_v2 against the golden rule set.

Uses Gemini quota: one request per golden rule (16). Answers are cached in
`.haqwa_cache/` by GeminiClient, so a re-run of the same prompt costs no quota.
A cached answer is NOT a repetition: stability needs fresh calls (`--fresh`).
Two fresh runs, kept apart:
    uv run --env-file .env python spikes/rule_ast/eval_parse_v2.py --fresh --label run3a
    uv run --env-file .env python spikes/rule_ast/eval_parse_v2.py --fresh --label run3b

Run from the repo root:
    uv run python spikes/rule_ast/eval_parse_v2.py --dry-run          # no calls, checks scoring
    uv run --env-file .env python spikes/rule_ast/eval_parse_v2.py    # live

Outcome classes, reported separately (GPT review, 2026-10-16):
  Golden = a rule
    correct   same meaning as the golden answer (after normalising known equivalences)
    wrong     a valid rule with a DIFFERENT meaning. Dangerous: could be sealed.
    refused   Gemini said "unsupported". Safe but a miss.
    invalid   Gemini's answer did not fit the schema (GeminiBadOutput) or failed
              wire/core validation (ParseError). Safe but a miss.
  Golden = UNSUPPORTED
    correct_refusal  Gemini said "unsupported"
    wrong            Gemini produced a rule (an approximation). Dangerous.
    invalid          ParseError. NOT counted as a correct refusal: malformed output is
                     a different failure from recognising unsupported meaning.

G1 bar (smoke gate, provisional):
  wrong == 0, invalid == 0, every UNSUPPORTED case is correct_refusal,
  and supported correct >= 90%.
Every "wrong" must still be checked by hand: the normal form below covers known
equivalences only, not every equivalent shape.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

sys.path.insert(0, str(Path(__file__).parent))

from golden_v2 import GOLDEN, SYSTEMS, UNSUPPORTED  # noqa: E402

from haqwa.ai.client import GeminiBadOutput, GeminiClient, GeminiError  # noqa: E402
from haqwa.ai.parse import ParseError  # noqa: E402
from haqwa.ai.parse_v2 import parse_v2  # noqa: E402
from haqwa.ai.render_v2 import render_rule  # noqa: E402
from haqwa.ai.rule_wire import WireRule, to_rule_v2  # noqa: E402
from haqwa.core.rules_v2 import RuleV2  # noqa: E402

RUNS = Path(__file__).parent / "runs"
SECONDS_BETWEEN_CALLS = 13  # free tier: 5 requests/minute
_DURATION: TypeAdapter[timedelta] = TypeAdapter(timedelta)
_SWAP = {"gt": "lt", "ge": "le"}


# ---- meaning normal form ------------------------------------------------------------


def _value(v: Any) -> str:
    """1000, 1000.0 and "1000" are the same number; other values compare as text."""
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, (int, float)):
        return repr(float(v))
    return str(v)


def _cond(c: Any) -> tuple[Any, ...]:
    if c.op == "in":
        values = sorted({_value(v) for v in c.value})
        if len(values) == 1:  # `in [x]` is `eq x`
            return (c.field, "eq", values[0])
        return (c.field, "in", tuple(values))
    return (c.field, c.op, _value(c.value))


def canon(rule: RuleV2) -> Any:
    """Meaning as a nested tuple. Normalises: node ids, order of all_of children, where,
    exclude and since; `in [x]` == `eq x`; numbers 1000 == 1000.0; count `lt n` == `le n-1`;
    sum_compare `a >= b` == `b <= a`; durations in seconds; all_of with one child."""
    nodes = {n.id: n for n in rule.nodes}

    def select(node_id: str) -> tuple[Any, ...]:
        s = nodes[node_id]
        return (s.event, tuple(sorted(map(_cond, s.where))), tuple(sorted(map(_cond, s.exclude))))

    def check(node_id: str) -> Any:
        n = nodes[node_id]
        if n.type == "all_of":
            kids = sorted((check(c) for c in n.children), key=repr)
            return kids[0] if len(kids) == 1 else ("all_of", tuple(kids))
        if n.type == "count":
            op, value = n.op, n.value
            if op == "lt" and value >= 1:
                op, value = "le", value - 1
            return ("count", select(n.of), op, value, tuple(sorted(n.since)))
        if n.type == "sum_compare":
            left, right, op = (n.left.of, n.left.field), (n.right.of, n.right.field), n.op
            if op in _SWAP:
                left, right, op = right, left, _SWAP[op]
            sides = [(select(left[0]), left[1]), (select(right[0]), right[1])]
            if op in ("eq", "ne"):
                sides.sort(key=repr)
            return ("sum_compare", sides[0], op, sides[1])
        if n.type == "every_followed_within":
            seconds = _DURATION.validate_python(n.within).total_seconds()
            return ("within", select(n.start), select(n.by), seconds, tuple(sorted(n.since)))
        if n.type == "field_compare":
            a, b = sorted([n.a, n.b])  # a != b is b != a
            return ("field_compare", select(n.of), a, n.op, b)
        if n.type == "none_after":
            return ("none_after", select(n.of), select(n.after), tuple(sorted(n.since)))
        if n.type == "every_preceded_by":
            return ("preceded_by", select(n.of), select(n.by), tuple(sorted(n.since)))
        raise ValueError(f"unknown node type {n.type}")

    return (rule.per, check(rule.root))


def expected_rule(gid: str, system: str, text: str, wire: WireRule) -> RuleV2:
    result = to_rule_v2(wire, rule_id=gid, source=text, vocab=SYSTEMS[system])
    assert isinstance(result, RuleV2), f"{gid}: golden answer must be a rule"
    return result


# ---- run ------------------------------------------------------------------------------


class _DryRunSDK:
    """Answers each prompt with the golden answer itself, to test the scoring."""

    def __init__(self) -> None:
        self.models = self
        self.answer = ""

    def generate_content(self, **kwargs: Any) -> Any:
        class R:
            text = self.answer

        return R()


def score(gid: str, system: str, text: str, golden: WireRule | str, client: Any) -> dict:
    row: dict[str, Any] = {"id": gid, "rule": text, "golden": "unsupported"
                           if golden == UNSUPPORTED else "rule"}  # fmt: skip
    try:
        outcome = parse_v2(text, rule_id=gid, vocab=SYSTEMS[system], client=client)
    except ParseError as e:
        return row | {"result": "invalid", "problems": e.problems}
    except GeminiBadOutput as e:  # the answer did not fit the per-vocabulary schema
        return row | {"result": "invalid", "problems": [str(e)[:500]]}
    row["cached"] = outcome.cached
    if golden == UNSUPPORTED:
        if outcome.status == "unsupported":
            return row | {"result": "correct_refusal", "reason": outcome.reason}
        return row | {"result": "wrong", "meaning": outcome.meaning}
    if outcome.status == "unsupported":
        return row | {"result": "refused", "reason": outcome.reason}
    assert outcome.rule is not None and isinstance(golden, WireRule)
    expected = expected_rule(gid, system, text, golden)
    if canon(outcome.rule) == canon(expected):
        return row | {"result": "correct", "meaning": outcome.meaning}
    return row | {
        "result": "wrong",
        "meaning": outcome.meaning,
        "expected_meaning": render_rule(expected),
    }


def gate(rows: list[dict]) -> dict[str, Any]:
    supported = [r for r in rows if r["golden"] == "rule"]
    refusals = [r for r in rows if r["golden"] == "unsupported"]
    correct = sum(r["result"] == "correct" for r in supported)
    report = {
        "supported_correct": f"{correct}/{len(supported)}",
        "refusal_correct": f"{sum(r['result'] == 'correct_refusal' for r in refusals)}"
        f"/{len(refusals)}",
        "wrong": sum(r["result"] == "wrong" for r in rows),
        "invalid": sum(r["result"] == "invalid" for r in rows),
        "refused_supported": sum(r["result"] == "refused" for r in supported),
    }
    report["G1_pass"] = (
        report["wrong"] == 0
        and report["invalid"] == 0
        and all(r["result"] == "correct_refusal" for r in refusals)
        and correct >= 0.9 * len(supported)
    )
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="no Gemini calls")
    ap.add_argument("--fresh", action="store_true", help="ignore the cache (costs quota)")
    ap.add_argument("--label", default="summary", help="result file: runs/g1_<label>.json")
    args = ap.parse_args()

    dry = _DryRunSDK() if args.dry_run else None
    cache = None if (args.dry_run or args.fresh) else Path(".haqwa_cache")
    client = GeminiClient(cache_dir=cache, sdk=dry)

    rows = []
    for gid, system, text, golden in GOLDEN:
        if dry is not None:
            payload = (
                {"unsupported_reason": "golden"}
                if golden == UNSUPPORTED
                else golden.model_dump(exclude_defaults=True)  # type: ignore[union-attr]
            )
            dry.answer = json.dumps(payload)
        try:
            row = score(gid, system, text, golden, client)
        except GeminiError as e:
            sys.exit(f"Gemini error on {gid}: {e}. Finished rows are cached; re-run later.")
        rows.append(row)
        print(json.dumps({"id": gid, "result": row["result"]}))
        if not args.dry_run and not row.get("cached", True):
            time.sleep(SECONDS_BETWEEN_CALLS)

    report = gate(rows)
    print("\nG1:", json.dumps(report))
    if not args.dry_run:
        out = RUNS / f"g1_{args.label}.json"
        RUNS.mkdir(exist_ok=True)
        out.write_text(json.dumps({"gate": report, "rows": rows}, indent=2), encoding="utf-8")
        print(f"details: {out}")


if __name__ == "__main__":
    main()
