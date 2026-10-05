"""Plain-English explanation of one violation (C3 endpoint 6). ADVISORY ONLY.

Core has already decided that this is a violation. Gemini only explains what happened
and the likely cause, for a non-technical ops manager. The explanation never changes the
verdict, and the result always carries `advisory=True` so the UI labels it.

One Gemini call per violation; the disk cache in `client.py` makes repeats free.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from haqwa.core.report import Violation
from haqwa.core.spec import AllowIf, ResetAfter, Rule

from .client import GeminiClient


# Wire model (no docstring: Pydantic would send it to Gemini as a schema description).
class WireExplanation(BaseModel):
    text: str = Field(
        description="2-3 short sentences: what happened to this entity, and the likely cause"
    )


class Explanation(BaseModel):
    """What the web returns for `/api/v1/explain` (C3)."""

    text: str
    advisory: bool = True  # always True: the verdict comes from core, never from this text
    cached: bool = False


def explain_violation(rule: Rule, violation: Violation, *, client: GeminiClient) -> Explanation:
    """Ask Gemini to explain one violation that core already found.

    Raises:
        GeminiError: quota, availability or bad output (see `client.py`). The verdict
            stays valid; the UI just shows no explanation.
    """
    result = client.generate(build_prompt(rule, violation), WireExplanation)
    return Explanation(text=result.value.text.strip(), cached=result.cached)


def build_prompt(rule: Rule, violation: Violation) -> str:
    """The explain prompt: rule, owner decisions, and the entity's timeline."""
    decisions = _owner_decisions(rule) or ["(none)"]
    lines = []
    for i, e in enumerate(violation.timeline):
        mark = ">>" if i == violation.offending_index else "  "
        data = ", ".join(f"{k}={v}" for k, v in e.data.items() if k != rule.per)
        lines.append(f"{mark} {e.ts.isoformat()}  {e.event}" + (f"  ({data})" if data else ""))
    timeline = "\n".join(lines)
    decision_text = "\n".join(f"- {d}" for d in decisions)
    return f"""You explain a policy violation to a non-technical operations manager.

A deterministic checker has ALREADY decided this is a violation. Do not question,
repeat or change that verdict, and do not judge other rules.

Policy: "{rule.source}" (per {rule.per})
The policy owner decided:
{decision_text}

Checker message: {violation.message}

Events for {rule.per} {violation.entity} (oldest first; ">>" marks the event that broke
the policy):
{timeline}

In 2-3 short sentences of plain English: say what happened to {rule.per}
{violation.entity}, then the most likely cause. Use only facts from the events above;
if the cause is not certain, say "likely". No code, no event names in snake_case, no
markdown."""


def _owner_decisions(rule: Rule) -> list[str]:
    """The rule's exceptions in plain English, so the explanation respects them."""
    out = []
    for exc in rule.exceptions:
        if isinstance(exc, ResetAfter):
            out.append(f"After '{exc.reset_after}', the {rule.per} starts fresh.")
        elif isinstance(exc, AllowIf):
            c = exc.allow_if
            out.append(f"Events where {c.field} {c.op} {c.value!r} are allowed and ignored.")
    return out
