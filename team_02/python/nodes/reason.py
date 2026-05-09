from __future__ import annotations
from typing import Any
from _runtime.llm import call_llm
from personas import format_for_prompt


# =============================================================================
# reason.py — LLM decision node for the Comfort Copilot state graph.
#
# The system prompt is built DYNAMICALLY each time the reason node runs,
# using the intent and persona already detected by the preprocess node.
# This ensures the LLM only calls the tools needed for the current intent.
#
# Intent → tool sequence mapping:
#   chitchat        → no tools, answer directly
#   comfort_analyze → compute_comfort_scores only
#   comfort_detect  → compute_comfort_scores → detect_sensorial_conflicts
#   comfort_full    → compute_comfort_scores → detect_sensorial_conflicts → generate_suggestions
#   inspire         → (Phase 3, not yet implemented)
# =============================================================================


# ---------------------------------------------------------------------------
# Static sections shared across all system prompts
# ---------------------------------------------------------------------------

_BASE = """You are Comfort Copilot, an AI agent that analyzes architectural room layouts for multi-sensory comfort. You evaluate six comfort dimensions — thermal, visual, acoustic, spatial, olfactory, and tactile — detect conflicts, and generate improvement recommendations tailored to a specific user persona.

## Available personas
{personas}

## Layout rules
- If no layout is loaded and the request requires one, your FIRST tool call must be `select_layout` (no arguments).
- Never call `select_layout` more than once per session.
- Do not include `layout_json` in your tool arguments — it is injected automatically from the loaded layout.

## Supporting tools
Use these when the user asks specific questions outside of comfort analysis:
- `compute_room_area` — when the user asks about the size of a specific room
- `compute_total_area` — when the user asks about total floor area
- `remove_furniture_piece` — when implementing a suggestion that involves removing furniture

## Tool failure rule
If a tool result contains "_no_change_warning", respond immediately with action "final" reporting the failure. Do not retry the same tool.

Toolbox (name, description, and inputSchema for each tool):
{{tool_catalog}}

Return strictly valid JSON with exactly this shape:
{{{{
  "action": "final" | "tool",
  "final_response": "...",
  "tool_calls": [{{{{"name": "<tool-name>", "arguments": {{{{...}}}}}}}}]
}}}}

Output rules:
- Return JSON only, with no prose or explanation outside final_response.
- Do not use markdown code fences.
- If action is "final", set tool_calls to [] and put the answer in final_response.
- If action is "tool", set final_response to "" and list tool calls in tool_calls.
"""

_PERSONA_ASK = """
## Action required — persona missing
The user wants a comfort analysis but did NOT mention a persona.
Respond immediately with action "final", asking the user which persona to use.
Do NOT call any tools until a persona is established.
"""

_CHITCHAT = """
## Intent: chitchat
The user is asking a casual question unrelated to comfort analysis.
Respond with action "final" directly — no tools needed.
"""

_ANALYZE = """
## Intent: comfort_analyze — compute scores only
The user wants to see comfort scores. Run ONLY this step:
1. Call `compute_comfort_scores` — args: persona="{persona}", room_ids="all"
2. Respond with action "final" using the scores schema below.

## Output schema for comfort_analyze
{{{{
  "layoutId": "<from layout>",
  "persona": "<persona used>",
  "rooms": [
    {{{{
      "roomId": "<id>",
      "roomName": "<name>",
      "persona": "<persona>",
      "comfortScores": {{{{
        "thermal": 0.0, "visual": 0.0, "acoustic": 0.0,
        "spatial": 0.0, "olfactory": 0.0, "tactile": 0.0
      }}}},
      "overallScore": 0.0,
      "conflicts": [],
      "suggestions": [],
      "narrative": "<plain language summary of scores only>"
    }}}}
  ]
}}}}
"""

