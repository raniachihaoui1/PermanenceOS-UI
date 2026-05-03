from __future__ import annotations
import json
from typing import Any, TypedDict
from langgraph.graph import END, START, StateGraph
from nodes.reason import build_reason_node
from nodes.tools import build_tool_node, handle_select_layout


# Keywords that suggest the user's request needs a layout. Used as a
# deterministic pre-empt because small models (e.g. Llama-3.1-8B) do not
# reliably follow the "call select_layout first" instruction in the system
# prompt and will skip to a layout-dependent tool, hallucinating results.
LAYOUT_INTENT_KEYWORDS: tuple[str, ...] = (
    "layout", "json", "file", "choose", "pick", "select", "load", "open",
    "work on", "work with", "use",
    "room", "kitchen", "bedroom", "bathroom", "living", "guest", "master",
    "wall", "door", "window", "outline", "geometry",
    "area", "size", "measure", "dimension",
    "compute", "calculate", "delete", "remove", "edit", "modify",
    "rename", "change", "update", "move", "resize", "split", "merge",
)


def _prompt_needs_layout(prompt: str) -> bool:
    lower = prompt.lower()
    return any(kw in lower for kw in LAYOUT_INTENT_KEYWORDS)


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


def _route(state: AgentState) -> str:
    if state["final_response"] is not None:
        return "finish"
    return "run_tool"


def build_graph(ctx: Any) -> Any:
    reason = build_reason_node(ctx.llm)
    tool = build_tool_node(
        ctx.mcp_client,
        ctx.tools,
        ctx.edited_layout_dir,
        ctx.layout_input_dir,
    )

    graph = StateGraph(AgentState)
    graph.add_node("reason", reason)
    graph.add_node("tool", tool)
    graph.add_edge(START, "reason")
    graph.add_conditional_edges("reason", _route, {"run_tool": "tool", "finish": END})
    graph.add_edge("tool", "reason")

    return graph.compile()


def run_agent(prompt: str, ctx: Any) -> str:
    # Pre-empt: if the user's prompt clearly involves a layout but none is
    # loaded yet, run the select_layout pseudo-tool ourselves before the LLM
    # reasons. We mutate ctx.layout_data so _build_initial_state below uses
    # the "layout already loaded" branch - keeps the initial user message
    # consistent (no stale "no layout loaded" text).
    if not ctx.layout_data and _prompt_needs_layout(prompt):
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
    
    # Create room ID to name mapping
    room_id_to_name = {}
    for r in rooms:
        room_id = r.get("id", "")
        room_name = r.get("name", "")
        if room_id:
            room_id_to_name[room_id] = room_name
    
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
    
    # Add furniture information
    furniture = layout.get("furniture", []) or []
    if furniture:
        lines.append(f"furniture ({len(furniture)}):")
        for furn in furniture:
            furn_name = furn.get("name", "?")
            furn_attrs = furn.get("attributes", {}) or {}
            room_id = furn_attrs.get("roomId", "")
            room_name = room_id_to_name.get(room_id, "?")
            furn_type = furn_attrs.get("type", "?")
            lines.append(
                f"  - name=\"{furn_name}\" "
                f"type={furn_type} "
                f"room=\"{room_name}\""
            )
    
    return "\n".join(lines)
