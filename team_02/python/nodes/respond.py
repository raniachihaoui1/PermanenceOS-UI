"""
nodes/respond.py — RESPOND node for the Comfort Copilot state graph.

LLM node. Runs last on the comfort path, after all tool nodes have finished.
Reads the raw JSON results from state and produces a natural language report
for the user — no JSON, no markdown tables, just clear prose.

Reads from state:
  raw_prompt             (str)       — original user request
  persona_detected       (str)       — e.g. "Elderly 65+"
  layout_id              (str)       — e.g. "201"
  comfort_depth          (str)       — "analyze" | "detect" | "full"
  last_scores_json       (str)       — output of compute_comfort_scores
  last_conflicts_json    (str | "")  — output of detect_sensorial_conflicts
  last_suggestions_json  (str | "")  — output of generate_suggestions

Writes to state:
  final_response  (str)  — the formatted natural language report
"""

from __future__ import annotations
from _runtime.llm import call_llm_simple


_SYSTEM_PROMPT = """\
You are Comfort Copilot, an architectural comfort analyst specialising in
multi-sensory wellbeing: thermal, visual, acoustic, spatial, olfactory, tactile.

You have just run an analysis of an apartment layout. Write a concise report
that mixes actual scores with plain-language interpretation. Be brief and direct.

Start with ONE line addressing the persona (e.g. "For a Child under 12, Layout 202:").
Do NOT repeat the persona name for every room — write it once only at the top.

Format per room (one room = one short block):
  Room Name
  - Best: <dimension> (<score>) - one-line note
  - Worst: <dimension> (<score>) - one-line note
  - Other scores: thermal X.XX | visual X.XX | acoustic X.XX | spatial X.XX | olfactory X.XX | tactile X.XX
  - One sentence on what this means for the persona.

Rules:
- Scores range from 0.0 (very poor) to 1.0 (excellent).
- Address the persona by its EXACT category name ONCE at the top. Never invent
  a personal name like "Sarah" or "John".
- CRITICAL: Only include a "Conflicts" section if the message contains a
  "--- CONFLICTS (tool output) ---" block. If that block says "not run", you
  MUST NOT write any conflicts — do not infer them from scores.
- CRITICAL: Only include a "Suggestions" section if the message contains a
  "--- SUGGESTIONS (tool output) ---" block. If that block says "not run", you
  MUST NOT write any suggestions — do not infer them from scores.
- End with one sentence overall summary.
- No markdown tables. No JSON. No internal tool names. Keep it short.
- Use only plain ASCII characters. Use a hyphen (-) not an em dash.
"""


def build_respond_node(llm):
    """Return the respond node function, capturing the LLM instance."""

    def respond_node(state: dict) -> dict:
        persona       = state.get("persona_detected", "Neutral")
        layout_id     = state.get("layout_id", "?")
        depth         = state.get("comfort_depth", "analyze")
        scores        = state.get("last_scores_json", "")
        conflicts     = state.get("last_conflicts_json", "")
        suggestions   = state.get("last_suggestions_json", "")
        raw_prompt    = state.get("raw_prompt", "")

        # Build the user message — include only the data that was actually computed
        sections: list[str] = [
            f"User request: {raw_prompt}",
            f"Persona: {persona}",
            f"Layout ID: {layout_id}",
            f"Analysis depth: {depth}",
            "",
            "--- COMFORT SCORES (tool output) ---",
            scores or "(not computed)",
            "",
            "--- CONFLICTS (tool output) ---",
            conflicts if conflicts else "not run — do NOT invent or infer conflicts",
            "",
            "--- SUGGESTIONS (tool output) ---",
            suggestions if suggestions else "not run — do NOT invent or infer suggestions",
        ]

        user_message = "\n".join(sections)

        print(f"[respond] Generating natural language report...")
        response = call_llm_simple(llm, _SYSTEM_PROMPT, user_message)

        return {
            **state,
            "final_response": response,
        }

    return respond_node
