"""Google ADK agent connected to the live MCP shop."""

from __future__ import annotations

import asyncio
import time
from typing import Any

DEFAULT_MODEL = "gemini-3.6-flash"
TASKS = {
    "timeout_after_commit": "Create order A-1 for 50 and charge it.",
    "stale_state": "Process fulfilment for order A-1.",
}


class GeminiRequestCounter:
    """Count ADK requests while spacing them to respect the demo quota."""

    def __init__(self, min_interval: float = 13.0) -> None:
        self.requests = 0
        self.responses = 0
        self.min_interval = min_interval
        self.last_request = 0.0

    async def before_model(self, *, callback_context: Any, llm_request: Any) -> None:
        wait = self.min_interval - (time.monotonic() - self.last_request)
        if self.last_request and wait > 0:
            await asyncio.sleep(wait)
        self.last_request = time.monotonic()
        self.requests += 1

    def after_model(self, *, callback_context: Any, llm_response: Any) -> None:
        self.responses += 1


async def run_adk_agent(
    url: str, task: str, model: str, counter: GeminiRequestCounter
) -> list[dict[str, Any]]:
    """Run one neutral agent task and return its visible tool calls and results."""
    # ADK is an optional demo dependency. Keeping imports here leaves the core usable alone.
    from google.adk.agents import LlmAgent
    from google.adk.models.google_llm import Gemini
    from google.adk.runners import InMemoryRunner
    from google.adk.tools.mcp_tool.mcp_toolset import McpToolset, StreamableHTTPConnectionParams
    from google.genai import types

    retry = types.HttpRetryOptions(
        attempts=4, initial_delay=15, max_delay=60, http_status_codes=[429, 503]
    )
    toolset = McpToolset(connection_params=StreamableHTTPConnectionParams(url=url))
    calls: list[dict[str, Any]] = []
    try:
        agent = LlmAgent(
            name="shop_agent",
            model=Gemini(model=model, retry_options=retry),
            instruction=(
                "You are a shop assistant. Complete the user's request using the shop tools."
            ),
            tools=[toolset],
            before_model_callback=counter.before_model,
            after_model_callback=counter.after_model,
        )
        runner = InMemoryRunner(agent=agent, app_name="haqwa_live")
        session = await runner.session_service.create_session(app_name="haqwa_live", user_id="u1")
        message = types.Content(role="user", parts=[types.Part(text=task)])
        async for event in runner.run_async(
            user_id="u1", session_id=session.id, new_message=message
        ):
            for call in event.get_function_calls():
                calls.append({"name": call.name, "args": call.args})
            for response in event.get_function_responses():
                for call in reversed(calls):
                    if call["name"] == response.name and "result" not in call:
                        call["result"] = response.response
                        break
    finally:
        await toolset.close()
    return calls
