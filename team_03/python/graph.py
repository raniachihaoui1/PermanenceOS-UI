"""
graph.py — Phase 3 agent graph: state, nodes, edges, and routing.

This is the main file to edit when changing how the agent works.
- AgentState        : all data flowing between nodes
- build_graph       : wires every node and edge together
- run_agent         : called from main.py; builds and runs the graph once
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import Annotated, Any, TypedDict
from langgraph.graph.message import add_messages

from langgraph.graph import END, START, StateGraph

from nodes.reason import build_reason_node
from nodes.tools import build_tool_node
from nodes.add_objects import build_add_objects_node
from nodes.visibility import build_visibility_node
from nodes.path_analysis import build_path_node
from nodes.reachability import build_reachability_node
from nodes.orientation import build_orientation_node
from nodes.collision import build_collision_node
from nodes.scoring import build_scoring_node
from nodes.profile_agent import build_profile_agent_node
from nodes.space_type_agent import build_space_type_agent_node
from _runtime.session import close_session


# ---------------------------------------------------------------------------
# Reducer for parallel node writes.
# When Group 1 nodes (collision, visibility, orientation) run in parallel they
# all return state updates simultaneously. LangGraph requires a reducer for any
# field that more than one parallel branch writes; without one it raises
# InvalidUpdateError. _keep_last takes the last non-None value so a node that
# doesn't touch a field (returns None) never clobbers a sibling's result.
# ---------------------------------------------------------------------------

def _keep_last(a, b):
    return b if b is not None else a


# ---------------------------------------------------------------------------
# State — the data every node can read and write.
# Keys are grouped by concern so it is easy to trace which nodes own each field.
# Fields written by parallel branches are Annotated with _keep_last.
# Fields written only by a single node stay as plain TypedDict fields.
# ---------------------------------------------------------------------------

class AgentState(TypedDict):
    # Core conversation — add_messages merges appended entries rather than
    # replacing the whole list; required because parallel nodes all append.
    messages:            Annotated[list[dict[str, Any]], add_messages]

    # Every node increments iteration and may write pending_tool_calls or
    # final_response — _keep_last prevents InvalidUpdateError from parallel writes.
    pending_tool_calls:  Annotated[list[dict[str, Any]] | None, _keep_last]
    iteration:           Annotated[int,                         _keep_last]
    final_response:      Annotated[str | None,                  _keep_last]

    # Plain fields — written only once at startup, never by parallel branches.
    max_iterations:      int
    tool_catalog:        str

    # Layout and session paths — stable for the lifetime of one run.
    layout_json_string:  str
    workspace_path:      str
    layout_name:         str
    _llm:                Any

    # Pre-agent outputs — written by sequential pre-agents; _keep_last guards
    # against the unlikely case a retry or graph change writes them in parallel.
    space_config:        Annotated[dict[str, Any] | None, _keep_last]
    profile_config:      Annotated[dict[str, Any] | None, _keep_last]

    # Object placement — reason sets these, add_objects clears them.
    object_to_place:       Annotated[dict[str, Any] | None, _keep_last]
    last_placement_result: Annotated[dict[str, Any] | None, _keep_last]

    # Analysis results — collision/visibility/orientation run in parallel;
    # path/reachability are sequential but annotated for future-safety.
    collision_results:    Annotated[dict[str, Any] | None, _keep_last]
    visibility_results:   Annotated[list | None,           _keep_last]
    orientation_results:  Annotated[dict[str, Any] | None, _keep_last]
    path_results:         Annotated[dict[str, Any] | None, _keep_last]
    reachability_results: Annotated[dict[str, Any] | None, _keep_last]

    # Scoring and control — each written by a single node but annotated
    # defensively so any future parallelisation doesn't silently corrupt state.
    scoring_results:     Annotated[dict[str, Any] | None, _keep_last]
    evaluation_passed:   Annotated[bool | None,           _keep_last]
    user_approved:       Annotated[bool | None,           _keep_last]


# ---------------------------------------------------------------------------
# Routing functions — pure state reads, no side effects.
# Each returns a string that matches a key in the conditional_edges map.
# ---------------------------------------------------------------------------

def _route_after_reason(state: AgentState) -> str:
    # Reason node sets exactly one of these fields to signal what should happen next.
    # object_to_place takes priority: place the object before running any analysis.
    if state.get("object_to_place"):
        return "add_objects"
    # final_response means the LLM is done reasoning — move to analysis pipeline.
    if state.get("final_response") is not None:
        return "finish"
    # Default: a tool call was queued; execute it then return to reason.
    return "run_tool"


def _route_after_group1(state: AgentState) -> str:
    # Group 1 = collision + visibility + orientation.
    # Hard violations mean the layout is physically impassable — route back
    # to reason immediately rather than wasting time on path checks.
    # Warnings alone (pass=False, hard_violations=0) do NOT trigger adjustment;
    # they fall through to "continue" so scoring can still penalise them.
    collision = state.get("collision_results")
    if collision and not collision.get("pass", True):
        hard = collision.get("summary", {}).get("hard_violations", 0)
        if hard > 0:
            return "adjust"
    return "continue"


def _route_after_group2(state: AgentState) -> str:
    # Group 2 = path + reachability.
    # If more than 30% of paths are blocked, or fewer than 70% of objects are
    # reachable, the layout needs another adjustment round before scoring.
    path = state.get("path_results")
    if path:
        pairs = path.get("pairs", [])
        unreachable = [p for p in pairs if p.get("status") == "unreachable"]
        if pairs and len(unreachable) > len(pairs) * 0.3:
            return "adjust"

    reach = state.get("reachability_results")
    if reach:
        summary = reach.get("summary", {})
        total    = summary.get("total", 0)
        reachable = summary.get("reachable", 0)
        if total > 0 and reachable / total < 0.7:
            return "adjust"

    return "continue"


def _route_after_checkpoint(state: AgentState) -> str:
    # User either approves the layout (write output and end) or requests more
    # changes (loop back to reason with their new instructions).
    if state.get("user_approved"):
        return "approved"
    return "continue"


# ---------------------------------------------------------------------------
# User checkpoint node — pauses execution to show score and ask for approval.
# ---------------------------------------------------------------------------

def user_checkpoint_node(state: AgentState) -> AgentState:
    # Present the current score to the user and let them decide whether to
    # approve the layout or describe further changes.
    # This is the only node that blocks on user input — all other nodes are
    # fully automated.
    scoring = state.get("scoring_results") or {}
    score = scoring.get("total_score", 0)
    grade = scoring.get("grade", "?")
    rec   = scoring.get("recommendation", "")

    print(f"\n{'=' * 50}")
    print(f"LAYOUT SCORE: {score:.1f}/100  Grade: {grade}")
    print(f"Recommendation: {rec}")
    print(f"{'=' * 50}")
    print("Options:")
    print("  'approve' → save final layout and finish")
    print("  anything else → describe what to change")
    print()

    user_input = input("Your decision: ").strip()

    if user_input.lower() in ("approve", "yes", "ok", "done"):
        state["user_approved"] = True
    else:
        # User wants further changes — inject their message so the reason node
        # picks up their instruction on the next iteration.
        state["user_approved"] = False
        state["messages"].append({"role": "user", "content": user_input})
        # Reset iteration counter so the new round gets the full budget.
        state["iteration"] = 0

    return state


# ---------------------------------------------------------------------------
# Explain node — LLM generates a spatial reasoning summary of the approved layout.
# Runs after user_approved=True and before output so the explanation is
# captured in final_response before the session file is deleted.
# ---------------------------------------------------------------------------


def explain_node(state: AgentState) -> AgentState:
    # Called only once, immediately after the user approves at the checkpoint.
    # The LLM receives a compact summary of every tool's results so it can
    # give grounded feedback without re-reading the full layout JSON.
    from _runtime.llm import call_llm

    scoring    = state.get("scoring_results") or {}
    collision  = state.get("collision_results") or {}
    path       = state.get("path_results") or {}

    score     = scoring.get("total_score", 0)
    grade     = scoring.get("grade", "?")
    breakdown = scoring.get("breakdown", {})

    # Build a concise text summary the LLM can reason over quickly.
    analysis_summary = (
        f"Layout score: {score:.1f}/100  Grade: {grade}\n\n"
        f"Tool breakdown:\n"
        f"- Collision:    {breakdown.get('collision',    {}).get('score', 0):.0f}/100\n"
        f"- Visibility:   {breakdown.get('visibility',   {}).get('score', 0):.0f}/100\n"
        f"- Path:         {breakdown.get('path',         {}).get('score', 0):.0f}/100\n"
        f"- Reachability: {breakdown.get('reachability', {}).get('score', 0):.0f}/100\n"
        f"- Orientation:  {breakdown.get('orientation',  {}).get('score', 0):.0f}/100\n\n"
    )

    # Include the top collision violations so the LLM can name specific issues.
    violations = collision.get("violations", [])
    if violations:
        analysis_summary += "Collision issues:\n"
        for v in violations[:3]:
            analysis_summary += f"  - {v}\n"

    # Worst-case path distance gives the LLM a concrete distance to cite.
    wc = path.get("worst_case", {})
    if wc.get("from"):
        analysis_summary += (
            f"\nLongest path: {wc['from']} → {wc['to']} ({wc['distance']}m)\n"
        )

    # Build the prompt by concatenation — avoids .format() choking on any
    # literal braces that appear in the analysis summary or layout JSON.
    prompt = (
        "You are a spatial design expert.\n"
        "The user has approved a layout.\n\n"
        "Analysis results:\n" + analysis_summary +
        "\nLayout JSON (first 2000 chars):\n" +
        state["layout_json_string"][:2000] +
        "\n\nWrite a clear 3-5 sentence explanation covering: "
        "overall assessment, main strengths, key weaknesses, "
        "one specific recommendation. "
        "Reference actual object names and distances.\n\n"
        "Respond with action final and put your explanation in final_response."
    )

    result = call_llm(
        state.get("_llm"),
        prompt,
        state["messages"],
        state["tool_catalog"],
    )

    explanation = result.get("final_response", "Layout approved and saved.")
    print(f"\nLayout Explanation:\n{explanation}")
    state["final_response"] = explanation
    return state


# ---------------------------------------------------------------------------
# Output node — writes the approved layout to disk and ends the session.
# ---------------------------------------------------------------------------

def output_node(state: AgentState) -> AgentState:
    # Called only after user_approved=True.
    # Writes the final layout to output/ with a timestamp, then deletes the
    # workspace session file so the next run starts clean.
    output_path = close_session(
        state["workspace_path"],
        Path(state["workspace_path"]).parent / "output",
        state["layout_name"],
    )
    print(f"\nLayout saved to: {output_path}")
    state["final_response"] = f"Layout approved and saved to {output_path}"
    return state


# ---------------------------------------------------------------------------
# Graph wiring — build all nodes, then wire edges and conditional routes.
# ---------------------------------------------------------------------------

def build_graph(ctx: Any) -> Any:
    # Build every node from its factory function.
    # Factories receive the dependencies they need (LLM, MCP client, paths)
    # and return a plain callable that accepts and returns AgentState.
    profile_agent    = build_profile_agent_node(ctx.llm, ctx.knowledge_dir)
    space_type_agent = build_space_type_agent_node(ctx.llm, ctx.knowledge_dir)
    reason           = build_reason_node(ctx.llm)
    tool             = build_tool_node(ctx.mcp_client, ctx.tools, ctx.workspace_path)
    add_objects      = build_add_objects_node(ctx.mcp_client, ctx.workspace_path)
    visibility       = build_visibility_node(ctx.mcp_client)
    path             = build_path_node(ctx.mcp_client)
    reachability     = build_reachability_node(ctx.mcp_client)
    orientation      = build_orientation_node(ctx.mcp_client)
    collision        = build_collision_node(ctx.mcp_client, ctx.workspace_path)
    scoring          = build_scoring_node()

    graph = StateGraph(AgentState)

    # Register every node so it can be referenced by name in edge wiring.
    graph.add_node("profile_agent",    profile_agent)
    graph.add_node("space_type_agent", space_type_agent)
    graph.add_node("reason",           reason)
    graph.add_node("tool",             tool)
    graph.add_node("add_objects",      add_objects)
    graph.add_node("visibility",       visibility)
    graph.add_node("path",             path)
    graph.add_node("reachability",     reachability)
    graph.add_node("orientation",      orientation)
    graph.add_node("collision",        collision)
    graph.add_node("scoring",          scoring)
    graph.add_node("user_checkpoint",  user_checkpoint_node)
    graph.add_node("explain",          explain_node)
    graph.add_node("output",           output_node)

    # Pre-agents run sequentially once at startup to classify the layout type
    # and resolve the user accessibility profile before the LLM sees anything.
    graph.add_edge(START, "profile_agent")
    graph.add_edge("profile_agent", "space_type_agent")
    graph.add_edge("space_type_agent", "reason")

    # Reason routes to: place an object, execute a tool, or move to analysis.
    graph.add_conditional_edges(
        "reason", _route_after_reason,
        {
            "add_objects": "add_objects",
            "run_tool":    "tool",
            "finish":      "visibility",   # start analysis pipeline when done reasoning
        },
    )

    # Tool result is fed back to reason so the LLM can interpret it.
    graph.add_edge("tool", "reason")

    # After a placement, run Group 1 analyses in parallel.
    # LangGraph executes all three before advancing to their shared convergence point.
    graph.add_edge("add_objects", "collision")
    graph.add_edge("add_objects", "visibility")
    graph.add_edge("add_objects", "orientation")

    # Group 1 convergence: collision gates progress — hard violations send the
    # LLM back to fix the layout; otherwise fall through to Group 2.
    graph.add_conditional_edges(
        "collision", _route_after_group1,
        {"adjust": "reason", "continue": "path"},
    )
    # Visibility and orientation feed into path (Group 2 entry point).
    graph.add_edge("visibility",  "path")
    graph.add_edge("orientation", "path")

    # Group 2: path then reachability; poor connectivity sends back to reason.
    graph.add_edge("path", "reachability")
    graph.add_conditional_edges(
        "reachability", _route_after_group2,
        {"adjust": "reason", "continue": "scoring"},
    )

    # Scoring aggregates all results and triggers the human approval step.
    graph.add_edge("scoring", "user_checkpoint")

    # User checkpoint: approve → explain → output; otherwise loop back for changes.
    graph.add_conditional_edges(
        "user_checkpoint", _route_after_checkpoint,
        {"approved": "explain", "continue": "reason"},
    )

    # Explain runs once after approval; output writes the file and ends the session.
    graph.add_edge("explain", "output")
    graph.add_edge("output", END)

    return graph.compile()


# ---------------------------------------------------------------------------
# Entry point — called from main.py.
# ---------------------------------------------------------------------------

def run_agent(prompt: str, ctx: Any) -> str:
    app = build_graph(ctx)
    initial_state = _build_initial_state(prompt, ctx)

    # Print the graph topology before running so the wiring is visible
    # in the terminal output before any node executes.
    print("\nWorkflow graph:")
    app.get_graph().print_ascii()
    print()

    final_state = app.invoke(initial_state)

    final_response = final_state.get("final_response")
    if not isinstance(final_response, str):
        raise RuntimeError("Agent finished without final response")
    return final_response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slim_layout(layout_data: dict) -> dict:
    # Send only what the LLM needs for spatial reasoning.
    # Windows, MEP, and structure are stripped to reduce tokens — they matter
    # for visualization and engineering but not for object placement decisions.
    return {
        "layoutId": layout_data.get("layoutId"),
        "rooms": [
            {
                "id":       r.get("id"),
                "name":     r.get("name"),
                "geometry": r.get("geometry"),
            }
            for r in layout_data.get("rooms", [])
        ],
        "doors": [
            {
                "id":       d.get("id"),
                "name":     d.get("name"),
                "geometry": d.get("geometry"),
                "connects": d.get("attributes", {}).get("connectsRooms", []),
            }
            for d in layout_data.get("doors", [])
        ],
        "furniture": layout_data.get("furniture", []),
    }


def _build_initial_state(prompt: str, ctx: Any) -> AgentState:
    # The user message embeds a slim version of the layout JSON to keep the
    # LLM context lean. Space and profile config are filled in by the pre-agents
    # on their first run; all other fields start as None / 0.
    slim = _slim_layout(ctx.layout_data)
    layout_text = json.dumps(slim, indent=2)
    user_message = (
        f"Space config will be determined by Space Type Agent.\n"
        f"Profile config will be determined by Profile Agent.\n\n"
        f"User request:\n{prompt}\n\n"
        f"Current layout JSON:\n{layout_text}"
    )
    return {
        "messages":              [{"role": "user", "content": user_message}],
        "pending_tool_calls":    None,
        "final_response":        None,
        "iteration":             0,
        "max_iterations":        ctx.max_iterations,
        "tool_catalog":          _format_tool_catalog(ctx.tools),
        "layout_json_string":    json.dumps(slim),
        "workspace_path":        str(ctx.workspace_path),
        "layout_name":           ctx.layout_name,
        "space_config":          None,
        "profile_config":        None,
        "object_to_place":       None,
        "last_placement_result": None,
        "visibility_results":    None,
        "path_results":          None,
        "reachability_results":  None,
        "orientation_results":   None,
        "collision_results":     None,
        "scoring_results":       None,
        "evaluation_passed":     None,
        "user_approved":         None,
        "_llm":                  ctx.llm,
    }


def _format_tool_catalog(tools: list[dict[str, Any]]) -> str:
    lines = []
    for tool in tools:
        name = tool.get("name", "<unknown>")
        description = tool.get("description", "")
        schema = json.dumps(tool.get("inputSchema", {}))
        lines.append(f"- {name}: {description} | inputSchema={schema}")
    return "\n".join(lines)
