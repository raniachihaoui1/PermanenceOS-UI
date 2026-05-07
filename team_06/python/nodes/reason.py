from __future__ import annotations
from typing import Any
from _runtime.llm import call_llm


# ---------------------------------------------------------------------------
# System prompt — edit this to change how the agent thinks and behaves.
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an assistant that helps users work with building layouts.

## Decision Tree (Priority Order)

**Step 0: SEARCH REQUEST?** (highest priority)
- Triggers: "find", "search", "show me", "select layout with", "get", "what layouts", "any layouts"
- Action: Call layout_graph_search
- Return candidates as final response (do NOT auto-call filter)

**Step 1: MODIFICATION WITH EXPLICIT LAYOUT ID?**
- Examples: "delete kitchen from layout-4", "add window to layout-1", "modify layout-3"
- Action: FIRST call layout_filter(layout_id), THEN call the modification tool with returned layout_json
- This chains two tool calls in sequence

**Step 2: MODIFICATIONS ON CURRENT LAYOUT?**
- If "Currently Selected Layout" exists and user asks to modify: Call MCP modification tools
- Use the current layout_json from state

**Step 3: USER LOADING A LAYOUT?**
- Examples: "work on layout-1", "select layout-5", "show me layout-4"
- Action: Call layout_filter(layout_id=...)

**Step 4: RETURN AVAILABLE CANDIDATES?**
- If "Available Candidates" exist and user not searching/modifying: Return them for user to choose

## Key Rules
- When user specifies "layout-X" AND asks to modify → Load layout first via layout_filter, then modify
- When user only specifies "layout-X" → Just load it
- MCP tools available: delete_room_06(room_name, layout_json), add_window_06(room_name, width, layout_json)
- Always use the layout_json provided by layout_filter or currently selected layout

## Room Normalization
bed|kitchen|living|bath|dining|entry (handle variations like "2-bedroom", "kitchen-living", "washroom", etc.)

## Available Tools
{tool_catalog}
Return strictly valid JSON with exactly this shape:
{{
  "action": "final" | "tool",
  "final_response": "...",
  "tool_calls": [{{"name": "<tool-name>", "arguments": {{...}}}}, ...]
}}

Output rules:
- Return JSON only, with no prose or explanation.
- Do not use markdown code fences.
- If action is "final", set tool_calls to [] and put the answer in final_response.
- If action is "tool", set final_response to "" and put one or more tool calls in tool_calls.
"""


# ---------------------------------------------------------------------------
# Reason node — the LLM decision step in the graph.
# ---------------------------------------------------------------------------

def build_reason_node(llm):
    """Return a reason node function ready to be added to a LangGraph StateGraph."""

    def reason_node(state):
        print("\nReasoning with LLM...")
        print(f"[reason] Tool catalog:\n{state['tool_catalog']}")
        
        # Build dynamic system prompt with session context
        system_prompt = SYSTEM_PROMPT
        
        # Inject session context if available
        session_context = ""
        
        # Show available candidates from previous search
        if state.get("candidate_layouts"):
            candidates_str = "\n".join([
                f"  - layout: {c['layoutId']}, score: {c['score']}"
                for c in state.get("candidate_layouts", [])
            ])
            session_context += f"\n## Available Candidates from Previous Search\n{candidates_str}"
        
        if state.get("layout_id"):
            session_context += f"\n## Currently Selected Layout\n- Working on: {state['layout_id']}"
        
        if state.get("last_action"):
            session_context += f"\n- Last action: {state['last_action']}"
        
        if session_context:
            system_prompt = system_prompt + session_context
            print(f"[reason] Session context injected into prompt")
        
        print(f"[reason] System prompt length: {len(system_prompt)} chars")
        print(f"[reason] Messages count: {len(state['messages'])}")
        for i, msg in enumerate(state["messages"]):
            print(f"  Message {i} ({msg.get('role', '?')}): {len(msg.get('content', ''))} chars")
        
        result = call_llm(llm, system_prompt, state["messages"], state["tool_catalog"])
        
        print(f"[reason] LLM result type: {type(result)}")
        print(f"[reason] LLM result: {result}")
        
        if not isinstance(result, dict):
            raise RuntimeError(f"Expected dict from call_llm, got {type(result)}: {result}")

        # If the LLM decided no more actions are needed (action is final), set the final response in the state and clear pending tool calls
        if result["action"] == "final":
            print(f"[reason] Agent decided: FINAL - {result['final_response'][:100]}...")
            state["final_response"] = result["final_response"]
            state["pending_tool_calls"] = None

        # If the LLM decided the action is to use a tool, set the pending tool calls
        else:
            print(f"[reason] Agent decided: TOOL - {[t['name'] for t in result['tool_calls']]}")
            state["pending_tool_calls"] = result["tool_calls"]

        return state

    return reason_node
