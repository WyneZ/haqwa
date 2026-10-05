"""Spike: run a Google ADK (Gemini) agent inside AgentProof, then check it with Haqwa.

agentproof-sim 0.1.1 has no ADK adapter, so `ADKAdapter` below is our own (pattern copied
from agentproof's OpenAIAgentsAdapter: wrap world tools as framework tools, run the agent).

Offline (no key, no LLM): checks imports + tool wrapping + fault plumbing.
    python spikes/agentproof/spike_adk.py --offline
Live (calls Gemini; key only from the environment, never hard-coded):
    export GEMINI_API_KEY=...        # or: set -a; source .env; set +a
    python spikes/agentproof/spike_adk.py [--model gemini-...]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from typing import Any

from agentproof import AgentTest
from agentproof.adapters.base import AgentRunResult
from agentproof.core.faults import AgentProofToolError
from agentproof.mutations.tool_faults import TimeoutAfterCommit
from google.adk.agents import LlmAgent
from google.adk.models.google_llm import Gemini
from google.adk.runners import InMemoryRunner
from google.adk.tools import FunctionTool
from google.genai import types
from shop import print_haqwa_report, setup_shop

DEFAULT_MODEL = "gemini-3.6-flash"  # same model Track A's clarify spike used; change with --model

# Free tier for gemini-3.6-flash allowed 5 requests/minute when we tried (429 said
# `limit: 5`, 2026-09-25). 13 s between requests keeps us under that.
DEFAULT_MIN_INTERVAL = 13.0

# Retry 429 (quota) and 503 (overloaded) inside google-genai with backoff.
# Note: these HTTP retries are NOT seen by GeminiRequestCounter but DO use quota.
RETRY = types.HttpRetryOptions(
    attempts=4, initial_delay=15, max_delay=60, http_status_codes=[429, 503]
)

NAIVE_INSTRUCTION = (
    "You are a shop assistant. To complete a purchase: call create_order, then call "
    "charge_payment. If charge_payment returns an error, call charge_payment again. "
    "Reply 'paid' when a charge succeeds."
)


def build_adk_tools(world: Any) -> list[FunctionTool]:
    """Wrap AgentProof world tools as ADK function tools.

    ADK builds the tool schema from the Python signature, so each tool has an explicit
    typed wrapper. AgentProof tool errors (e.g. injected timeouts) are returned to the
    model as data instead of crashing the run - like a real API timeout response.
    """

    async def call(name: str, **kwargs: Any) -> dict:
        try:
            return {"result": await world.tools.invoke(name, kwargs)}
        except AgentProofToolError as exc:
            return {"error": type(exc).__name__, "message": str(exc)}

    async def create_order(order_id: str, amount: int) -> dict:
        """Create an order."""
        return await call("create_order", order_id=order_id, amount=amount)

    async def charge_payment(order_id: str, amount: int) -> dict:
        """Charge the customer's card for an order."""
        return await call("charge_payment", order_id=order_id, amount=amount)

    return [FunctionTool(create_order), FunctionTool(charge_payment)]


class GeminiRequestCounter:
    """Counts Gemini requests per AgentProof run via ADK model callbacks.

    `before_model_callback` fires once per model request ADK sends; `after_model_callback`
    once per response received. Requests - responses = calls that errored (429/503...).
    Note: HTTP-level retries inside google-genai (if any) are not visible here.
    """

    def __init__(self, min_interval: float = 0.0) -> None:
        self.runs: list[dict[str, int]] = []
        self.min_interval = min_interval  # pacing: min seconds between requests
        self._last = 0.0

    def start_run(self) -> None:
        self.runs.append({"requests": 0, "responses": 0})

    async def before_model(self, *, callback_context: Any, llm_request: Any) -> None:
        wait = self.min_interval - (time.monotonic() - self._last)
        if self._last and wait > 0:
            print(f"  (pacing: waiting {wait:.0f}s for free-tier rate limit)", flush=True)
            await asyncio.sleep(wait)
        self._last = time.monotonic()
        self.runs[-1]["requests"] += 1
        return None  # None = let ADK send the request as usual

    def after_model(self, *, callback_context: Any, llm_response: Any) -> None:
        self.runs[-1]["responses"] += 1
        return None

    @property
    def total_requests(self) -> int:
        return sum(r["requests"] for r in self.runs)

    def summary(self) -> str:
        lines = ["", "=== Gemini API usage"]
        for i, r in enumerate(self.runs, 1):
            lines.append(f"  run {i}: {r['requests']} requests, {r['responses']} responses")
        lines.append(f"  TOTAL: {self.total_requests} requests")
        return "\n".join(lines)


