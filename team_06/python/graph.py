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
    input_layout_json_string: str        # initial layout as JSON string (immutable)
    current_layout_json_string: str | None  # layout being evaluated (mutable, from filter or MCP tools)
    output_layout_json_string: str | None   # final result layout at end of workflow
    candidate_ids_json_string: str | None   # JSON array: [{"layoutId": "L1", "score": 0.95}, ...]
    current_candidate_index: int            # pointer to current candidate being evaluated (0, 1, 2...)

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

def run_agent(prompt: str, ctx: Any) -> str:
    app = build_graph(ctx)

    initial_state = _build_initial_state(prompt, ctx)
    final_state = app.invoke(initial_state)

    # Uncomment these two lines to see the graph structure in the terminal
    print("\nWorkflow graph:")
    app.get_graph().print_ascii()

    final_response = final_state.get("final_response")
    if not isinstance(final_response, str):
        raise RuntimeError("Agent finished without a final response")
    return final_response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_initial_state(prompt: str, ctx: Any) -> AgentState:
    # Convert the layout data to a JSON string
    input_layout_text = json.dumps(ctx.layout_data, indent=2)
    
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
        "input_layout_json_string": input_layout_text,
        "current_layout_json_string": None,
        "output_layout_json_string": None,
        "candidate_ids_json_string": None,
        "current_candidate_index": 0,
    }

# Helper funtion to prepare the tool catalog for the LLM
def _format_tool_catalog(tools: list[dict[str, Any]]) -> str:
    lines = []
    for tool in tools:
        name = tool.get("name", "<unknown>")
        description = tool.get("description", "")
        schema = json.dumps(tool.get("inputSchema", {}))
        lines.append(f"- {name}: {description} | inputSchema={schema}")
    return "\n".join(lines)

