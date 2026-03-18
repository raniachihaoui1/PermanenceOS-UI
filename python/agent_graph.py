# =============================================================================
# agent_graph.py — The "brain" of the AI agent
# =============================================================================
#
# WHAT THIS FILE DOES:
#   This file defines how the AI agent thinks and acts. The agent follows a
#   simple loop:
#
#     1. REASON  — The AI reads your question and the list of available tools,
#                  then decides what to do next: either call a tool or give a
#                  final answer.
#
#     2. TOOL    — If the AI decided to call a tool, this step runs that tool
#                  (e.g. a Grasshopper calculation) and hands the result back
#                  to the AI so it can keep going.
#
#     3. REPEAT  — Steps 1–2 repeat until the AI has everything it needs to
#                  give a complete final answer.
#
#   The structure of this loop is called a "graph" (hence the filename). The
#   graph is built with a library called LangGraph.
#
# KEY PIECES YOU MIGHT WANT TO CHANGE:
#
#   SYSTEM_PROMPT (line ~25)
#     This is the instruction sheet the AI reads before every conversation.
#     Change this text to give the AI a different personality, more specific
#     rules, or a different output format. For example:
#       - "Always respond in bullet points."
#       - "You are an expert structural engineer assistant."
#       - "Return results as a JSON object."
#
#   max_iterations (passed in from main.py)
#     This is the maximum number of tool calls the agent is allowed to make
#     before it is forced to stop. Raise it if your task needs many tool calls;
#     lower it to keep things fast and cheap.
#
#   route_after_reason (line ~195)
#     This is the decision function that chooses which step comes next in the
#     graph. If you wanted the agent to do something different after calling a
#     tool — for example, a validation step before looping back — you would
#     add a new node and wire it in here.
#
#   Adding a new node
#     To add a new step to the agent loop (e.g. a "summarize" step after the
#     final answer), you would:
#       1. Write a new function like `def summarize_node(state): ...`
#       2. Register it:  graph.add_node("summarize", summarize_node)
#       3. Wire it in:   graph.add_edge("reason", "summarize")
#                        graph.add_edge("summarize", END)
#
# =============================================================================

from __future__ import annotations

import json
from typing import Any, TypedDict

from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from mcp_client import McpClient


class AgentState(TypedDict):
    messages: list[dict[str, str]]
    pending_tool_calls: list[dict[str, Any]] | None
    final_response: str | None
    iteration: int
    max_iterations: int
    tool_catalog: str


SYSTEM_PROMPT = """You are a tool-using assistant.
You can either answer directly or request one MCP tool call.

Available tools:
{tool_catalog}

Return strictly valid JSON with exactly one of the following shapes:
1) {{"final_response": "..."}}
2) {{"tool_call": {{"name": "<tool-name>", "arguments": {{...}}}}}}
3) {{"tool_calls": [{{"name": "<tool-name>", "arguments": {{...}}}}, ...]}}
If you return tool calls, use exactly one JSON object.
"""


def _format_node_label(node_id: int, node_type: str, detail: str) -> str:
    if detail:
        return f"[{node_id:02d}] {node_type}: {detail}"
    return f"[{node_id:02d}] {node_type}"


def _extract_tool_sequence(messages: list[dict[str, str]]) -> list[str]:
    tool_names: list[str] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content", "")

        if role == "assistant":
            parsed = json.loads(content)
            tool_call = parsed.get("tool_call")
            if isinstance(tool_call, dict):
                tool_name = tool_call["name"]
                tool_names.append(tool_name)

    return tool_names


def _print_execution_graph_ascii(messages: list[dict[str, str]], final_response: str) -> None:
    print("\nExecution graph (ASCII):")

    nodes: list[str] = []
    node_id = 1
    nodes.append(_format_node_label(node_id, "start", "user_prompt"))

    for tool_name in _extract_tool_sequence(messages):
        node_id += 1
        nodes.append(_format_node_label(node_id, "tool", tool_name))

    node_id += 1
    nodes.append(_format_node_label(node_id, "final", "response"))

    print(nodes[0])
    for node in nodes[1:]:
        print("  |")
        print("  v")
        print(node)

    print("\nFinal response summary:")
    print(final_response)


