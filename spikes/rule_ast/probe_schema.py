"""Offline probe: how does google-genai send a recursive rule AST to Gemini?

Uses NO Gemini quota. It runs only the SDK's local schema conversion, the same step
that raised the `additionalProperties` error in September (before any API call).

Run:  uv run python spikes/rule_ast/probe_schema.py

The toy AST below is for this spike only. It is NOT the C1 v2 contract (step 0).
"""

from __future__ import annotations

import json
from typing import Any, Literal

from google.genai import _transformers as t
from pydantic import BaseModel, Field

# ---- S1: recursive toy AST --------------------------------------------------------------

Op = Literal["and", "or", "not", "compare", "count", "sum", "const"]


class Node(BaseModel):
    """One AST node. `children` points back to Node, so the schema is recursive."""

    op: Op
    event: str | None = Field(default=None, description="event name for count/sum")
    field: str | None = Field(default=None, description="data field for sum")
    cmp: Literal["lt", "le", "eq", "ge", "gt"] | None = None
    value: float | None = Field(default=None, description="number for const")
    children: list[Node] = Field(default_factory=list, description="sub-expressions")


class RecursiveRule(BaseModel):
    root: Node


# ---- S2: same AST unrolled to a fixed depth of 3 (no recursion) ------------------------


class Leaf(BaseModel):
    op: Literal["count", "sum", "const"]
    event: str | None = None
    field: str | None = None
    value: float | None = None


class Mid(BaseModel):
    op: Op
    event: str | None = None
    field: str | None = None
    cmp: Literal["lt", "le", "eq", "ge", "gt"] | None = None
    value: float | None = None
    children: list[Leaf] = Field(default_factory=list)


class Top(BaseModel):
    op: Op
    cmp: Literal["lt", "le", "eq", "ge", "gt"] | None = None
    children: list[Mid] = Field(default_factory=list)


class UnrolledRule(BaseModel):
    root: Top


# ---- S3: flat node list with id references (no recursion) ------------------------------


class FlatNode(BaseModel):
    id: str = Field(description="unique id, e.g. 'n1'")
    op: Op
    event: str | None = None
    field: str | None = None
    cmp: Literal["lt", "le", "eq", "ge", "gt"] | None = None
    value: float | None = None
    child_ids: list[str] = Field(default_factory=list, description="ids of sub-expressions")


class FlatRule(BaseModel):
    root_id: str
    nodes: list[FlatNode]


# ---- probes ----------------------------------------------------------------------------


class _DeveloperApi:
    """Stand-in for the SDK client in Developer API (API key) mode, as Haqwa uses."""

    vertexai = False


def sent_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The schema the SDK would send for `response_schema=model` (today's client.py path)."""
    return t.t_schema(_DeveloperApi(), model).model_dump(exclude_none=True)


def depth_of_children(schema: dict[str, Any]) -> int:
    """How many `children` levels still carry a real (non-empty) schema."""
    depth = 0
    node = schema["properties"]["root"]
    while "children" in node.get("properties", {}):
        items = node["properties"]["children"].get("items", {})
        if not items:
            break
        depth += 1
        node = items
    return depth


def ref_problems(schema: dict[str, Any]) -> list[str]:
    """Rules from the SDK docs for `response_json_schema` that Pydantic's output may break.

    - a sub-schema with `$ref` may only have other `$`-keys next to it
    - a cyclic `$ref` may only sit in a non-required property
    """
    problems: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            if "$ref" in node:
                extra = [k for k in node if not k.startswith("$")]
                if extra:
                    problems.append(f"{path}: $ref has sibling keys {extra}")
            for key, value in node.items():
                walk(value, f"{path}/{key}")
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]")

    walk(schema, "#")
    node_def = schema.get("$defs", {}).get("Node", {})
    if "children" in node_def.get("required", []):
        problems.append("Node.children is required (cyclic refs must be non-required)")
    return problems


def main() -> None:
    print("== Path A: response_schema=<Pydantic model> (what client.py does today) ==")
    for name, model in [("S1 recursive", RecursiveRule), ("S2 unrolled", UnrolledRule)]:
        levels = depth_of_children(sent_schema(model))
        print(f"{name}: children levels with a real schema = {levels}")
    flat_props = sent_schema(FlatRule)["properties"]["nodes"]["items"]["properties"]
    print(f"S3 flat: converts OK, node props = {sorted(flat_props)}")

    print("\n== Path B: response_json_schema=<JSON Schema> (needs a client.py change) ==")
    raw = RecursiveRule.model_json_schema()
    print("S1 $defs:", sorted(raw.get("$defs", {})))
    problems = ref_problems(raw)
    print("S1 problems vs SDK-documented limits:", problems or "none")
    print("\nS1 raw JSON Schema (first 900 chars):")
    print(json.dumps(raw, indent=1)[:900])


if __name__ == "__main__":
    main()
