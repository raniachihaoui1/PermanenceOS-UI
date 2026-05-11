from __future__ import annotations
import json
from typing import Any, TypedDict
from langgraph.graph import END, START, StateGraph
from nodes.reason import build_reason_node
from nodes.tools import build_tool_node


class AgentState():
    messages: list[dict[str, Any]]
    pending_tool_calls: list[dict[str, Any]] | None
    final_response: str | None
    iteration: int
    max_iterations: int
    tool_catalog: str
    layout_json_string: str


def _route(state: AgentState) -> str:
    if state["final_response"] is not None:
        return "finish"
    return "run_tool"


def build_graph(ctx: Any) -> Any:
    reason = build_reason_node(ctx.llm)
    tool = build_tool_node(ctx.mcp_client, ctx.tools, ctx.edited_layout_path)

    graph = StateGraph(AgentState)
    graph.add_node("reason", reason)
    graph.add_node("tool", tool)
    graph.add_edge(START, "reason")
    graph.add_conditional_edges("reason", _route, {"run_tool": "tool", "finish": END})
    graph.add_edge("tool", "reason")

    return graph.compile()


def run_agent(prompt: str, ctx: Any) -> str:
    app = build_graph(ctx)
    initial_state = _build_initial_state(prompt, ctx)
    final_state = app.invoke(initial_state)

    print("\nWorkflow graph:")
    app.get_graph().print_ascii()

    final_response = final_state.get("final_response")
    if not isinstance(final_response, str):
        raise RuntimeError("Agent finished without a final response")
    return final_response


def _build_initial_state(prompt: str, ctx: Any) -> AgentState:

    layout_data = ctx.layout_data

    if isinstance(layout_data, list):
        layout_ids = [l.get("layoutId") for l in layout_data]
        user_message = (
            f"There are {len(layout_ids)} layouts: {layout_ids}. "
            f"Call the tool once per layout.\n\nRequest: {prompt}"
        )
    else:
        user_message = f"Request: {prompt}"

    return {
        "messages": [{"role": "user", "content": user_message}],
        "pending_tool_calls": None,
        "final_response": None,
        "iteration": 0,
        "max_iterations": ctx.max_iterations,
        "tool_catalog": _format_tool_catalog(ctx.tools),
        "layout_json_string": json.dumps(layout_data),
    }


def _format_tool_catalog(tools: list[dict[str, Any]]) -> str:
    skip = {"compute_volume_of_sphere", "compute_area_of_sphere",
            "compute_volume_of_cone", "compute_volume_of_box"}
    lines = []
    for tool in tools:
        name = tool.get("name", "<unknown>")
        if name in skip:
            continue
        description = tool.get("description", "")
        schema = json.dumps(tool.get("inputSchema", {}))
        lines.append(f"- {name}: {description} | inputSchema={schema}")
    return "\n".join(lines)