def _parse_llm_json(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise RuntimeError("LLM JSON response must be an object")
        return parsed
    except json.JSONDecodeError as exc:
        if "Extra data" not in str(exc):
            raise

    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("LLM response was empty")

    tool_calls: list[dict[str, Any]] = []
    for line in lines:
        parsed_line = json.loads(line)
        if not isinstance(parsed_line, dict):
            raise RuntimeError("Each JSON line must be an object")
        tool_call = parsed_line.get("tool_call")
        if not isinstance(tool_call, dict):
            raise RuntimeError("Each JSON line must contain 'tool_call'")
        tool_calls.append(tool_call)

    return {"tool_calls": tool_calls}


def _normalize_llm_decision(parsed: dict[str, Any]) -> dict[str, Any]:
    if "final_response" in parsed:
        return {
            "action": "final",
            "final_response": parsed["final_response"],
        }

    tool_call = parsed.get("tool_call")
    if isinstance(tool_call, dict):
        return {
            "action": "tool",
            "tool_calls": [
                {
                    "tool_name": tool_call["name"],
                    "arguments": tool_call["arguments"],
                }
            ],
        }

    tool_calls = parsed.get("tool_calls")
    if isinstance(tool_calls, list) and tool_calls:
        normalized_tool_calls: list[dict[str, Any]] = []
        for tool in tool_calls:
            if not isinstance(tool, dict):
                raise RuntimeError("Each tool call must be an object")
            normalized_tool_calls.append(
                {
                    "tool_name": tool["name"],
                    "arguments": tool["arguments"],
                }
            )
        return {
            "action": "tool",
            "tool_calls": normalized_tool_calls,
        }

    raise RuntimeError("LLM response must include either 'final_response' or 'tool_call'")


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
        "pending_tool_calls": None,
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

        try:
            parsed = _normalize_llm_decision(_parse_llm_json(content))
        except Exception:
            print("\n[graph][reason] Raw LLM response before crash:")
            print(content)
            raise
        dbg(f"[graph][reason] Parsed decision: {parsed}")

        action = parsed["action"]
        if action == "final":
            final_response = parsed["final_response"]

            state["final_response"] = final_response
            state["pending_tool_calls"] = None
            dbg("[graph][reason] Decision=final")
            return state

        if action == "tool":
            tool_calls = parsed["tool_calls"]
            state["pending_tool_calls"] = tool_calls
            dbg(f"[graph][reason] Decision=tool | tool_calls={tool_calls}")
            return state

        raise RuntimeError("LLM action must be either 'final' or 'tool'")

    def tool_node(state: AgentState) -> AgentState:
        dbg("[graph][tool] Enter node")
        if not state["pending_tool_calls"]:
            raise RuntimeError("Tool node called without pending tool call")

        for pending_tool in state["pending_tool_calls"]:
            state["iteration"] += 1
            if state["iteration"] > state["max_iterations"]:
                raise RuntimeError("Max iterations exceeded")

            tool_name = pending_tool["tool_name"]
            tool_arguments = pending_tool["arguments"]

            dbg(
                f"[graph][tool] Calling tool | iteration={state['iteration']} | "
                f"name={tool_name} | args={tool_arguments}"
            )

            tool_output = mcp_client.call_tool(tool_name, tool_arguments)
            dbg(f"[graph][tool] Tool output: {tool_output}")

            state["messages"].append(
                {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "tool_call": {
                                "name": tool_name,
                                "arguments": tool_arguments,
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

        state["pending_tool_calls"] = None
        return state

    def route_after_reason(state: AgentState) -> str:
        if state["final_response"] is not None:
            dbg("[graph][route] reason -> finish")
            return "finish"
        dbg("[graph][route] reason -> run_tool")
        return "run_tool"

    # Graph shape (static): START -> reason -> (tool or END), and tool -> reason.
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

    # Runtime path (dynamic): depends on how many tool calls happen for this prompt.
    final_state = app.invoke(build_initial_state(user_prompt, tools, max_iterations))
    dbg(f"[graph] Final state: {final_state}")
    final_response = final_state.get("final_response")
    if not isinstance(final_response, str):
        raise RuntimeError("Agent finished without a final response")

    print("\nAgent graph (ASCII):")
    app.get_graph().print_ascii()
    _print_execution_graph_ascii(final_state["messages"], final_response)

    dbg("[graph] Completed successfully")

    return final_response
