from __future__ import annotations

import json
import re
from typing import Any, TypedDict

from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from mcp_client import McpClient


class AgentState(TypedDict):
    messages: list[dict[str, str]]
    pending_tool_name: str | None
    pending_tool_arguments: dict[str, Any] | None
    final_response: str | None
    iteration: int
    max_iterations: int
    tool_catalog: str


SYSTEM_PROMPT = """You are a tool-using assistant.
You can either answer directly or request one MCP tool call.

Available tools:
{tool_catalog}

Return strictly valid JSON with exactly one of the following shapes:
1) {{"action": "final", "final_response": "..."}}
2) {{"action": "tool", "tool_name": "<tool-name>", "arguments": {{...}}}}
"""


def _parse_llm_json(content: str) -> dict[str, Any]:
    fenced_match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", content, flags=re.IGNORECASE)
    if fenced_match is not None:
        fenced_payload = fenced_match.group(1)
        parsed_fenced = json.loads(fenced_payload)
        if not isinstance(parsed_fenced, dict):
            raise RuntimeError("LLM JSON response must be an object")
        return parsed_fenced

    decoder = json.JSONDecoder()
    json_start = content.find("{")
    if json_start == -1:
        raise RuntimeError("LLM response did not include a JSON object")

    parsed, _ = decoder.raw_decode(content, idx=json_start)
    if not isinstance(parsed, dict):
        raise RuntimeError("LLM JSON response must be an object")
    return parsed


def _normalize_llm_decision(parsed: dict[str, Any]) -> dict[str, Any]:
    if "action" in parsed:
        action_value = parsed["action"]
        if action_value not in {"final", "tool"}:
            raise RuntimeError("LLM action must be either 'final' or 'tool'")
        return parsed

    # Support tool-call decisions that omit explicit action.
    if "tool_name" in parsed and "arguments" in parsed:
        return {
            "action": "tool",
            "tool_name": parsed["tool_name"],
            "arguments": parsed["arguments"],
        }

    if "tool_call" in parsed and isinstance(parsed["tool_call"], dict):
        tool_call = parsed["tool_call"]
        return {
            "action": "tool",
            "tool_name": tool_call.get("name"),
            "arguments": tool_call.get("arguments"),
        }

    if "tool_calls" in parsed and isinstance(parsed["tool_calls"], list) and parsed["tool_calls"]:
        first_call = parsed["tool_calls"][0]
        if isinstance(first_call, dict):
            return {
                "action": "tool",
                "tool_name": first_call.get("name"),
                "arguments": first_call.get("arguments"),
            }

    # Support direct-answer decisions that omit explicit action.
    if "final_response" in parsed:
        return {
            "action": "final",
            "final_response": parsed["final_response"],
        }

    raise RuntimeError(f"LLM decision missing required fields: {parsed}")


