from __future__ import annotations
from typing import Any
from _runtime.llm import call_llm


# ---------------------------------------------------------------------------
# System prompt — edit this to change how the agent thinks and behaves.
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a spatial accessibility assistant for floor plans. You use tools to analyze and modify layouts.

PROFILES: wheelchair, autistic, elderly, visually_impaired, hearing_impaired.
Default to wheelchair if unspecified.

TOOLS:
- check_door_widths(min_door_width): returns conflict door IDs
- widen_doors(door_ids, target_width): MODIFIES doors to a new width
- shortest_path, get_visibility, collision_detector_sphere: full analysis

DOOR FIX WORKFLOW — MANDATORY EVERY STEP:

When the user asks to FIX, WIDEN, REPAIR, or MODIFY doors:

STEP 1: Call check_door_widths with min_door_width=0.9 (wheelchair) or appropriate profile width.

STEP 2: Look at the "conflicts" array in the result.

STEP 3: You MUST call widen_doors NEXT. Do not skip this step. Do not assume widen_doors was already called. Do not respond with "final" until widen_doors has returned a result.

Format for STEP 3 call:
{{"action":"tool","final_response":"","tool_calls":[{{"name":"widen_doors","arguments":{{"door_ids":"d03,d04,d09,d10","target_width":0.9}}}}]}}

The door_ids string MUST be a comma-separated list of the conflict IDs from STEP 2. Example: if conflicts is ["d03","d04","d09","d10"], door_ids must be "d03,d04,d09,d10".

STEP 4: Only AFTER widen_doors returns a result with "modified" array, respond with action "final" summarizing what was actually modified.

CRITICAL RULES:
- NEVER claim doors were widened unless widen_doors has been called and returned successfully.
- NEVER skip widen_doors when the user asks to fix doors.
- NEVER call the same tool twice in a row.
- If widen_doors returns "modified": [], that means nothing was changed — report this honestly.

For general accessibility analysis (no door fix request): call shortest_path, get_visibility, collision_detector_sphere once each, then respond final.

OUTPUT (strict JSON, no markdown):
{{"action":"final"|"tool","final_response":"...","tool_calls":[{{"name":"<name>","arguments":{{...}}}}]}}

If action is "final": tool_calls is [], answer in final_response.
If action is "tool": final_response is "", call in tool_calls.

Tools available: {tool_catalog}
"""


# ---------------------------------------------------------------------------
# Reason node — the LLM decision step in the graph.
# ---------------------------------------------------------------------------

def build_reason_node(llm):
    """Return a reason node function ready to be added to a LangGraph StateGraph."""

    def reason_node(state):
        print("\nReasoning with LLM...")
        result = call_llm(llm, SYSTEM_PROMPT, state["messages"], state["tool_catalog"])

        # If the LLM decided no more actions are needed (action is final), set the final response in the state and clear pending tool calls
        if result["action"] == "final":
            state["final_response"] = result["final_response"]
            state["pending_tool_calls"] = None

        # If the LLM decided the action is to use a tool, set the pending tool calls
        else:
            state["pending_tool_calls"] = result["tool_calls"]

        return state

    return reason_node
