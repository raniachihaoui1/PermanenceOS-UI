from __future__ import annotations
import json
from typing import Any
from _runtime.llm import call_llm
import time


SYSTEM_PROMPT = """You are a structural memory assistant for an architect making early design decisions.

Your role is to make structural consequences legible before decisions become irreversible. You do not design or calculate loads. You reason about consequences, flag conflicts, and propose alternatives.

LAYOUT CONTEXT:
The layout JSON is loaded from team_01/python/example_layouts/. It defines rooms, walls, doors, windows, structure, and their relationships. Use element IDs and attributes exactly as given. Never invent elements.

STRUCTURAL REASONING RULES:
- Columns and load-bearing walls are permanent — flag any request to remove them
- Beams connect columns — removing a beam may require adding an alternative load path
- Grid spacing affects which rooms can be reconfigured
- Always flag MEP conflicts when adding structural elements

GRAPH ROUTING RULES (must follow):
- Check structure_count on every request before deciding.
- If structure_count=0: set action="tool" and call tag_and_audit to create the structural grid from scratch.
- If structure_count>0: never regenerate grid.
- After CREATE GRID: evaluate runs automatically.
- After MODIFY: evaluate runs automatically.
- For question-only requests: set action="final" and answer directly.
- For explicit evaluation requests: set action="final" with final_response="".
- Never modify without a prior evaluate result in state.

TAG_AND_AUDIT USAGE:
- If structure_count=0 (grid does not exist): call tag_and_audit with typology="column_grid".
- If structure_count=0 and user did not provide grid spacing: use grid_spacing=4.0.
- If structure_count>0: you may call tag_and_audit for read/tag checks, but NEVER pass grid_spacing.
- Pass layout_json exactly from state — never simplify or invent it.

WHAT-IF QUESTIONS — two-step process, NEVER call a tool:
Step 1: User asks "what if we remove X" → set action="final", final_response="" (empty string). The evaluate node runs the simulation automatically.
Step 2: You receive a message starting with "STRUCTURAL FAIL after removing" → set action="final" and write the full response in final_response using this EXACT format, filling in values from the STRUCTURAL FAIL message:

"Removing [element_id] extends beam [beam_id] from [original_span]m to [effective_span]m, causing bending stress of [sigma] MPa (limit [allow] MPa). Three options to resolve this:
1. Add an intermediate column between [col_id_A] and [col_id_B] at the midpoint. This halves the effective span to [effective_span/2]m.
2. Replace beam [beam_id] with a deeper section to handle the extended span.
3. Add a transfer beam from an adjacent column to redirect the load path."

CRITICAL: Use ONLY the beam IDs and column IDs that appear in the STRUCTURAL FAIL message. Never invent element IDs.

REGULAR STRUCTURAL FAILURE RESPONSE:
When you receive a message "User instruction after structural failure" AND the conversation contains "Structural evaluation (first principles)":
- Read the BEAMS section of the evaluation to find which beam IDs failed and what check failed (BEND, SHEAR, DEFL_TL, DEFL_LL)
- Read the COLUMNS section to find which column IDs failed
- Set action="final" and write specific options using ONLY those exact element IDs from the evaluation
- Do NOT use the what-if span-extension format above — that is only for column removal simulations

For DEFLECTION failures (DEFL_TL or DEFL_LL): propose (1) adding a midspan column between the beam's endpoint columns to halve the span, (2) upgrading to the next IPE/RCC/Timber section tier, (3) reducing the tributary width by adding a parallel beam.
For BENDING failures (BEND): propose (1) upgrading to the next section tier, (2) adding a column at the midspan location.
For SHEAR failures (SHEAR): propose (1) increasing section width, (2) adding a column near the support.
For COLUMN stress/buckling failures: propose (1) upgrading column section, (2) reducing floor area tributary to that column.

Never guess element IDs. If a beam is named "CD_1" in the evaluation, use "CD_1" exactly.

GENERAL QUESTIONS (what rooms exist, what conflicts exist, what is permanent):
Answer directly from the layout JSON. Set action="final". Do not call any tool.

MODIFICATIONS (add grid, move element, confirmed change):
Set action="tool" and include the appropriate tool call.

Toolbox:
{tool_catalog}

Return strictly valid JSON:
{{
  "action": "final" | "tool",
  "final_response": "...",
  "tool_calls": [{{"name": "<tool-name>", "arguments": {{...}}}}, ...]
}}

Rules: JSON only, no markdown, no prose outside final_response.
If action is final: tool_calls must be []. If action is tool: final_response must be "".
"""


