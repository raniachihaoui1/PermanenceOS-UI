from __future__ import annotations
import json
from pathlib import Path
from typing import Any, TypedDict
from langgraph.graph import END, START, StateGraph
from nodes.reason import build_reason_node
from nodes.modify import build_modify_node
from nodes.evaluate import build_evaluate_node
from nodes.comparison import build_comparison_node

EXAMPLE_LAYOUTS_DIR = Path(__file__).parent / "example_layouts"


class AgentState(TypedDict):
    messages: list[dict[str, Any]]
    pending_tool_calls: list[dict[str, Any]] | None
    final_response: str | None
    iteration: int
    max_iterations: int
    tool_catalog: str
    layout_json_string: str
    evaluation_result: str | None
    comparison_result: str | None
    came_from: str | None
    original_layout_json_string: str | None
    cycle: int


def _route_from_reason(state: AgentState) -> str:
    if state.get("pending_tool_calls") and state.get("cycle", 0) < 2:
        return "modify"
    if state.get("final_response") or state.get("cycle", 0) >= 2:
        return END
    return "evaluate"


def _route_from_evaluate(state: AgentState) -> str:
    if state.get("came_from") == "modify":
        return "comparison"
    return "reason"


def build_graph(ctx: Any) -> Any:
    reason = build_reason_node(ctx.llm)
    modify = build_modify_node(ctx.mcp_client, ctx.tools, ctx.edited_layout_path)
    evaluate = build_evaluate_node(ctx.llm)
    comparison = build_comparison_node(ctx.llm)

    graph = StateGraph(AgentState)
    graph.add_node("reason", reason)
    graph.add_node("modify", modify)
    graph.add_node("evaluate", evaluate)
    graph.add_node("comparison", comparison)

    graph.add_edge(START, "reason")
    graph.add_conditional_edges("reason", _route_from_reason, {"modify": "modify", "evaluate": "evaluate", END: END})
    graph.add_edge("modify", "evaluate")
    graph.add_conditional_edges("evaluate", _route_from_evaluate, {"reason": "reason", "comparison": "comparison"})
    graph.add_edge("comparison", "reason")

    return graph.compile()


def run_agent(prompt: str, ctx: Any) -> str:
    app = build_graph(ctx)
    initial_state = _build_initial_state(prompt, ctx)
    final_state = app.invoke(initial_state)

    print("\nWorkflow graph:")
    app.get_graph().print_ascii()

    final_response = (
        final_state.get("final_response")
        or final_state.get("comparison_result")
        or ""
    )

    if not final_response and ctx.edited_layout_path.exists():
        final_response = f"Done. Layout saved to {ctx.edited_layout_path.name}"

    return final_response


def _load_all_layouts() -> list[dict[str, Any]]:
    """Load all layouts from example_layouts folder."""
    all_layouts = []
    for json_file in sorted(EXAMPLE_LAYOUTS_DIR.glob("*.json")):
        content = json.loads(json_file.read_text(encoding="utf-8"))
        if isinstance(content, list):
            all_layouts.extend(content)
        else:
            all_layouts.append(content)
    return all_layouts


def _build_initial_state(prompt: str, ctx: Any) -> AgentState:

    layouts = _load_all_layouts()
    layout_ids = [l.get("layoutId", "?") for l in layouts]

    # Send slim summary to LLM to stay within token limit
    slim = []
    for l in layouts:
        slim.append({
            "layoutId": l.get("layoutId"),
            "outline": l.get("outline"),
            "rooms": [{"id": r["id"], "name": r["name"]} for r in l.get("rooms", [])],
            "structure": l.get("structure", []),
        })

    user_message = (
        f"Context: {len(layouts)} layouts loaded from team_01/python/example_layouts/: {layout_ids}.\n"
        f"Valid room names are rooms[].name.\n\n"
        f"User request:\n{prompt}\n\n"
        f"Layout summaries:\n{json.dumps(slim, indent=2)}"
    )

    return {
        "messages": [{"role": "user", "content": user_message}],
        "pending_tool_calls": None,
        "final_response": None,
        "iteration": 0,
        "max_iterations": ctx.max_iterations,
        "tool_catalog": _format_tool_catalog(ctx.tools),
        "layout_json_string": json.dumps(layouts[0] if layouts else {}),
        "evaluation_result": None,
        "comparison_result": None,
        "came_from": None,
        "original_layout_json_string": None,
        "cycle": 0,
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