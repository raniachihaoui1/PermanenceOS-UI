from __future__ import annotations
import json
from typing import Any
from langgraph.graph import END, START, StateGraph
from nodes.reason import build_reason_node
from nodes.tools import build_tool_node, handle_select_layout
from nodes.preprocess import build_preprocess_node, needs_layout, detect_intent


# =============================================================================
# graph.py - Define the agent graph: state, nodes, and edges.
# =============================================================================


class AgentState():
    messages: list[dict[str, Any]]
    pending_tool_calls: list[dict[str, Any]] | None
    final_response: str | None
    iteration: int
    max_iterations: int
    tool_catalog: str
    layout_json_string: str
    intent: str
    persona_detected: str | None
    needs_persona_ask: bool


def _route(state: AgentState) -> str:
    if state["final_response"] is not None:
        return "finish"
    return "run_tool"


def build_graph(ctx: Any) -> Any:
    preprocess = build_preprocess_node()
    reason = build_reason_node(ctx.llm)
    tool = build_tool_node(
        ctx.mcp_client,
        ctx.tools,
        ctx.edited_layout_path,
        ctx.layout_input_dir,
    )

    graph = StateGraph(AgentState)
    graph.add_node("preprocess", preprocess)
    graph.add_node("reason", reason)
    graph.add_node("tool", tool)
    graph.add_edge(START, "preprocess")
    graph.add_edge("preprocess", "reason")
    graph.add_conditional_edges("reason", _route, {"run_tool": "tool", "finish": END})
    graph.add_edge("tool", "reason")

    return graph.compile()


def run_agent(prompt: str, ctx: Any) -> str:
    # Pre-empt: if the user's prompt clearly involves a layout but none is
    # loaded yet, run the select_layout pseudo-tool ourselves before the LLM
    # reasons. We mutate ctx.layout_data so _build_initial_state below uses
    # the "layout already loaded" branch - keeps the initial user message
    # consistent (no stale "no layout loaded" text).
    if not ctx.layout_data and needs_layout(prompt, detect_intent(prompt)):
        print("\n[graph] Prompt mentions layout - running select_layout before LLM reasoning.")
        scratch: dict[str, Any] = {"layout_json_string": ""}
        handle_select_layout(ctx.layout_input_dir, scratch)
        if scratch.get("layout_json_string"):
            ctx.layout_data = json.loads(scratch["layout_json_string"])

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
    layout_loaded = bool(ctx.layout_data)

    if layout_loaded:
        # Send the LLM a compact summary, NOT the full layout JSON. The full
        # JSON (with every room's geometry) blows past small-model context
        # windows. The tool node still has the full layout in state and
        # injects it into MCP calls; the LLM only needs room names/ids/types
        # to decide which arguments to pass.
        layout_section = (
            "Current layout (use rooms[].name for valid room names; "
            "the full layout JSON is auto-injected into tool calls):\n"
            f"{_layout_summary(ctx.layout_data)}"
        )
        layout_json_string = json.dumps(ctx.layout_data)
    else:
        layout_section = (
            "No layout is currently loaded. If - and only if - fulfilling the "
            "user's request requires a building layout, call the `select_layout` "
            "tool first; the user will be prompted in the terminal to choose a "
            "JSON file. If the request can be answered without a layout, respond "
            "with action 'final' and skip select_layout."
        )
        layout_json_string = ""

    user_message = (
        f"User request:\n{prompt}\n\n"
        f"{layout_section}"
    )

    return {
        "messages": [{"role": "user", "content": user_message}],
        "pending_tool_calls": None,
        "final_response": None,
        "iteration": 0,
        "max_iterations": ctx.max_iterations,
        "tool_catalog": _format_tool_catalog(ctx.tools),
        "layout_json_string": layout_json_string,
        "intent": "",
        "persona_detected": None,
        "needs_persona_ask": False,
    }


def _format_tool_catalog(tools: list[dict[str, Any]]) -> str:
    # Compact: name, description, and parameter names only. The strict JSON
    # schema in llm.py enforces actual argument structure, so we don't feed
    # the model verbose inputSchema text. Full schemas balloon the prompt
    # past small-model context limits.
    lines = []
    for tool in tools:
        name = tool.get("name", "<unknown>")
        description = tool.get("description", "")
        props = list((tool.get("inputSchema", {}).get("properties") or {}).keys())
        params = ", ".join(props) if props else "(no params)"
        lines.append(f"- {name}: {description} [params: {params}]")
    return "\n".join(lines)


def _layout_summary(layout: dict[str, Any]) -> str:
    """Compact, LLM-friendly summary of a layout - drops geometry arrays."""
    rooms = layout.get("rooms", []) or []
    lines = [
        f"layoutId: {layout.get('layoutId', '?')}",
        f"name: {layout.get('name', '?')}",
        f"rooms ({len(rooms)}):",
    ]
    for r in rooms:
        attrs = r.get("attributes", {}) or {}
        lines.append(
            f"  - id={r.get('id', '?')} "
            f"name=\"{r.get('name', '?')}\" "
            f"type={attrs.get('roomType', '?')} "
            f"area={attrs.get('area', '?')}"
        )
    return "\n".join(lines)