LLM_ONLY_SYSTEM_PROMPT = """You are a structural design assistant.

You will receive a layout JSON and a user request.
Do not call tools.
Do not mention MCP.
Respond in plain text with the shortest useful answer.
Focus on material selection first, then the candidate grid concept.
"""


def run_llm_only_reasoning(llm: Any, prompt: str, layout_data: dict[str, Any]) -> str:
    # Serialized the layout so the direct LLM path can reason from the input JSON.
    layout_context = json.dumps(layout_data, indent=2, ensure_ascii=False)
    # Serialized the layout so the LLM can reason directly from the input JSON.
    # Built the single user message that carries both the request and the layout context.
    messages = [
        {"role": "user", "content": f"User request:\n{prompt}\n\nLayout JSON:\n{layout_context}"},
    ]
    # Built a single user message because this path intentionally skips the graph and tools.
    # Invoked the model with a plain system prompt and the user request.
    response = llm.invoke([
        {"role": "system", "content": LLM_ONLY_SYSTEM_PROMPT},
        *messages,
    ])
    # Sent the plain-text prompt directly to the model without any MCP/tool workflow.
    # Read the model output in a way that works for LangChain response objects.
    content = getattr(response, "content", "")
    # Read the model output while tolerating client objects that expose content as an attribute.
    # Returned a string regardless of whether the model content came back as text or another type.
    return content if isinstance(content, str) else str(content)
    # Returned the text response so main.py can print it directly.


def build_reason_node(llm):

    def _enforce_routing_policy(state: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        layout = json.loads(state.get("layout_json_string") or "{}")
        structure_count = len(layout.get("structure", [])) if isinstance(layout, dict) else 0
        evaluation_present = state.get("evaluation_result") is not None

        if result.get("action") == "tool":
            tool_calls = result.get("tool_calls") or []
            sanitized = []

            for call in tool_calls:
                name = call.get("name")
                arguments = dict(call.get("arguments") or {})

                if name == "tag_and_audit":
                    if structure_count == 0:
                        arguments.setdefault("typology", "column_grid")
                        arguments.setdefault("grid_spacing", 4.0)
                    else:
                        arguments.pop("grid_spacing", None)

                sanitized.append({"name": name, "arguments": arguments})

            result["tool_calls"] = sanitized

            # Enforce first-time grid creation when no structure exists.
            if structure_count == 0:
                has_create_call = any(call.get("name") == "tag_and_audit" for call in sanitized)
                if not has_create_call:
                    result["tool_calls"] = [{
                        "name": "tag_and_audit",
                        "arguments": {"typology": "column_grid", "grid_spacing": 4.0},
                    }]

            # Do not modify existing structure before any evaluation has run.
            if structure_count > 0 and not evaluation_present:
                result["action"] = "final"
                result["final_response"] = ""
                result["tool_calls"] = []

        return result

    def reason_node(state):
        cycle = state.get("cycle", 0)
        print(f"\n{'='*50}")
        print(f"  NODE: REASON  (cycle {cycle})")
        print(f"{'='*50}")

        # Trim history to stay within token limit
        # Cap each message at 600 chars so tool results (full layout JSON) don't blow the context
        def _cap(msg: dict, limit: int = 600) -> dict:
            c = msg.get("content", "")
            return {**msg, "content": c[:limit] + " ...[trimmed]"} if len(c) > limit else msg

        messages = state["messages"]
        kept = (messages[:1] + messages[-3:]) if len(messages) > 4 else messages
        trimmed_messages = [_cap(m) for m in kept]

        result = None
        last_error = None

        for attempt in range(3):
            try:
                result = call_llm(llm, SYSTEM_PROMPT, trimmed_messages, state["tool_catalog"])
                break
            except RuntimeError as e:
                if "non-empty 'tool_calls'" in str(e):
                    result = {"action": "final", "final_response": ""}
                    break
                last_error = e
                if attempt < 2:
                    wait = 5 * (attempt + 1)
                    print(f"LLM call failed (attempt {attempt+1}/3), retrying in {wait}s... {e}")
                    time.sleep(wait)
            except Exception as e:
                last_error = e
                if attempt < 2:
                    wait = 5 * (attempt + 1)
                    print(f"LLM call failed (attempt {attempt+1}/3), retrying in {wait}s... {e}")
                    time.sleep(wait)

        if result is None:
            raise RuntimeError(f"LLM failed after 3 attempts: {last_error}")

        result = _enforce_routing_policy(state, result)

        if result["action"] == "final":
            state["final_response"] = result["final_response"]
            state["pending_tool_calls"] = None
        else:
            state["pending_tool_calls"] = result["tool_calls"]
            state["final_response"] = None

        state["came_from"] = "reason"
        return state

    return reason_node