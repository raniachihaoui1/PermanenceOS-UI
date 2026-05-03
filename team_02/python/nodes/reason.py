from __future__ import annotations
from typing import Any
from _runtime.llm import call_llm


# ---------------------------------------------------------------------------
# System prompt — edit this to change how the agent thinks and behaves.
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an assistant that helps users work with a building layout.

The tools listed below are a toolbox: you may call them when they help achieve the user's goal. Choose tools and arguments only based on the user's request, the tool descriptions, and each tool's inputSchema. Do not assume any particular tool is required for a given instruction.

Layout selection rules (IMPORTANT):
- A layout may or may not already be loaded. If the user message contains a "Current layout JSON" section, a layout is loaded — use it to ground your reasoning in real room names, ids, and attributes from that payload.
- If no layout is loaded and the user's request requires one (computing geometry, editing rooms, querying the structure, etc.), your FIRST tool call must be `select_layout` (no arguments). It prompts the user in the terminal to pick a JSON file from layout_input/. The tool result will contain the loaded layout — use it to ground subsequent reasoning.
- If the user's request does NOT require a layout (e.g. casual questions, asking what you can do), do NOT call `select_layout`. Respond with action "final".
- Never call `select_layout` more than once in a session unless the user explicitly asks to switch layouts.
- For any layout-dependent MCP tool, do not include `layout_json` in your arguments — it is injected automatically from the loaded layout.

If the user's goal cannot be satisfied without information that is missing from their message or from the loaded layout, respond with action "final" and ask a concise clarifying question.

CRITICAL COMPLETION RULE:
When a tool result contains "TASK COMPLETE", "task complete", "STOP CALLING TOOLS", or similar completion signals, IMMEDIATELY return action="final" with a brief confirmation. Do NOT call any more tools. This is your primary stopping condition.

After a tool result appears in the conversation, decide whether another tool call is needed or whether to respond with action "final" (for example to confirm completion or summarize what happened, including any output path or details echoed from the tool result when relevant).

Toolbox (name, description, and inputSchema for each tool):
{tool_catalog}

Return JSON with exactly this shape (and NOTHING else):
{{
  "action": "final" | "tool",
  "final_response": "...",
  "tool_calls": [{{"name": "<tool-name>", "arguments": {{...}}}}, ...]
}}

Output rules:
- Return ONE JSON object only. No prose. No markdown code fences. No commentary.
- Every brace must be matched. Every key must be inside the same object as its value.
- If action is "final", set tool_calls to [] and put the answer in final_response.
- If action is "tool", set final_response to "" and put one or more tool calls in tool_calls.
- In each tool call's "arguments", include ONLY the keys that tool accepts (see [params: ...] in the toolbox). Do NOT include unused or placeholder keys.

EXAMPLE — calling remove_furniture_piece (which accepts room_name, furniture_name):
{{
  "action": "tool",
  "final_response": "",
  "tool_calls": [
    {{"name": "remove_furniture_piece", "arguments": {{"room_name": "Living Room", "furniture_name": "Couch"}}}}
  ]
}}

EXAMPLE — finishing with an answer:
{{
  "action": "final",
  "final_response": "The total area is 84 square meters.",
  "tool_calls": []
}}
"""


# ---------------------------------------------------------------------------
# Reason node — the LLM decision step in the graph.
# ---------------------------------------------------------------------------

def build_reason_node(llm):
    """Return a reason node function ready to be added to a LangGraph StateGraph."""

    def reason_node(state):
        import time
        iter_n = state.get("iteration", 0)
        max_iters = state.get("max_iterations", "?")
        print(f"\nReasoning with LLM... (iteration {iter_n + 1}/{max_iters})")
        
        # Check if we've hit the iteration limit BEFORE calling the LLM
        if iter_n >= max_iters:
            print(f"  Max iterations ({max_iters}) reached. Forcing final response.")
            state["final_response"] = "The agent has reached its maximum iteration limit. The task may require multiple steps or clarification."
            state["pending_tool_calls"] = None
            return state
        
        t0 = time.time()
        result = call_llm(llm, SYSTEM_PROMPT, state["messages"], state["tool_catalog"])
        elapsed = time.time() - t0
        print(f"  LLM responded in {elapsed:.1f}s")

        if result["action"] == "final":
            print(f"  Decision: FINAL -> {result['final_response'][:120]}")
            state["final_response"] = result["final_response"]
            state["pending_tool_calls"] = None
        else:
            tool_summary = ", ".join(
                f"{c.get('name')}({list(c.get('arguments', {}).keys())})"
                for c in result["tool_calls"]
            )
            print(f"  Decision: TOOL -> {tool_summary}")
            state["pending_tool_calls"] = result["tool_calls"]

        return state

    return reason_node
