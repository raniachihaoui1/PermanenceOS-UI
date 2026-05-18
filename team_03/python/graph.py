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

    # Layout and session paths — layout_json_string is updated by add_objects
    # and tools nodes after placements; needs _keep_last so updates propagate.
    layout_json_string:  Annotated[str, _keep_last]
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

    # Adjustment loop counter — prevents infinite loops when collision/reachability
    # violations persist despite object placement attempts. After max adjustments
    # the graph continues to scoring regardless.
    adjustment_count:    Annotated[int, _keep_last]

    # Placement history — list of dicts describing each furniture move.
    # Populated by add_objects, displayed by user_checkpoint before approval.
    placement_history:   Annotated[list[dict] | None, _keep_last]

    # Original layout snapshot — used to detect if doors/windows/structure
    # were modified or lost during the pipeline.
    original_layout:     dict | None


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
    # Empty string "" is treated as "cleared" (not finished); only a real
    # non-empty string triggers the finish route.
    fr = state.get("final_response")
    if fr is not None and fr != "":
        return "finish"
    # Default: a tool call was queued; execute it then return to reason.
    return "run_tool"


MAX_ADJUSTMENTS = 3  # Max times the graph loops back to reason for collision/reachability fixes


def _route_after_group1(state: AgentState) -> str:
    # Group 1 = collision + visibility + orientation.
    # Hard violations mean the layout is physically impassable — route back
    # to reason immediately rather than wasting time on path checks.
    # BUT: only loop back if (a) the agent placed objects, and (b) we haven't
    # exceeded the max adjustment attempts. Otherwise continue to scoring.
    adj = state.get("adjustment_count", 0)
    collision = state.get("collision_results")
    if collision and not collision.get("pass", True):
        hard = collision.get("summary", {}).get("hard_violations", 0)
        if hard > 0 and state.get("last_placement_result") is not None and adj < MAX_ADJUSTMENTS:
            print(f"[router] Hard collision violations — adjustment {adj + 1}/{MAX_ADJUSTMENTS}")
            return "adjust"
    return "continue"


def _route_after_group2(state: AgentState) -> str:
    # Group 2 = path + reachability.
    # Same logic with max adjustment limit.
    has_placed = state.get("last_placement_result") is not None
    adj = state.get("adjustment_count", 0)

    if has_placed and adj < MAX_ADJUSTMENTS:
        path = state.get("path_results")
        if path:
            pairs = path.get("pairs", [])
            unreachable = [p for p in pairs if p.get("status") == "unreachable"]
            if pairs and len(unreachable) > len(pairs) * 0.3:
                print(f"[router] Path violations — adjustment {adj + 1}/{MAX_ADJUSTMENTS}")
                return "adjust"

        reach = state.get("reachability_results")
        if reach:
            summary = reach.get("summary", {})
            total    = summary.get("total", 0)
            reachable = summary.get("reachable", 0)
            if total > 0 and reachable / total < 0.7:
                print(f"[router] Reachability violations — adjustment {adj + 1}/{MAX_ADJUSTMENTS}")
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

def analysis_fan_out_node(state: AgentState) -> dict:
    """No-op pass-through that exists solely as a fan-out point.
    LangGraph needs a single source node to fan out to the three
    Group 1 analysis nodes (collision, visibility, orientation).
    Returns an empty update dict — nothing to change in state."""
    return {}


def group1_join_node(state: AgentState) -> dict:
    """Join point after Group 1 parallel nodes converge.
    Increments adjustment_count so the router can enforce the max limit.
    LangGraph waits for all incoming edges (collision, visibility,
    orientation) to complete before executing this node."""
    collision = state.get("collision_results")
    if collision and not collision.get("pass", True):
        hard = collision.get("summary", {}).get("hard_violations", 0)
        if hard > 0 and state.get("last_placement_result") is not None:
            return {"adjustment_count": state.get("adjustment_count", 0) + 1}
    return {}


