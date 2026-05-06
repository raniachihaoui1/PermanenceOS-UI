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
  - DO NOT call layout_filter directly.
- If "Available Candidates from Previous Search" exists: Previous search found layouts.
  - **IMPORTANT**: Do NOT auto-call layout_filter. User will choose which to inspect.
  - If user says "select layout-X" or "work on layout-X" explicitly → Call layout_filter with that layoutId.
  - If user says "search for..." or "find..." → Call layout_graph_search again for new search.
  - Otherwise: Return candidates as final response so user can decide what to do next.

**Step 1: Does user EXPLICITLY ask to FIND or SEARCH a layout?**
- Examples: "find 2-bedroom", "search for layout", "show me layouts with", "find a layout"
- Only if NO current_layout_id and NO candidate_layouts.
- Action: Call layout_graph_search with programs list (can include duplicates for counts)
- After search: Return the candidates to user as final response (DO NOT auto-call filter)
- User will then choose which one to examine

**Step 2: Does user provide a LAYOUT ID directly?**
- Examples: "filter layout-1", "use layout-5", "work on layout-1"
- Action: Call layout_filter(layout_id=...) directly

**Step 3: Does user ask for MODIFICATIONS/DELETION on the current layout?**
- Examples: "delete the kitchen", "remove bedroom", "change window", "add window"
- Current layout JSON is provided in the user message
- Action: Call appropriate MCP tools directly

## Key Rules
- NEVER call layout_filter directly unless user explicitly asks for a specific layout ID.
- If session context exists, assume the user is continuing their previous interaction.
- Session context (selected layout + candidates) overrides all other logic.
- Always use layout_graph_search for room-based queries.

## Graph Search (Unified Topology Matching)

Build a pattern graph and search layouts by graph similarity (edge matching):

**Two connection modes:**
1. **"any"** - Rooms must exist (any edge configuration allowed)
   - "find layouts with 2 bedrooms, kitchen, living"
   - Programs: ["bed", "bed", "kitchen", "living"], connection_type: "any"

2. **"connected"** - Rooms must ALL be interconnected via doors (complete subgraph)
   - "find layouts where 2 bedrooms, kitchen, and living are all connected"
   - "find open floor plan with kitchen and living"
   - Programs: ["bed", "bed", "kitchen", "living"], connection_type: "connected"

**Examples:**
- Input: "I want a 3-bedroom with kitchen and living room"
  → layout_graph_search(programs=["bed", "bed", "bed", "kitchen", "living"], connection_type="any")
- Input: "find layout with 2-bed open kitchen-living area"
  → layout_graph_search(programs=["bed", "bed", "kitchen", "living"], connection_type="connected")
- Input: "show me layouts with 2 bathrooms and entry"
  → layout_graph_search(programs=["bath", "bath", "entry"], connection_type="any")

## How to Parse Room Type Queries
When user asks for layouts with specific rooms, build a pattern graph for unified topology matching:

**CRITICAL: Count Matters!**
- "2-bedroom" → ['bed', 'bed'] (include 2 duplicates)
- "3 bathrooms" → ['bath', 'bath', 'bath'] (include 3 duplicates)  
- "one bed + kitchen" → ['bed', 'kitchen'] (no duplicates)
- The programs list preserves count information!

**Connection Keywords (triggers connection_type="connected"):**
- "connected", "accessible", "next to", "near", "open floor plan", "flows into", "connects to", "opens to", "adjoins", "via door", "all interconnected"
- "open kitchen-living" (implied connection)
- "bedroom with ensuite" (implies adjacent bath)

**Parsing Rules:**
1. Extract room types WITH DUPLICATES ("2 bed" → ['bed', 'bed'], NOT ['bed'])
2. Ignore adjectives and decorative words: "open kitchen" → ["kitchen"]
3. Extract only normalized room types
4. **Detect connection keywords** to choose connection_type ("any" default, "connected" if keywords found)

**Room Type Normalization:**
- "2-bedroom", "bedroom", "sleeping room" → "bed"
- "kitchen", "kitchenette" → "kitchen"
- "living room", "living space" → "living"
- "bathroom", "bath", "washroom" → "bath"
- "dining room", "dining area" → "dining"
- "entry", "foyer", "entrance" → "entry"

**Examples:**
- Input: "I want a 3-bedroom apartment with kitchen and living room"
  → layout_graph_search(programs=["bed", "bed", "bed", "kitchen", "living"], connection_type="any")
- Input: "find layout with bed connected to kitchen"
  → layout_graph_search(programs=["bed", "kitchen"], connection_type="connected")
- Input: "find layout with 2 bathrooms and entry"
  → layout_graph_search(programs=["bath", "bath", "entry"], connection_type="any")
- Input: "show me layouts with open kitchen-living area"
  → layout_graph_search(programs=["kitchen", "living"], connection_type="connected")

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
