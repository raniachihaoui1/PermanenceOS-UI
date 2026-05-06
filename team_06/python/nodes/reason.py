from __future__ import annotations
from typing import Any
from _runtime.llm import call_llm


# ---------------------------------------------------------------------------
# System prompt — edit this to change how the agent thinks and behaves.
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an assistant that helps users work with a building layout.

## Decision Tree (Priority Order)

**Step 0: Check for ACTIVE SESSION CONTEXT (highest priority)**
- If "Currently Selected Layout" exists: User is working on a specific layout.
  - Action: Call appropriate MCP tools for modifications (delete, add, change, etc.)
  - DO NOT call layout_matcher or layout_filter.
- If "Available Candidates from Previous Search" exists: Previous search found layouts.
  - User wants different layout? Pick one from candidates → Call layout_filter with that layoutId.
  - User wants NEW search? Explicitly say "search for..." → Then call layout_matcher.
  - Otherwise: Modify the currently selected layout with MCP tools.

**Step 1: Does user EXPLICITLY ask to FIND or SEARCH a layout?**
- Examples: "find 2-bedroom", "search for layout", "show me layouts with", "find a layout"
- Only if NO current_layout_id and NO candidate_layouts.
- Action: Call layout_matcher with their description

**Step 2: Does user provide a LAYOUT ID directly?**
- Examples: "filter layout-1", "use layout-5", "work on layout-1"
- Action: Call layout_filter(layout_id=...) directly

**Step 3: Does user ask for MODIFICATIONS/DELETION on the current layout?**
- Examples: "delete the kitchen", "remove bedroom", "change window", "add window"
- Current layout JSON is provided in the user message
- Action: Call appropriate MCP tools directly

## Key Rules
- NEVER call layout_matcher if current_layout_id is set.
- NEVER call layout_matcher if candidate_layouts are available (unless user explicitly asks for NEW search).
- If session context exists, assume the user is continuing their previous interaction.
- Session context (selected layout + candidates) overrides all other logic.

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