def user_checkpoint_node(state: AgentState) -> dict:
    # Present the current score to the user and let them decide whether to
    # approve the layout or describe further changes.
    # This is the only node that blocks on user input — all other nodes are
    # fully automated.

    # ── Structural integrity check ──────────────────────────────────────
    # Verify that doors, windows, structure, and outline haven't been lost
    # during the pipeline. If any are missing, restore from the original.
    original = state.get("original_layout") or {}
    current_layout = json.loads(state["layout_json_string"])
    integrity_warnings = []
    restored = False

    for layer in ("doors", "windows", "mep", "structure", "outline"):
        orig_data = original.get(layer)
        curr_data = current_layout.get(layer)
        if orig_data and not curr_data:
            current_layout[layer] = orig_data
            restored = True
            if layer == "outline":
                integrity_warnings.append(f"  {layer}: RESTORED (was missing)")
            else:
                integrity_warnings.append(f"  {layer}: RESTORED — {len(orig_data)} items recovered")
        elif isinstance(orig_data, list) and isinstance(curr_data, list):
            if len(curr_data) < len(orig_data):
                current_layout[layer] = orig_data
                restored = True
                integrity_warnings.append(
                    f"  {layer}: RESTORED — had {len(curr_data)}, restored to {len(orig_data)}"
                )

    if restored:
        layout_json_string = json.dumps(current_layout)
        from _runtime.session import save_session
        save_session(current_layout, state["workspace_path"])
        print("\n[checkpoint] Structural integrity issues detected and fixed:")
        for w in integrity_warnings:
            print(w)

    # ── Door change detection ───────────────────────────────────────────
    # Check if any doors were modified (position or size changed).
    orig_doors = {d.get("id"): d for d in original.get("doors", [])}
    curr_doors = {d.get("id"): d for d in current_layout.get("doors", [])}
    door_changes = []
    for door_id, orig_door in orig_doors.items():
        curr_door = curr_doors.get(door_id)
        if not curr_door:
            door_changes.append(f"  REMOVED: {orig_door.get('name', door_id)}")
        elif orig_door.get("geometry") != curr_door.get("geometry"):
            door_changes.append(f"  MODIFIED: {orig_door.get('name', door_id)}")
    for door_id in curr_doors:
        if door_id not in orig_doors:
            door_changes.append(f"  ADDED: {curr_doors[door_id].get('name', door_id)}")

    scoring = state.get("scoring_results") or {}
    score = scoring.get("total_score", 0)
    grade = scoring.get("grade", "?")
    rec   = scoring.get("recommendation", "")
    breakdown = scoring.get("breakdown", {})

    print(f"\n{'=' * 60}")
    print(f"LAYOUT SCORE: {score:.1f}/100  Grade: {grade}")
    print(f"Recommendation: {rec}")
    print(f"{'=' * 60}")

    # Show score breakdown per tool
    print("\nScore breakdown:")
    for tool_name, details in breakdown.items():
        s = details.get("score", 0)
        w = details.get("weight", 0)
        ws = details.get("weighted", 0)
        print(f"  {tool_name:15s}  {s:5.1f}/100  (weight {w:.2f}, contribution {ws:.2f})")

    # Show collision violations if any
    collision = state.get("collision_results") or {}
    violations = collision.get("violations", [])
    if violations:
        print(f"\nCollision violations ({len(violations)}):")
        for v in violations[:5]:
            if isinstance(v, str):
                print(f"  - {v}")
            elif isinstance(v, dict):
                print(f"  - {v.get('type', '?')}: {v.get('description', str(v))}")

    # Show placement history — what objects were moved/added
    history = state.get("placement_history")
    if history:
        print(f"\nFurniture changes made ({len(history)} items):")
        for c in history:
            name = c.get("name", "?")
            action = c.get("action", "?")
            room = c.get("room", "?")
            if action == "moved":
                fr = c.get("from", [0, 0])
                to = c.get("to", [0, 0])
                print(f"  MOVED  {name:30s}  ({fr[0]:6.1f}, {fr[1]:6.1f}) -> ({to[0]:6.1f}, {to[1]:6.1f})  [{room}]")
            else:
                to = c.get("to", [0, 0])
                print(f"  ADDED  {name:30s}  at ({to[0]:6.1f}, {to[1]:6.1f})  [{room}]")

    # Show structural integrity warnings
    if integrity_warnings:
        print(f"\nStructural integrity fixes applied:")
        for w in integrity_warnings:
            print(w)

    # Show door changes — alert user before they approve
    if door_changes:
        print(f"\nDoor changes detected:")
        for dc in door_changes:
            print(dc)
        print("  (Review carefully — door modifications may affect accessibility)")

    print(f"\n{'=' * 60}")
    print("Options:")
    print("  'approve' -> save final layout and finish")
    print("  anything else -> describe what to change")
    print()

    user_input = input("Your decision: ").strip()

    # Build base updates — include restored layout if integrity was fixed
    updates: dict = {}
    if restored:
        updates["layout_json_string"] = json.dumps(current_layout)

    if user_input.lower() in ("approve", "yes", "ok", "done"):
        updates["user_approved"] = True
        return updates
    else:
        # User wants further changes — inject their message so the reason node
        # picks up their instruction on the next iteration.
        # Reset iteration counter so the new round gets the full budget.
        updates["user_approved"] = False
        updates["messages"] = [{"role": "user", "content": user_input}]
        updates["iteration"] = 0
        return updates


