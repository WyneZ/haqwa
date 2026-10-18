"""Live test: does Gemini return a correct rule AST? S1 (recursive) vs S3 (flat list).

Uses Gemini quota: 3 rules x 2 shapes = 6 requests (free tier: 5/min, 20/day).
Every answer is saved in `spikes/rule_ast/runs/`. A saved answer is reused, so running the
script again costs NO quota. Delete a file in `runs/` only if you want that call again.

Run from the repo root:
    uv run --env-file .env python spikes/rule_ast/live_test.py            # live (6 calls)
    uv run python spikes/rule_ast/live_test.py --dry-run                  # no calls, checks logic

The toy AST here is for this spike only. It is NOT the C1 v2 contract (step 0).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

HERE = Path(__file__).parent
RUNS = HERE / "runs"
MODEL = os.environ.get("HAQWA_MODEL", "gemini-3.6-flash")
SECONDS_BETWEEN_CALLS = 13  # stays under 5 requests/minute

Op = Literal["and", "or", "not", "compare", "count", "sum", "const"]
Cmp = Literal["lt", "le", "eq", "ge", "gt"]

# ---- S1: recursive tree -----------------------------------------------------------------


class Node(BaseModel):
    op: Op
    event: str | None = Field(default=None, description="event name, for count and sum")
    field: str | None = Field(default=None, description="numeric data field, for sum")
    cmp: Cmp | None = Field(default=None, description="comparison, for compare")
    value: float | None = Field(default=None, description="number, for const")
    children: list[Node] = Field(default_factory=list, description="sub-expressions")


class TreeRule(BaseModel):
    per: str = Field(description="entity key field, e.g. 'order_id'")
    check: Node = Field(description="must be true for every entity")


# ---- S3: flat node list with id references ----------------------------------------------


class FlatNode(BaseModel):
    id: str = Field(description="unique id, e.g. 'n1'")
    op: Op
    event: str | None = Field(default=None, description="event name, for count and sum")
    field: str | None = Field(default=None, description="numeric data field, for sum")
    cmp: Cmp | None = Field(default=None, description="comparison, for compare")
    value: float | None = Field(default=None, description="number, for const")
    child_ids: list[str] = Field(default_factory=list, description="ids of sub-expressions")


class FlatRule(BaseModel):
    per: str = Field(description="entity key field, e.g. 'order_id'")
    root_id: str = Field(description="id of the node that must be true for every entity")
    nodes: list[FlatNode]


# ---- test rules and the AST a human expects ---------------------------------------------


def n(op: str, *children: dict[str, Any], **kw: Any) -> dict[str, Any]:
    return {"op": op, **kw, "children": list(children)}


def cnt(event: str) -> dict[str, Any]:
    return n("count", event=event)


def total(event: str) -> dict[str, Any]:
    return n("sum", event=event, field="amount")


def num(v: float) -> dict[str, Any]:
    return n("const", value=v)


RULES: dict[str, tuple[str, dict[str, Any]]] = {
    # depth 2: count vs constant
    "r2_count": (
        "An order can have at most 3 refund requests.",
        n("compare", cnt("refund_requested"), num(3), cmp="le"),
    ),
    # depth 2: sum vs sum
    "r3_sum": (
        "The total refunded amount of an order must not exceed the total charged amount.",
        n("compare", total("refunded"), total("charged"), cmp="le"),
    ),
    # depth 4: tests how far Gemini follows nesting ("unrolled to a limited degree")
    "r4_deep": (
        "If an order is refunded, it must have been charged at least once, and the total "
        "refunded amount must not exceed the total charged amount.",
        n(
            "or",
            n("compare", cnt("refunded"), num(0), cmp="eq"),
            n(
                "and",
                n("compare", cnt("charged"), num(1), cmp="ge"),
                n("compare", total("refunded"), total("charged"), cmp="le"),
            ),
        ),
    ),
}

EVENTS = ["charged", "refunded", "refund_requested", "shipped"]
FIELDS = ["order_id", "amount"]


def prompt_for(rule_text: str, shape: str) -> str:
    shape_text = (
        "Return a tree: each node has `children` (its sub-expressions)."
        if shape == "s1"
        else "Return a flat list of nodes. Give each node a unique `id` ('n1', 'n2', ...). "
        "A node lists its sub-expressions by id in `child_ids`. `root_id` is the top node."
    )
    return f"""Translate a business rule into an expression that must be TRUE for every entity.

Events: {", ".join(EVENTS)}
Data fields: {", ".join(FIELDS)} (entity key: order_id; numeric: amount)

Operators (use only these):
- count(event): number of `event` occurrences for the entity
- sum(event, field): total of numeric `field` over `event` occurrences
- const(value): a number
- compare(cmp, left, right): exactly 2 sub-expressions; cmp is lt, le, eq, ge or gt
- and / or: 2 or more sub-expressions; not: exactly 1

Use only the events and fields listed. Unused properties stay null or empty.
{shape_text}

Rule: "{rule_text}"
"""


# ---- schema for S1 via response_json_schema ---------------------------------------------


def json_schema_for(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic JSON Schema minus `default` (not in the SDK's documented supported keys)."""

    def strip(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: strip(v) for k, v in node.items() if k != "default"}
        if isinstance(node, list):
            return [strip(v) for v in node]
        return node

    return strip(model.model_json_schema())


# ---- Gemini call (with on-disk reuse) ---------------------------------------------------


