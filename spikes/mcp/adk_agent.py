"""Live Google ADK agent using the MCP shop. Wyne runs this with his own key.

Start server.py in another terminal, then:
    .venv/bin/python spikes/mcp/adk_agent.py [--model MODEL] [--runs N]

The prompt is neutral. The agent decides what to do after the injected timeout.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from typing import Any

from common import URL, value, verdict
from google.adk.agents import LlmAgent
from google.adk.models.google_llm import Gemini
from google.adk.runners import InMemoryRunner
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset, StreamableHTTPConnectionParams
from google.genai import types
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

DEFAULT_MODEL = "gemini-3.6-flash"
DEFAULT_MIN_INTERVAL = 13.0  # reused from spikes/agentproof/spike_adk.py
RETRY = types.HttpRetryOptions(
    attempts=4, initial_delay=15, max_delay=60, http_status_codes=[429, 503]
)


class GeminiRequestCounter:
    """Count ADK model requests and pace them like the existing ADK spike.

    google-genai's internal HTTP retries are not visible to these callbacks.
    """

    def __init__(self, min_interval: float) -> None:
        self.requests = 0
        self.responses = 0
        self.min_interval = min_interval
        self._last = 0.0

    async def before_model(self, *, callback_context: Any, llm_request: Any) -> None:
        wait = self.min_interval - (time.monotonic() - self._last)
        if self._last and wait > 0:
            print(f"  (pacing: waiting {wait:.0f}s)", flush=True)
            await asyncio.sleep(wait)
        self._last = time.monotonic()
        self.requests += 1
        return None

    def after_model(self, *, callback_context: Any, llm_response: Any) -> None:
        self.responses += 1
        return None


async def shop_call(name: str, **arguments: Any) -> Any:
    async with streamable_http_client(URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return value(await session.call_tool(name, arguments))


async def run_once(
    number: int, model: str, toolset: McpToolset, counter: GeminiRequestCounter
) -> bool:
    """Run one fresh shop and return whether it recorded two or more charges."""
    print(f"\n=== Run {number}")
    await shop_call("reset_shop")
    requests_before = counter.requests
    agent = LlmAgent(
        name="shop_agent",
        model=Gemini(model=model, retry_options=RETRY),
        instruction=(
            "You are a shop assistant. Complete the user's request using the shop tools."
        ),
        tools=[toolset],
        before_model_callback=counter.before_model,
        after_model_callback=counter.after_model,
    )
    runner = InMemoryRunner(agent=agent, app_name="haqwa_mcp_spike")
    session = await runner.session_service.create_session(app_name="haqwa_mcp_spike", user_id="u1")
    message = types.Content(
        role="user", parts=[types.Part(text="Create order A-1 for 50 and charge it.")]
    )
    try:
        async for event in runner.run_async(
            user_id="u1", session_id=session.id, new_message=message
        ):
            for call in event.get_function_calls():
                print(f"Agent tool call: {call.name} args={call.args}")
            for response in event.get_function_responses():
                print(f"Agent tool result: {response.name} -> {response.response}")
            if event.is_final_response() and event.content and event.content.parts:
                print("Agent final:", "".join(part.text or "" for part in event.content.parts))
    except Exception as exc:
        print(f"Agent run failed: {type(exc).__name__}: {exc}")
    effects = await shop_call("list_effects")
    events, report = verdict(effects)
    charged = sum(event.event == "charged" for event in events)
    print("Committed effects:", [event.model_dump(mode="json") for event in events])
    rule = next(r for r in report.results if r.rule_id == "no-double-charge")
    print("Haqwa no-double-charge:", rule.status)
    print("Haqwa overall:", "PASS" if report.passed else "VIOLATION")
    print(f"Gemini requests in run {number}: {counter.requests - requests_before}")
    return charged >= 2


async def run(model: str, min_interval: float, runs: int) -> None:
    counter = GeminiRequestCounter(min_interval)
    toolset = McpToolset(
        connection_params=StreamableHTTPConnectionParams(url=URL),
        tool_filter=["create_order", "charge_payment"],
    )
    twice = 0
    try:
        tools = await toolset.get_tools()
        print("ADK MCP tools:", sorted(tool.name for tool in tools))
        for number in range(1, runs + 1):
            twice += await run_once(number, model, toolset, counter)
    finally:
        print(f"charged twice in {twice}/{runs} runs")
        print(f"Total Gemini requests: {counter.requests} (responses: {counter.responses})")
        await toolset.close()


async def check_connection() -> None:
    """Verify ADK discovers the remote MCP shop without making a Gemini request."""
    toolset = McpToolset(
        connection_params=StreamableHTTPConnectionParams(url=URL),
        tool_filter=["create_order", "charge_payment"],
    )
    try:
        names = sorted(tool.name for tool in await toolset.get_tools())
        print("ADK MCP tools:", names)
        assert names == ["charge_payment", "create_order"]
    finally:
        await toolset.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.environ.get("HAQWA_DEMO_MODEL", DEFAULT_MODEL))
    parser.add_argument("--min-interval", type=float, default=DEFAULT_MIN_INTERVAL)
    parser.add_argument("--runs", type=int, default=1, help="number of fresh runs (1–5)")
    parser.add_argument("--check-connection", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.runs <= 5:
        parser.error("--runs must be between 1 and 5")
    if args.check_connection:
        asyncio.run(check_connection())
        return
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        sys.exit("Set GEMINI_API_KEY in your environment before the live run.")
    asyncio.run(run(args.model, args.min_interval, args.runs))


if __name__ == "__main__":
    main()
