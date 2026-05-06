from __future__ import annotations
import json
from pathlib import Path
from typing import Any, TypedDict
from langgraph.graph import END, START, StateGraph
from nodes.reason import build_reason_node
from nodes.tools import build_tool_node
from nodes.local_tools import get_local_tools, build_local_tool_node


# =============================================================================
# graph.py — Define the agent graph: state, nodes, and edges.
#
# This is the main file you edit to change how the agent works.
# - AgentState  : the data that flows through the graph
# - build_graph : wires nodes and edges together
# - run_agent   : called from main.py; builds and runs the graph once
# =============================================================================


# ---------------------------------------------------------------------------
# State — the data that every node can read and write.
# ---------------------------------------------------------------------------

class AgentState():
    messages: list[dict[str, Any]]       # full conversation history
    pending_tool_calls: list[dict[str, Any]] | None  # tool calls queued by the reason node
    final_response: str | None           # set when the agent is done
    iteration: int                       # current tool-call count
    max_iterations: int                  # safety cap to stop the process (set from .env)
    tool_catalog: str                    # formatted list of available MCP tools
    layout_json_string: str              # current layout as a JSON string, injected into tool calls
    candidate_layouts: list[dict[str, Any]] | None  # search results with layoutId and score
    layout_id: str | None                # which layout is selected (persisted to session)
    last_action: str | None              # brief summary of last action (persisted to session)

# ---------------------------------------------------------------------------
# Routing — decides which node runs next after "reason".
# ---------------------------------------------------------------------------

def _route(state: AgentState) -> str:
    if state["final_response"] is not None:
        return "finish"
    
    # Check if any pending tool calls are local tools
    if state["pending_tool_calls"]:
        for call in state["pending_tool_calls"]:
            if call["name"] in ["layout_filter", "layout_matcher"]:
                return "local_tool"
    
    return "run_tool"


# ---------------------------------------------------------------------------
# Graph wiring — add nodes and edges here.
# ---------------------------------------------------------------------------

def build_graph(ctx: Any) -> Any:
    # Create the state graph
    # Use the reason and tool nodes
    reason = build_reason_node(ctx.llm)
    tool = build_tool_node(ctx.mcp_client, ctx.tools, ctx.edited_layout_path)
    local_tool = build_local_tool_node()

    # Initialize the graph
    graph = StateGraph(AgentState)

    # Add the nodes
    graph.add_node("reason", reason)
    graph.add_node("tool", tool)
    graph.add_node("local_tool", local_tool)

    # Add the edges
    graph.add_edge(START, "reason")
    graph.add_conditional_edges("reason", _route, {"run_tool": "tool", "local_tool": "local_tool", "finish": END})
    graph.add_edge("tool", "reason")
    graph.add_edge("local_tool", "reason")

    return graph.compile()


# ---------------------------------------------------------------------------
# Entry point — called from main.py.
# ---------------------------------------------------------------------------

def run_agent(prompt: str, ctx: Any, session_state: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    app = build_graph(ctx)

    initial_state = _build_initial_state(prompt, ctx, session_state)
    final_state = app.invoke(initial_state)

    # Uncomment these two lines to see the graph structure in the terminal
    print("\nWorkflow graph:")
    app.get_graph().print_ascii()

    final_response = final_state.get("final_response")
    if not isinstance(final_response, str):
        raise RuntimeError("Agent finished without a final response")
    
    # Return both the response and the full state (for session persistence)
    return final_response, final_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_initial_state(prompt: str, ctx: Any, session_state: dict[str, Any] | None = None) -> AgentState:
    # Restore persistent state from session if available
    layout_id = None
    candidate_layouts = None
    last_action = None
    layout_text = json.dumps(ctx.layout_data, indent=2)  # default layout
    
    if session_state:
        layout_id = session_state.get("layout_id")
        candidate_layouts = session_state.get("candidate_layouts")
        last_action = session_state.get("last_action")
        
        # If we have a layout ID, load that specific layout instead of default
        if layout_id:
            try:
                team_dir = Path(__file__).resolve().parent.parent
                layouts_path = team_dir / "layout_inputs" / "sample_layouts.json"
                all_layouts = json.loads(layouts_path.read_text(encoding="utf-8"))
                
                # Find the layout by ID
                for layout in all_layouts:
                    if layout.get("layoutId") == layout_id:
                        layout_text = json.dumps(layout, indent=2)
                        print(f"[graph] Loaded selected layout: {layout_id}")
                        break
            except Exception as e:
                print(f"[graph] Warning: Could not load layout {layout_id}: {e}")
                layout_text = json.dumps(ctx.layout_data, indent=2)
        
        if layout_id or candidate_layouts or last_action:
            print(f"[graph] Restored session: candidates={len(candidate_layouts or [])}, layout={layout_id}, last_action={last_action}")
    
    # Get local tools
    local_tools = get_local_tools()
    
    # Combine local tools with MCP tools for the tool catalog
    combined_tools = local_tools + ctx.tools
    tool_catalog = _format_tool_catalog(combined_tools)

    # Engineer the user message
    user_message = (
        "Context: the current layout is JSON below. "
        "Valid room names are rooms[].name.\n\n"
        f"User request:\n{prompt}\n\n"
        f"Current layout JSON:\n{input_layout_text}"
    )

    return {
        "messages": [{"role": "user", "content": user_message}],
        "pending_tool_calls": None,
        "final_response": None,
        "iteration": 0,
        "max_iterations": ctx.max_iterations,
        "tool_catalog": tool_catalog,
        "layout_json_string": layout_text,
        "candidate_layouts": candidate_layouts,
        "layout_id": layout_id,
        "last_action": last_action,
    }

# Helper function to prepare the tool catalog for the LLM (compact format)
def _format_tool_catalog(tools: list[dict[str, Any]]) -> str:
    lines = []
    for tool in tools:
        name = tool.get("name", "<unknown>")
        description = tool.get("description", "")
        schema = tool.get("inputSchema", {})
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        
        # Build param list: show parameter names and whether required
        params = []
        for prop_name in properties.keys():
            marker = "*" if prop_name in required else ""
            params.append(f"{prop_name}{marker}")
        
        param_str = f"({', '.join(params)})" if params else ""
        lines.append(f"- {name}{param_str}: {description}")
    
    return "\n".join(lines)

