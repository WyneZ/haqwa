"""Run a Gemini ADK agent against an existing Haqwa MCP session."""

from __future__ import annotations

import argparse
import asyncio
import json
import os

from haqwa.live.agent import DEFAULT_MODEL, GeminiRequestCounter, run_adk_agent


def main() -> None:
    parser = argparse.ArgumentParser(description="Connect a Gemini agent to a Haqwa shop.")
    parser.add_argument("--url", required=True, help="MCP URL returned by the session API")
    parser.add_argument("--task", required=True, help="Task returned by the session API")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini model name")
    args = parser.parse_args()
    if not os.getenv("GEMINI_API_KEY"):
        parser.error("Set GEMINI_API_KEY in the environment before connecting the agent.")

    calls = asyncio.run(run_adk_agent(args.url, args.task, args.model, GeminiRequestCounter()))
    for call in calls:
        print(json.dumps(call, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