# ---------------------------------------------------------------------------
# Explain node — LLM generates a spatial reasoning summary of the approved layout.
# Runs after user_approved=True and before output so the explanation is
# captured in final_response before the session file is deleted.
# ---------------------------------------------------------------------------


def explain_node(state: AgentState) -> dict:
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
            f"\nLongest path: {wc['from']} -> {wc['to']} ({wc['distance']}m)\n"
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

    try:
        result = call_llm(
            state.get("_llm"),
            prompt,
            state["messages"],
            state["tool_catalog"],
        )
        explanation = result.get("final_response", "Layout approved and saved.")
    except Exception:
        # LLM may return markdown/text instead of JSON — use call_llm_simple
        # as a fallback to get the raw text response.
        try:
            from _runtime.llm import call_llm_simple
            raw = call_llm_simple(state.get("_llm"), prompt, "Generate the explanation.")
            if raw and isinstance(raw, dict):
                explanation = raw.get("final_response", str(raw))
            else:
                explanation = "Layout approved and saved."
        except Exception as exc2:
            print(f"[explain] Fallback also failed: {exc2}")
            explanation = "Layout approved and saved."
    print(f"\nLayout Explanation:\n{explanation}")
    return {"final_response": explanation}


# ---------------------------------------------------------------------------
# Output node — writes the approved layout to disk and ends the session.
# ---------------------------------------------------------------------------

def output_node(state: AgentState) -> dict:
    # Called only after user_approved=True.
    # Writes the final layout to output/ with a timestamp, then deletes the
    # workspace session file so the next run starts clean.
    output_path = close_session(
        state["workspace_path"],
        Path(state["workspace_path"]).parent / "output",
        state["layout_name"],
    )
    print(f"\nLayout saved to: {output_path}")
    return {"final_response": f"Layout approved and saved to {output_path}"}


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
    graph.add_node("analysis_fan_out", analysis_fan_out_node)
    graph.add_node("visibility",       visibility)
    graph.add_node("path",             path)
    graph.add_node("reachability",     reachability)
    graph.add_node("orientation",      orientation)
    graph.add_node("collision",        collision)
    graph.add_node("group1_join",      group1_join_node)
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
    # "finish" goes to analysis_fan_out which triggers all Group 1 nodes in parallel.
    graph.add_conditional_edges(
        "reason", _route_after_reason,
        {
            "add_objects":  "add_objects",
            "run_tool":     "tool",
            "finish":       "analysis_fan_out",
        },
    )

    # Tool result is fed back to reason so the LLM can interpret it.
    graph.add_edge("tool", "reason")

    # After a placement, go through the same analysis fan-out node
    # so both paths (placement and direct finish) trigger the same parallel group.
    graph.add_edge("add_objects", "analysis_fan_out")

    # analysis_fan_out fans out to all three Group 1 nodes in parallel.
    graph.add_edge("analysis_fan_out", "collision")
    graph.add_edge("analysis_fan_out", "visibility")
    graph.add_edge("analysis_fan_out", "orientation")

    # Group 1 convergence: all three feed into group1_join so LangGraph
    # waits for all of them before evaluating collision results.
    graph.add_edge("collision",   "group1_join")
    graph.add_edge("visibility",  "group1_join")
    graph.add_edge("orientation", "group1_join")

    # group1_join checks collision results — hard violations route back to reason.
    graph.add_conditional_edges(
        "group1_join", _route_after_group1,
        {"adjust": "reason", "continue": "path"},
    )

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
    # LLM context lean. But layout_json_string stores the FULL layout because
    # MCP tools (collision-detector-grid, visualize_visibility) need all fields
    # (outline, structure, mep) that _slim_layout strips.
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
        "layout_json_string":    json.dumps(ctx.layout_data),
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
        "adjustment_count":      0,
        "placement_history":     None,
        "original_layout":       ctx.layout_data,
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
