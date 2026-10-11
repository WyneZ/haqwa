# MCP shop spike

The MCP server uses the official Python `mcp` SDK and one AgentProof `World`.
`create_order` and `charge_payment` call the registered `haqwa.demo.shop.setup_shop`
tools. The first charge after each reset commits its `charged` effect, then the MCP
layer returns a generic timeout tool error. `list_effects` exposes the
committed ledger; `reset_shop` gives each demonstration a fresh world.
The client sees only `Request timed out`; the server logs the injected fault
after committing the effect.

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
.venv/bin/python spikes/mcp/adk_agent.py --runs 1
```

The live agent receives only the two shop tools and the neutral task “Create
order A-1 for 50 and charge it.” `--runs` accepts 1–5 and resets the shop before
each run. The script prints every tool call with arguments and result, each
run's committed effects and Haqwa verdict, the number of runs with duplicate
charges, and total ADK model requests. The request count does not include
internal HTTP retries by `google-genai`.

This is a single-process localhost spike. Resetting the shop while an agent run
is active would replace its world, so run one client at a time.