class ADKAdapter:
    """AgentProof adapter for a Google ADK LlmAgent (spike version)."""

    name = "google-adk"

    def __init__(self, model: str, counter: GeminiRequestCounter | None = None) -> None:
        self.model = model
        self.counter = counter or GeminiRequestCounter()

    async def run(self, *, world: Any, user_input: str) -> AgentRunResult:
        self.counter.start_run()
        agent = LlmAgent(
            name="shop_agent",
            model=Gemini(model=self.model, retry_options=RETRY),
            instruction=NAIVE_INSTRUCTION,
            tools=build_adk_tools(world),
            before_model_callback=self.counter.before_model,
            after_model_callback=self.counter.after_model,
        )
        runner = InMemoryRunner(agent=agent, app_name="haqwa_spike")
        session = await runner.session_service.create_session(app_name="haqwa_spike", user_id="u1")
        final = None
        message = types.Content(role="user", parts=[types.Part(text=user_input)])
        async for event in runner.run_async(
            user_id="u1", session_id=session.id, new_message=message
        ):
            if event.is_final_response() and event.content and event.content.parts:
                final = "".join(p.text or "" for p in event.content.parts)
        return AgentRunResult(final_output=final, metadata={"framework": "google-adk"})


async def offline_check() -> None:
    """No LLM: call the wrapped tools the way the model would, under the timeout fault."""
    from agentproof import World

    world = World()
    setup_shop(world)
    TimeoutAfterCommit(target="charge_payment").install(world)
    tools = {t.name: t for t in build_adk_tools(world)}
    print("ADK tool names:", sorted(tools))
    print("create_order ->", await tools["create_order"].func(order_id="A-1", amount=50))
    print("charge #1    ->", await tools["charge_payment"].func(order_id="A-1", amount=50))
    print("charge #2    ->", await tools["charge_payment"].func(order_id="A-1", amount=50))

    class R:  # minimal stand-in for an AgentProof RunResult
        scenario, mutation, error_message = "offline (timeout_after_commit)", None, None
        effects = world.effects.all()

    print_haqwa_report(type("S", (), {"results": [R]}))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--save-effects", help="write the faulted effect ledger as recording JSON")
    parser.add_argument("--model", default=os.environ.get("HAQWA_DEMO_MODEL", DEFAULT_MODEL))
    parser.add_argument(
        "--min-interval",
        type=float,
        default=DEFAULT_MIN_INTERVAL,
        help="seconds between Gemini requests (0 = no pacing)",
    )
    args = parser.parse_args()

    if args.offline:
        asyncio.run(offline_check())
        return
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        sys.exit("Set GEMINI_API_KEY in the environment (or use --offline).")

    counter = GeminiRequestCounter(min_interval=args.min_interval)
    suite = AgentTest(
        agent=None,
        adapter=ADKAdapter(args.model, counter),
        mutations=[TimeoutAfterCommit(target="charge_payment")],
        name="adk",
    )

    @suite.scenario(name="adk_payment_timeout")
    def scenario(world):
        setup_shop(world)
        world.input("Buy order A-1 for 50 dollars.")

    try:
        result = suite.run_sync(store_artifacts=False)
        print_haqwa_report(result)
        if args.save_effects:
            from haqwa.demo.recording import save_effects

            faulted = [run for run in result.results if run.mutation is not None]
            if not faulted or faulted[-1].error_message:
                sys.exit("Cannot save recording: the faulted run did not complete.")
            save_effects(faulted[-1].effects, args.save_effects)
            print(f"Saved effects to {args.save_effects}")
    finally:
        print(counter.summary())  # printed even if a run fails


if __name__ == "__main__":
    main()