def _format_tools(tools: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for tool in tools:
        name = str(tool.get("name", "<unknown>"))
        description = str(tool.get("description", ""))
        input_schema = json.dumps(tool.get("inputSchema", {}))
        lines.append(f"- {name}: {description} | inputSchema={input_schema}")
    return "\n".join(lines)


def build_initial_state(user_prompt: str, tools: list[dict[str, Any]], max_iterations: int) -> AgentState:
    return {
        "messages": [{"role": "user", "content": user_prompt}],
        "pending_tool_name": None,
        "pending_tool_arguments": None,
        "final_response": None,
        "iteration": 0,
        "max_iterations": max_iterations,
        "tool_catalog": _format_tools(tools),
    }


def run_agent(
    user_prompt: str,
    tools: list[dict[str, Any]],
    mcp_client: McpClient,
    openai_api_key: str,
    openai_base_url: str,
    openai_model: str,
    debug_graph: bool,
    timeout_seconds: float,
    max_iterations: int,
) -> str:
    def dbg(message: str) -> None:
        if debug_graph:
            print(message)

    dbg("[graph] Initializing agent graph")
    dbg(f"[graph] Model: {openai_model}")
    dbg(f"[graph] Max iterations: {max_iterations}")

    llm = ChatOpenAI(
        api_key=openai_api_key,
        base_url=openai_base_url,
        model=openai_model,
        timeout=timeout_seconds,
        temperature=0,
    )

    def reason_node(state: AgentState) -> AgentState:
        dbg(f"[graph][reason] Enter node | iteration={state['iteration']} | messages={len(state['messages'])}")
        system_prompt = SYSTEM_PROMPT.format(tool_catalog=state["tool_catalog"])
        llm_messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}] + state["messages"]

        result = llm.invoke(llm_messages)
        content = result.content
        if not isinstance(content, str):
            raise RuntimeError("LLM response content must be a string")

        parsed = _normalize_llm_decision(_parse_llm_json(content))
        dbg(f"[graph][reason] Parsed decision: {parsed}")

        action = parsed["action"]
        if action == "final":
            final_response = parsed["final_response"]
            if not isinstance(final_response, str):
                raise RuntimeError("final_response must be a string")

            state["final_response"] = final_response
            state["pending_tool_name"] = None
            state["pending_tool_arguments"] = None
            dbg("[graph][reason] Decision=final")
            return state

        if action == "tool":
            tool_name = parsed["tool_name"]
            arguments = parsed["arguments"]
            if not isinstance(tool_name, str):
                raise RuntimeError("tool_name must be a string")
            if not isinstance(arguments, dict):
                raise RuntimeError("arguments must be an object")

            state["pending_tool_name"] = tool_name
            state["pending_tool_arguments"] = arguments
            dbg(f"[graph][reason] Decision=tool | tool_name={tool_name} | arguments={arguments}")
            return state

        raise RuntimeError("LLM action must be either 'final' or 'tool'")

    def tool_node(state: AgentState) -> AgentState:
        dbg("[graph][tool] Enter node")
        if state["pending_tool_name"] is None or state["pending_tool_arguments"] is None:
            raise RuntimeError("Tool node called without pending tool call")

        state["iteration"] += 1
        if state["iteration"] > state["max_iterations"]:
            raise RuntimeError("Max iterations exceeded")

        dbg(
            f"[graph][tool] Calling tool | iteration={state['iteration']} | "
            f"name={state['pending_tool_name']} | args={state['pending_tool_arguments']}"
        )

        tool_output = mcp_client.call_tool(state["pending_tool_name"], state["pending_tool_arguments"])
        dbg(f"[graph][tool] Tool output: {tool_output}")

        state["messages"].append(
            {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "tool_call": {
                            "name": state["pending_tool_name"],
                            "arguments": state["pending_tool_arguments"],
                        }
                    }
                ),
            }
        )
        state["messages"].append(
            {
                "role": "user",
                "content": f"Tool result: {tool_output}",
            }
        )

        state["pending_tool_name"] = None
        state["pending_tool_arguments"] = None
        return state

    def route_after_reason(state: AgentState) -> str:
        if state["final_response"] is not None:
            dbg("[graph][route] reason -> finish")
            return "finish"
        dbg("[graph][route] reason -> run_tool")
        return "run_tool"

    graph = StateGraph(AgentState)
    graph.add_node("reason", reason_node)
    graph.add_node("tool", tool_node)
    graph.add_edge(START, "reason")
    graph.add_conditional_edges(
        "reason",
        route_after_reason,
        {
            "run_tool": "tool",
            "finish": END,
        },
    )
    graph.add_edge("tool", "reason")

    app = graph.compile()
    dbg("[graph] Graph compiled")

    final_state = app.invoke(build_initial_state(user_prompt, tools, max_iterations))
    dbg(f"[graph] Final state: {final_state}")
    final_response = final_state.get("final_response")
    if not isinstance(final_response, str):
        raise RuntimeError("Agent finished without a final response")

    dbg("[graph] Completed successfully")

    return final_response
