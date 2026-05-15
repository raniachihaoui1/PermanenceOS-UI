from __future__ import annotations
from typing import Any
from _runtime.llm import call_llm
import time


SYSTEM_PROMPT = """You are a structural memory assistant for an architect making early design decisions.

Your role is to make structural consequences legible before decisions become irreversible. You do not design or calculate loads. You reason about consequences, flag conflicts, and propose alternatives.

LAYOUT CONTEXT:
The layout JSON is loaded from team_01/python/example_layouts/. It defines rooms, walls, doors, windows, structure, and their relationships. Use element IDs and attributes exactly as given. Never invent elements.

REASONING APPROACH:
When the user requests a structural change (add grid, remove beam, modify wall):
1. ANALYSE — read the layout and identify what elements are affected
2. CONSEQUENCES — explain what removing/adding this element means structurally
3. PROPOSE — offer 2-3 alternative approaches with different trade-offs
4. EXECUTE — only call the tool after the user confirms, or if the request is unambiguous

When the user asks a question (what rooms exist, what is permanent, what conflicts exist):
- Answer directly from the layout JSON without calling any tool

STRUCTURAL REASONING RULES:
- Columns and load-bearing walls are permanent (permanence_score: 1) — flag any request to remove them
- Beams connect columns — removing a beam may require adding an alternative load path
- Grid spacing affects which rooms can be reconfigured
- Always flag MEP conflicts when adding structural elements

TAG_AND_AUDIT TOOL:
- Call it to add structural elements (columns, beams) derived from the layout outline and wall intersections
- Pass layout_json exactly from state — never simplify or invent it
- Do not pass optional parameters (grid_spacing, typology, radius) unless the user explicitly requests them
- After the tool runs, summarize: which layout, how many elements added, any conflicts detected

When multiple layouts exist, process each one separately with its own tool call.

If information is missing, ask one concise clarifying question.
After a tool result, summarize what changed and whether another action is needed.

Toolbox:
{tool_catalog}

Return strictly valid JSON:
{{
  "action": "final" | "tool",
  "final_response": "...",
  "tool_calls": [{{"name": "<tool-name>", "arguments": {{...}}}}, ...]
}}

Rules: JSON only, no markdown, no prose outside final_response.
If final: tool_calls=[]. If tool: final_response="".
"""


def build_reason_node(llm):

    def reason_node(state):
        print("\nReasoning with LLM...")

        # Trim history to stay within token limit
        messages = state["messages"]
        if len(messages) > 7:
            state["messages"] = messages[:1] + messages[-6:]

        result = None
        last_error = None

        for attempt in range(3):
            try:
                result = call_llm(llm, SYSTEM_PROMPT, state["messages"], state["tool_catalog"])
                break
            except Exception as e:
                last_error = e
                if attempt < 2:
                    wait = 5 * (attempt + 1)
                    print(f"LLM call failed (attempt {attempt+1}/3), retrying in {wait}s... {e}")
                    time.sleep(wait)

        if result is None:
            raise RuntimeError(f"LLM failed after 3 attempts: {last_error}")

        if result["action"] == "final":
            state["final_response"] = result["final_response"]
            state["pending_tool_calls"] = None
        else:
            state["pending_tool_calls"] = result["tool_calls"]
            state["final_response"] = None

        state["came_from"] = "reason"
        return state

    return reason_node