def call_gemini(prompt: str, shape: str) -> str:
    from google import genai
    from google.genai import errors as genai_errors

    config: dict[str, Any] = {
        "response_mime_type": "application/json",
        "automatic_function_calling": {"disable": True},
    }
    if shape == "s1":
        config["response_json_schema"] = json_schema_for(TreeRule)  # recursive, Path B
    else:
        config["response_schema"] = FlatRule  # today's client.py path

    client = genai.Client()
    for attempt in range(3):
        try:
            response = client.models.generate_content(model=MODEL, contents=prompt, config=config)
            return response.text or ""
        except genai_errors.ClientError as e:
            if e.code == 429:
                sys.exit(f"Quota hit (429). Stop here; saved runs are kept.\n{e}")
            raise
        except genai_errors.ServerError:
            if attempt == 2:
                raise
            time.sleep(4 * (attempt + 1))
    raise RuntimeError("unreachable")


def get_answer(rule_id: str, shape: str, *, dry_run: bool) -> tuple[str, bool]:
    """Return (raw JSON text, came_from_api)."""
    path = RUNS / f"{rule_id}_{shape}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["response"], False
    if dry_run:
        return fake_answer(rule_id, shape), False
    text = call_gemini(prompt_for(RULES[rule_id][0], shape), shape)
    RUNS.mkdir(exist_ok=True)
    entry = {"model": MODEL, "shape": shape, "rule": RULES[rule_id][0], "response": text}
    path.write_text(json.dumps(entry, indent=2), encoding="utf-8")
    return text, True


# ---- checking ---------------------------------------------------------------------------

_FLIP = {"gt": "lt", "ge": "le", "lt": "lt", "le": "le", "eq": "eq"}


def canon(node: dict[str, Any]) -> Any:
    """Normal form so equivalent trees compare equal (a >= b  ==  b <= a; and/or order)."""
    op = node["op"]
    kids = [canon(c) for c in node.get("children", [])]
    if op == "count":
        return ("count", node.get("event"))
    if op == "sum":
        return ("sum", node.get("event"), node.get("field"))
    if op == "const":
        return ("const", float(node.get("value") or 0))
    if op == "compare":
        cmp = node.get("cmp")
        if cmp in ("gt", "ge"):
            kids = list(reversed(kids))
        if cmp == "eq":
            kids = sorted(kids, key=repr)
        return ("compare", _FLIP.get(cmp, cmp), tuple(kids))
    if op in ("and", "or"):
        return (op, tuple(sorted(kids, key=repr)))
    return (op, tuple(kids))


def depth(node: dict[str, Any]) -> int:
    kids = node.get("children", [])
    return 1 + (max(depth(c) for c in kids) if kids else 0)


def flat_to_tree(rule: FlatRule) -> dict[str, Any]:
    """Rebuild the tree from ids. Raises ValueError on duplicate, missing or cyclic ids."""
    by_id = {nd.id: nd for nd in rule.nodes}
    if len(by_id) != len(rule.nodes):
        raise ValueError("duplicate node ids")

    def build(node_id: str, seen: frozenset[str]) -> dict[str, Any]:
        if node_id in seen:
            raise ValueError(f"cycle at {node_id}")
        if node_id not in by_id:
            raise ValueError(f"unknown id {node_id}")
        nd = by_id[node_id]
        data = nd.model_dump(exclude={"id", "child_ids"})
        data["children"] = [build(c, seen | {node_id}) for c in nd.child_ids]
        return data

    tree = build(rule.root_id, frozenset())
    used = {rule.root_id} | {c for nd in rule.nodes for c in nd.child_ids}
    if unused := set(by_id) - used:
        raise ValueError(f"unused nodes {sorted(unused)}")
    return tree


def unknown_names(node: dict[str, Any]) -> list[str]:
    bad = []
    if node.get("event") and node["event"] not in EVENTS:
        bad.append(node["event"])
    if node.get("field") and node["field"] not in FIELDS:
        bad.append(node["field"])
    for c in node.get("children", []):
        bad += unknown_names(c)
    return bad


def check(rule_id: str, shape: str, text: str) -> dict[str, Any]:
    result: dict[str, Any] = {"rule": rule_id, "shape": shape}
    try:
        if shape == "s1":
            parsed = TreeRule.model_validate_json(text)
            tree = parsed.check.model_dump()
        else:
            parsed = FlatRule.model_validate_json(text)
            tree = flat_to_tree(parsed)
    except (ValidationError, ValueError) as e:
        return result | {"valid": False, "error": str(e).splitlines()[0]}
    expected = RULES[rule_id][1]
    return result | {
        "valid": True,
        "per_ok": parsed.per == "order_id",
        "depth": depth(tree),
        "expected_depth": depth(expected),
        "unknown_names": unknown_names(tree),
        "matches_expected": canon(tree) == canon(expected),
    }


# ---- dry run: fake answers built from the expected trees -------------------------------


def fake_answer(rule_id: str, shape: str) -> str:
    tree = RULES[rule_id][1]
    if shape == "s1":
        return json.dumps({"per": "order_id", "check": tree})
    nodes: list[dict[str, Any]] = []

    def add(node: dict[str, Any]) -> str:
        node_id = f"n{len(nodes) + 1}"
        entry = {k: v for k, v in node.items() if k != "children"} | {"id": node_id}
        nodes.append(entry)
        entry["child_ids"] = [add(c) for c in node["children"]]
        return node_id

    root = add(tree)
    return json.dumps({"per": "order_id", "root_id": root, "nodes": nodes})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="no Gemini calls; fake answers")
    args = ap.parse_args()

    rows = []
    for rule_id in RULES:
        for shape in ("s1", "s3"):
            text, from_api = get_answer(rule_id, shape, dry_run=args.dry_run)
            rows.append(check(rule_id, shape, text))
            if from_api:
                time.sleep(SECONDS_BETWEEN_CALLS)

    print(f"model={MODEL}  dry_run={args.dry_run}\n")
    for r in rows:
        print(json.dumps(r))
    if not args.dry_run:
        (RUNS / "summary.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
