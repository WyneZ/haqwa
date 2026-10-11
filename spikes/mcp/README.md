# MCP shop spike

The MCP server uses the official Python `mcp` SDK and one AgentProof `World`.
`create_order` and `charge_payment` call the registered `haqwa.demo.shop.setup_shop`
tools. The first charge after each reset commits its `charged` effect, then the MCP
layer returns a `timeout_after_commit` tool error. `list_effects` exposes the
committed ledger; `reset_shop` gives each demonstration a fresh world.

From the repository root, install the pinned demo dependencies:

```sh
.venv/bin/uv sync --group demo
```

In terminal 1:

```sh
.venv/bin/python spikes/mcp/server.py
```

In terminal 2, prove the tools and both verdicts without a model or key:

```sh
.venv/bin/python spikes/mcp/client_script.py
```

Check ADK's MCP connection without a model request:

```sh
.venv/bin/python spikes/mcp/adk_agent.py --check-connection
```

For Wyne's live run, set `GEMINI_API_KEY` in the terminal environment, then:

```sh
.venv/bin/python spikes/mcp/adk_agent.py
```

The live agent receives only the two shop tools and the neutral task “Create
order A-1 for 50 and charge it.” The script prints the agent's tool calls, the
committed effects, Haqwa's verdict, and the count of ADK model requests. The
count does not include internal HTTP retries by `google-genai`.

This is a single-process localhost spike. Resetting the shop while an agent run
is active would replace its world, so run one client at a time.
