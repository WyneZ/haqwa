"""Demo shop + agents + AgentProof fault scenarios (needs agentproof-sim==0.1.1).

Used by the terminal demo (`python -m haqwa.demo`) and the web API (screen 2).
The agents are deterministic native Python (no Gemini): see docs/decisions.md.
"""

from .scenarios import Scenario, list_scenarios, run_scenario

__all__ = ["Scenario", "list_scenarios", "run_scenario"]