_DETECT = """
## Intent: comfort_detect — scores + conflict detection
The user wants to know what is wrong. Run ONLY these two steps:
1. Call `compute_comfort_scores` — args: persona="{persona}", room_ids="all"
2. Call `detect_sensorial_conflicts` — args: persona="{persona}"
3. Respond with action "final" using the schema below.

## Output schema for comfort_detect
{{{{
  "layoutId": "<from layout>",
  "persona": "<persona used>",
  "rooms": [
    {{{{
      "roomId": "<id>",
      "roomName": "<name>",
      "persona": "<persona>",
      "comfortScores": {{{{
        "thermal": 0.0, "visual": 0.0, "acoustic": 0.0,
        "spatial": 0.0, "olfactory": 0.0, "tactile": 0.0
      }}}},
      "overallScore": 0.0,
      "conflicts": ["<conflict description>"],
      "suggestions": [],
      "narrative": "<plain language summary of scores and conflicts>"
    }}}}
  ]
}}}}
"""

_FULL = """
## Intent: comfort_full — scores + conflicts + suggestions
The user wants the full analysis with improvement recommendations. Follow all three steps:
1. Call `compute_comfort_scores` — args: persona="{persona}", room_ids="all"
2. Call `detect_sensorial_conflicts` — args: persona="{persona}"
3. Call `generate_suggestions` — args: persona="{persona}", conflicts=<full JSON string from step 2>
4. Respond with action "final" using the schema below.

## Output schema for comfort_full
{{{{
  "layoutId": "<from layout>",
  "persona": "<persona used>",
  "rooms": [
    {{{{
      "roomId": "<id>",
      "roomName": "<name>",
      "persona": "<persona>",
      "comfortScores": {{{{
        "thermal": 0.0, "visual": 0.0, "acoustic": 0.0,
        "spatial": 0.0, "olfactory": 0.0, "tactile": 0.0
      }}}},
      "overallScore": 0.0,
      "conflicts": ["<conflict description>"],
      "suggestions": ["<suggestion text>"],
      "narrative": "<plain language summary>"
    }}}}
  ]
}}}}

Assemble by combining the three tool results: scores from compute_comfort_scores,
conflicts from detect_sensorial_conflicts, suggestions from generate_suggestions.
Match rooms by roomId. For rooms with no conflicts, set conflicts to [] and suggestions to [].
"""

_INSPIRE = """
## Intent: inspire
The user wants atmospheric / mood inspiration. This feature is not yet implemented.
Respond with action "final" letting the user know image generation is coming in a future phase.
"""


# ---------------------------------------------------------------------------
# Dynamic system prompt builder
# ---------------------------------------------------------------------------

def _build_system_prompt(intent: str, persona: str | None, needs_persona_ask: bool) -> str:
    """
    Assemble a system prompt tailored to the current intent and persona.
    The base section is always included; the intent section is appended.
    """
    base = _BASE.format(personas=format_for_prompt())

    if needs_persona_ask:
        return base + _PERSONA_ASK

    p = persona or "Neutral"

    if intent == "chitchat" or intent == "":
        return base + _CHITCHAT
    elif intent == "comfort_analyze":
        return base + _ANALYZE.format(persona=p)
    elif intent == "comfort_detect":
        return base + _DETECT.format(persona=p)
    elif intent == "comfort_full":
        return base + _FULL.format(persona=p)
    elif intent == "inspire":
        return base + _INSPIRE
    else:
        # Fallback — treat unknown intent as chitchat
        return base + _CHITCHAT


# ---------------------------------------------------------------------------
# Reason node — the LLM decision step in the graph.
# ---------------------------------------------------------------------------

def build_reason_node(llm):
    """Return a reason node function ready to be added to a LangGraph StateGraph."""

    def reason_node(state):
        intent = state.get("intent", "")
        persona = state.get("persona_detected")
        needs_persona_ask = state.get("needs_persona_ask", False)

        print(f"\n[reason] Intent={intent!r}  Persona={persona!r}  NeedsAsk={needs_persona_ask}")

        system_prompt = _build_system_prompt(intent, persona, needs_persona_ask)
        print("\nReasoning with LLM...")
        result = call_llm(llm, system_prompt, state["messages"], state["tool_catalog"])

        # If the LLM decided no more actions are needed, store final response
        if result["action"] == "final":
            state["final_response"] = result["final_response"]
            state["pending_tool_calls"] = None

        # If the LLM decided to call a tool, store the pending calls
        else:
            state["pending_tool_calls"] = result["tool_calls"]

        return state

    return reason_node
