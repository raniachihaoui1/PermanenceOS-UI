from __future__ import annotations
import json
from typing import Any, TypedDict
from langgraph.graph import END, START, StateGraph
from nodes.reason import (
    build_central_reason_node,
    build_optimization_node,
    build_reason_output_node,
)
from nodes.tools import build_tool_node


# =============================================================================
# graph.py — TerraPilot agent graph (hub-and-spoke architecture)
#
# Architecture: Central Reason Node + specialist worker nodes
#
#   The Central Reason Node (LLM) acts as the hub. It reads the full
#   conversation history, understands the current design state, and chooses
#   ONE action per cycle. Specialist workers execute the action, update state,
#   and return control to the hub. Three terminal paths end the run.
#
# Nodes
# ──────────────────────────────────────────────────────────────────────────────
#   central_reason       LLM     Hub — decides next action (one of 9)
#   suggestion_layer     AUTO    Presents design alternatives to user
#   tool_shape_creation  TOOL    Executes shape/site creation MCP calls
#   update_shape_state   AUTO    Extracts geometry_id; appends state log
#   tool_evaluation      AUTO    Runs all 3 evaluation tools via MCP
#   update_score_state   AUTO    Stores evaluation scores; appends state log
#   human_feedback       AUTO*   Simulates user feedback (mock mode)
#   tool_constraint_check AUTO   Runs all 5 constraint tools via MCP
#   update_constraint_state AUTO Stores violations; appends state log
#   optimization         LLM     Decides which manipulation tool to apply
#   tool_manipulation    TOOL    Executes manipulation MCP calls
#   update_modified_shape AUTO   Extracts updated geometry_id; appends log
#   reason_output        LLM     Writes final architectural narrative
#   visualization        AUTO    Generates text-based design summary
#   final_output         AUTO    Consolidates final_response from state
#   cache_final_state    AUTO    Saves design output to JSON on disk
#
# Flow
# ──────────────────────────────────────────────────────────────────────────────
#   START -> central_reason
#
#   [suggest]           central_reason -> suggestion_layer -> central_reason
#   [generate_shape]    central_reason -> tool_shape_creation
#                                      -> update_shape_state -> central_reason
#   [evaluate]          central_reason -> tool_evaluation
#                                      -> update_score_state -> central_reason
#   [ask_user]          central_reason -> human_feedback -> central_reason
#   [check_constraints] central_reason -> tool_constraint_check
#                                      -> update_constraint_state -> central_reason
#   [optimize]          central_reason -> optimization
#                                      -> tool_manipulation -> update_modified_shape
#                                      -> tool_constraint_check
#                                      -> update_constraint_state -> central_reason
#   [explain]           central_reason -> reason_output -> final_output
#                                      -> cache_final_state -> END
#   [visualize]         central_reason -> visualization -> final_output
#                                      -> cache_final_state -> END
#   [accept]            central_reason -> final_output -> cache_final_state -> END
#
#   * tool_constraint_check is shared by [check_constraints] and [optimize] paths
# =============================================================================


# -- Tool name sets per category ----------------------------------------------

_SHAPE_TOOL_NAMES = {
    "site_boundary_reader_04",
    "context_reader_04",
    "legal_constraints_reader_04",
    "shape_library_loader_04",
    "parametric_shape_generator_04",
}

_MANIPULATION_TOOL_NAMES = {
    "scale_shape_tool_04",
    "stretch_arm_tool_04",
    "width_modifier_tool_04",
    "courtyard_modifier_tool_04",
    "rotate_mirror_tool_04",
    "bend_angle_tool_04",
    "terrace_step_tool_04",
}

_CONSTRAINT_TOOL_NAMES = [
    "site_fit_checker_04",
    "setback_checker_04",
    "area_requirement_checker_04",
    "adjacency_access_checker_04",
    "tree_constraint_checker_04",
]

_EVAL_TOOL_NAMES = [
    "spatial_intention_evaluator_04",
    "performance_evaluator_04",
    "shape_integrity_evaluator_04",
]

# Maximum optimisation cycles before the LLM must choose explain/accept
_MAX_MOD_ITERS = 4


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class AgentState(TypedDict, total=False):
    messages:               list[dict[str, Any]]
    next_action:            str                       # decision from central_reason
    pending_tool_calls:     list[dict[str, Any]] | None
    final_response:         str | None
    iteration:              int
    max_iterations:         int
    tool_catalog:           str
    layout_json_string:     str

    # Shape state
    geometry_id:            str | None
    shape_state:            dict[str, Any] | None

    # Score state
    score_state:            dict[str, Any] | None
    evaluation_done:        bool

    # Constraint state
    constraint_results:     dict[str, Any] | None
    violations:             list[str]
    modification_iters:     int


# ---------------------------------------------------------------------------
# Violation categorisation
# ---------------------------------------------------------------------------

def _categorize_violations(results: dict[str, Any]) -> list[str]:
    """Map raw checker results to violation category names."""
    violations: list[str] = []

    fit = results.get("site_fit_checker_04", {}).get("data", {})
    if not fit.get("fits", True) and not fit.get("fits_within_site", True):
        violations.append("fit")

    setback = results.get("setback_checker_04", {}).get("data", {})
    if not setback.get("compliant", True):
        violations.append("setback")

    area = results.get("area_requirement_checker_04", {}).get("data", {})
    if not area.get("gfa_compliant", True) and not area.get("meets_requirement", True):
        violations.append("area")

    access = results.get("adjacency_access_checker_04", {}).get("data", {})
    if not access.get("road_access_ok", True) and not access.get("access_adequate", True):
        violations.append("access")

    trees = results.get("tree_constraint_checker_04", {}).get("data", {})
    if not trees.get("no_conflicts", True):
        violations.append("trees")

    return violations


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def _route_from_central_reason(state: AgentState) -> str:
    """Hub routing: map next_action to the correct worker node."""
    action = state.get("next_action", "accept")
    routing = {
        "suggest":            "suggestion_layer",
        "generate_shape":     "tool_shape_creation",
        "evaluate":           "tool_evaluation",
        "ask_user":           "human_feedback",
        "check_constraints":  "tool_constraint_check",
        "optimize":           "optimization",
        "explain":            "reason_output",
        "visualize":          "visualization",
        "accept":             "final_output",
    }
    dest = routing.get(action, "final_output")
    print(f"[routing] central_reason -> {dest}  (action={action})")
    return dest


# ---------------------------------------------------------------------------
# AUTO node: suggestion_layer
# ---------------------------------------------------------------------------

def _build_suggestion_layer() -> Any:
    """Presents design alternatives to the user; returns immediately to hub."""

    def suggestion_layer(state: AgentState) -> dict:
        messages = list(state.get("messages", []))
        messages.append({
            "role":    "user",
            "content": (
                "=== SUGGESTION LAYER ===\n"
                "Design suggestions have been presented to the user. "
                "Awaiting next decision."
            ),
        })
        print("[suggestion_layer] Suggestion displayed.")
        return {"messages": messages, "next_action": None}

    return suggestion_layer


# ---------------------------------------------------------------------------
# AUTO node: update_shape_state
# ---------------------------------------------------------------------------

def _build_update_shape_state() -> Any:
    """Extracts geometry_id from the most recent tool result and logs it."""

    def update_shape_state(state: AgentState) -> dict:
        geometry_id = state.get("geometry_id")
        for msg in reversed(state.get("messages", [])):
            if msg.get("role") == "user" and msg.get("content", "").startswith("Tool result:"):
                try:
                    payload = json.loads(
                        msg["content"].removeprefix("Tool result:").strip()
                    )
                    gid = payload.get("data", {}).get("geometry_id")
                    if gid:
                        geometry_id = gid
                except Exception:
                    pass
                break

        messages = list(state.get("messages", []))
        messages.append({
            "role":    "user",
            "content": (
                f"=== SHAPE STATE UPDATED ===\n"
                f"geometry_id: {geometry_id}\n"
                f"Shape creation complete. Ready for constraint checking or evaluation."
            ),
        })
        print(f"[update_shape_state] geometry_id={geometry_id}")
        return {
            "messages":    messages,
            "geometry_id": geometry_id,
            "shape_state": {"geometry_id": geometry_id, "created": True},
            "next_action": None,
        }

    return update_shape_state


# ---------------------------------------------------------------------------
# AUTO node: tool_evaluation
# ---------------------------------------------------------------------------

def _build_tool_evaluation(mcp_client: Any) -> Any:
    """Runs all 3 evaluation tools automatically. No LLM involved."""

    def tool_evaluation(state: AgentState) -> dict:
        geom_id     = state.get("geometry_id")
        eval_parts: list[str] = []
        score_state: dict[str, Any] = {}

        for tool_name in _EVAL_TOOL_NAMES:
            args = {"geometry_id": geom_id} if geom_id else {}
            try:
                raw    = mcp_client.call_tool(tool_name, args)
                parsed = json.loads(raw)
                eval_parts.append(f"[{tool_name}]:\n{raw}")
                score_state[tool_name] = parsed.get("data", {})
            except Exception as exc:
                eval_parts.append(f"[{tool_name}]: ERROR -- {exc}")

        messages = list(state.get("messages", []))
        messages.append({
            "role":    "user",
            "content": "=== EVALUATION RESULTS ===\n\n" + "\n\n".join(eval_parts),
        })
        print("[tool_evaluation] All 3 evaluators complete.")
        return {
            "messages":    messages,
            "score_state": score_state,
            "next_action": None,
        }

    return tool_evaluation


# ---------------------------------------------------------------------------
# AUTO node: update_score_state
# ---------------------------------------------------------------------------

def _build_update_score_state() -> Any:
    """Stores evaluation scores and logs completion."""

    def update_score_state(state: AgentState) -> dict:
        messages = list(state.get("messages", []))
        messages.append({
            "role":    "user",
            "content": (
                "=== SCORE STATE UPDATED ===\n"
                "Evaluation scores stored. Design is scored and ready for final report or accept."
            ),
        })
        print("[update_score_state] Score state updated.")
        return {"messages": messages, "evaluation_done": True, "next_action": None}

    return update_score_state


# ---------------------------------------------------------------------------
# AUTO node: human_feedback
# ---------------------------------------------------------------------------

def _build_human_feedback() -> Any:
    """Simulates human feedback in mock/notebook mode; auto-advances."""

    def human_feedback(state: AgentState) -> dict:
        messages = list(state.get("messages", []))
        messages.append({
            "role":    "user",
            "content": (
                "=== HUMAN FEEDBACK ===\n"
                "User reviewed the current design.\n"
                "Feedback: The direction looks correct -- please proceed."
            ),
        })
        print("[human_feedback] Auto-advance (mock mode).")
        return {"messages": messages, "next_action": None}

    return human_feedback


# ---------------------------------------------------------------------------
# AUTO node: tool_constraint_check
# Shared by both the [check_constraints] and [optimize] paths.
# ---------------------------------------------------------------------------

def _build_tool_constraint_check(mcp_client: Any) -> Any:
    """Runs all 5 constraint tools automatically. No LLM involved."""

    def tool_constraint_check(state: AgentState) -> dict:
        geom_id     = state.get("geometry_id")
        layout_json = state.get("layout_json_string", "{}")
        results: dict[str, Any] = {}
        cycle = state.get("modification_iters", 0) + 1

        for tool_name in _CONSTRAINT_TOOL_NAMES:
            args: dict[str, Any] = {"layout_json": layout_json}
            if geom_id:
                args["geometry_id"] = geom_id
            try:
                raw = mcp_client.call_tool(tool_name, args)
                results[tool_name] = json.loads(raw)
            except Exception as exc:
                results[tool_name] = {"success": False, "error": str(exc)}

        violations = _categorize_violations(results)
        viol_text  = (
            f"Violations detected: {violations}"
            if violations
            else "All 5 constraints satisfied -- no violations."
        )

        messages = list(state.get("messages", []))
        messages.append({
            "role":    "user",
            "content": (
                f"=== CONSTRAINT CHECK RESULTS (cycle {cycle}) ===\n"
                f"{json.dumps(results, indent=2)}\n\n"
                f"{viol_text}\n"
                f"{'Next: consider optimization.' if violations else 'Next: evaluate or accept.'}"
            ),
        })

        print(f"[tool_constraint_check] cycle={cycle}  violations={violations}")
        return {
            "messages":           messages,
            "constraint_results": results,
            "violations":         violations,
            "pending_tool_calls": None,
            "modification_iters": cycle,
            "next_action":        None,
        }

    return tool_constraint_check


# ---------------------------------------------------------------------------
# AUTO node: update_constraint_state
# ---------------------------------------------------------------------------

def _build_update_constraint_state() -> Any:
    """Stores constraint violations and logs status before returning to hub."""

    def update_constraint_state(state: AgentState) -> dict:
        violations = state.get("violations", [])
        status     = f"violations={violations}" if violations else "all_clear"
        messages   = list(state.get("messages", []))
        messages.append({
            "role":    "user",
            "content": (
                f"=== CONSTRAINT STATE UPDATED ===\n"
                f"Status: {status}. Returning to central reasoning."
            ),
        })
        print(f"[update_constraint_state] {status}")
        return {"messages": messages, "next_action": None}

    return update_constraint_state


# ---------------------------------------------------------------------------
# AUTO node: update_modified_shape
# ---------------------------------------------------------------------------

def _build_update_modified_shape() -> Any:
    """Extracts updated geometry_id after manipulation; routes to re-check."""

    def update_modified_shape(state: AgentState) -> dict:
        geometry_id = state.get("geometry_id")
        for msg in reversed(state.get("messages", [])):
            if msg.get("role") == "user" and msg.get("content", "").startswith("Tool result:"):
                try:
                    payload = json.loads(
                        msg["content"].removeprefix("Tool result:").strip()
                    )
                    gid = payload.get("data", {}).get("geometry_id")
                    if gid:
                        geometry_id = gid
                except Exception:
                    pass
                break

        messages = list(state.get("messages", []))
        messages.append({
            "role":    "user",
            "content": (
                f"=== MODIFIED SHAPE STATE UPDATED ===\n"
                f"geometry_id: {geometry_id}. Re-checking constraints now."
            ),
        })
        print(f"[update_modified_shape] geometry_id={geometry_id}")
        return {
            "messages":    messages,
            "geometry_id": geometry_id,
            "shape_state": {"geometry_id": geometry_id, "modified": True},
            "next_action": None,
        }

    return update_modified_shape


# ---------------------------------------------------------------------------
# AUTO node: visualization
# ---------------------------------------------------------------------------

def _build_visualization() -> Any:
    """Generates a text-based design summary for the final output path."""

    def visualization(state: AgentState) -> dict:
        geometry_id = state.get("geometry_id", "unknown")
        score_state = state.get("score_state") or {}
        violations  = state.get("violations", [])
        messages    = list(state.get("messages", []))

        messages.append({
            "role":    "user",
            "content": (
                f"=== VISUALIZATION ===\n"
                f"Geometry ID : {geometry_id}\n"
                f"Violations  : {violations or 'none'}\n"
                f"Scores      : {json.dumps(score_state, indent=2)}"
            ),
        })
        print("[visualization] Visualization generated.")
        return {"messages": messages}

    return visualization


# ---------------------------------------------------------------------------
# AUTO node: final_output
# ---------------------------------------------------------------------------

def _build_final_output() -> Any:
    """Consolidates the final response from state or builds a minimal summary."""

    def final_output(state: AgentState) -> dict:
        final_response = state.get("final_response") or ""
        if not final_response:
            geometry_id    = state.get("geometry_id", "unknown")
            violations     = state.get("violations", [])
            score_state    = state.get("score_state") or {}
            final_response = (
                f"Design complete.\n"
                f"geometry_id  : {geometry_id}\n"
                f"Violations   : {violations or 'none'}\n"
                f"Scores       : {json.dumps(score_state)}"
            )
        print("[final_output] Final output assembled.")
        return {"final_response": final_response}

    return final_output


# ---------------------------------------------------------------------------
# AUTO node: cache_final_state
# ---------------------------------------------------------------------------

def _build_cache_final_state(edited_layout_path: Any) -> Any:
    """Saves the design output JSON to disk."""
    from pathlib import Path

    def cache_final_state(state: AgentState) -> dict:
        try:
            out = {
                "final_response":     state.get("final_response", ""),
                "geometry_id":        state.get("geometry_id"),
                "violations":         state.get("violations", []),
                "score_state":        state.get("score_state"),
                "modification_iters": state.get("modification_iters", 0),
            }
            path = Path(edited_layout_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w") as f:
                json.dump(out, f, indent=2)
            print(f"[cache_final_state] Saved -> {path}")
        except Exception as exc:
            print(f"[cache_final_state] Save failed: {exc}")
        return {}

    return cache_final_state


# ---------------------------------------------------------------------------
# Tracked tool executor -- shape creation
# ---------------------------------------------------------------------------

def _build_shape_tool_node(ctx: Any) -> Any:
    """Wraps the generic tool executor; extracts geometry_id from results."""
    inner = build_tool_node(ctx.mcp_client, ctx.tools, ctx.edited_layout_path)

    def tool_shape_creation(state: AgentState) -> dict:
        result = inner(state)
        for msg in reversed(result.get("messages", state.get("messages", []))):
            if msg.get("role") == "user" and msg.get("content", "").startswith("Tool result:"):
                try:
                    payload = json.loads(
                        msg["content"].removeprefix("Tool result:").strip()
                    )
                    gid = payload.get("data", {}).get("geometry_id")
                    if gid:
                        result["geometry_id"] = gid
                except Exception:
                    pass
                break
        return result

    return tool_shape_creation


# ---------------------------------------------------------------------------
# Tracked tool executor -- manipulation
# ---------------------------------------------------------------------------

def _build_manipulation_tool_node(ctx: Any) -> Any:
    """Wraps the generic tool executor for manipulation calls."""
    inner = build_tool_node(ctx.mcp_client, ctx.tools, ctx.edited_layout_path)

    def tool_manipulation(state: AgentState) -> dict:
        result = inner(state)
        for msg in reversed(result.get("messages", state.get("messages", []))):
            if msg.get("role") == "user" and msg.get("content", "").startswith("Tool result:"):
                try:
                    payload = json.loads(
                        msg["content"].removeprefix("Tool result:").strip()
                    )
                    gid = payload.get("data", {}).get("geometry_id")
                    if gid:
                        result["geometry_id"] = gid
                except Exception:
                    pass
                break
        return result

    return tool_manipulation


# ---------------------------------------------------------------------------
# Phase catalog builder
# ---------------------------------------------------------------------------

def _fmt_phase_catalog(all_tools: list[dict], names: set) -> str:
    return "\n".join(
        f"- {t['name']}: {t.get('description', '')} | inputSchema={json.dumps(t.get('inputSchema', {}))}"
        for t in all_tools if t.get("name") in names
    )


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------

def build_graph(ctx: Any) -> Any:
    all_tools = ctx.tools

    # Per-category tool catalogs for LLM prompts
    all_names            = {t["name"] for t in all_tools}
    shape_catalog        = _fmt_phase_catalog(all_tools, _SHAPE_TOOL_NAMES)
    manipulation_catalog = _fmt_phase_catalog(all_tools, _MANIPULATION_TOOL_NAMES)
    full_catalog         = _fmt_phase_catalog(all_tools, all_names)

    # -- LLM nodes (3) --------------------------------------------------------
    central_reason = build_central_reason_node(
        ctx.llm, full_catalog, _MAX_MOD_ITERS
    )
    optimization   = build_optimization_node(ctx.llm, manipulation_catalog)
    reason_output  = build_reason_output_node(ctx.llm)

    # -- AUTO nodes -----------------------------------------------------------
    suggestion_layer        = _build_suggestion_layer()
    tool_shape_creation     = _build_shape_tool_node(ctx)
    update_shape_state      = _build_update_shape_state()
    tool_evaluation         = _build_tool_evaluation(ctx.mcp_client)
    update_score_state      = _build_update_score_state()
    human_feedback          = _build_human_feedback()
    tool_constraint_check   = _build_tool_constraint_check(ctx.mcp_client)
    update_constraint_state = _build_update_constraint_state()
    tool_manipulation       = _build_manipulation_tool_node(ctx)
    update_modified_shape   = _build_update_modified_shape()
    visualization           = _build_visualization()
    final_output            = _build_final_output()
    cache_final_state       = _build_cache_final_state(ctx.edited_layout_path)

    graph = StateGraph(AgentState)

    # -- Register all 16 nodes ------------------------------------------------
    graph.add_node("central_reason",          central_reason)
    graph.add_node("suggestion_layer",        suggestion_layer)
    graph.add_node("tool_shape_creation",     tool_shape_creation)
    graph.add_node("update_shape_state",      update_shape_state)
    graph.add_node("tool_evaluation",         tool_evaluation)
    graph.add_node("update_score_state",      update_score_state)
    graph.add_node("human_feedback",          human_feedback)
    graph.add_node("tool_constraint_check",   tool_constraint_check)
    graph.add_node("update_constraint_state", update_constraint_state)
    graph.add_node("optimization",            optimization)
    graph.add_node("tool_manipulation",       tool_manipulation)
    graph.add_node("update_modified_shape",   update_modified_shape)
    graph.add_node("reason_output",           reason_output)
    graph.add_node("visualization",           visualization)
    graph.add_node("final_output",            final_output)
    graph.add_node("cache_final_state",       cache_final_state)

    # -- Wiring ---------------------------------------------------------------

    # Entry point
    graph.add_edge(START, "central_reason")

    # Hub dispatches to workers (conditional)
    graph.add_conditional_edges(
        "central_reason", _route_from_central_reason,
        {
            "suggestion_layer":       "suggestion_layer",
            "tool_shape_creation":    "tool_shape_creation",
            "tool_evaluation":        "tool_evaluation",
            "human_feedback":         "human_feedback",
            "tool_constraint_check":  "tool_constraint_check",
            "optimization":           "optimization",
            "reason_output":          "reason_output",
            "visualization":          "visualization",
            "final_output":           "final_output",
        },
    )

    # [suggest] spoke: suggestion_layer -> hub
    graph.add_edge("suggestion_layer",        "central_reason")

    # [generate_shape] spoke: tool -> update state -> hub
    graph.add_edge("tool_shape_creation",     "update_shape_state")
    graph.add_edge("update_shape_state",      "central_reason")

    # [evaluate] spoke: tool -> update score -> hub
    graph.add_edge("tool_evaluation",         "update_score_state")
    graph.add_edge("update_score_state",      "central_reason")

    # [ask_user] spoke: feedback -> hub
    graph.add_edge("human_feedback",          "central_reason")

    # [check_constraints] and [optimize] tail both flow into:
    #   tool_constraint_check -> update_constraint_state -> hub
    graph.add_edge("tool_constraint_check",   "update_constraint_state")
    graph.add_edge("update_constraint_state", "central_reason")

    # [optimize] spoke: optimization -> manipulation -> update -> re-check
    graph.add_edge("optimization",            "tool_manipulation")
    graph.add_edge("tool_manipulation",       "update_modified_shape")
    graph.add_edge("update_modified_shape",   "tool_constraint_check")

    # [explain] terminal path
    graph.add_edge("reason_output",           "final_output")

    # [visualize] terminal path
    graph.add_edge("visualization",           "final_output")

    # All terminal paths converge to cache and end
    graph.add_edge("final_output",            "cache_final_state")
    graph.add_edge("cache_final_state",       END)

    return graph.compile()


# ---------------------------------------------------------------------------
# Entry point -- called from main.py and the notebook.
# ---------------------------------------------------------------------------

def run_agent(prompt: str, ctx: Any) -> str:
    app           = build_graph(ctx)
    initial_state = _build_initial_state(prompt, ctx)
    final_state   = app.invoke(initial_state)

    try:
        print("\nWorkflow graph:")
        app.get_graph().print_ascii()
    except ImportError:
        pass

    final_response = final_state.get("final_response")
    if not isinstance(final_response, str):
        raise RuntimeError("Agent finished without a final response")
    return final_response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_tool_catalog(tools: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"- {t.get('name', '<unknown>')}: {t.get('description', '')} | inputSchema={json.dumps(t.get('inputSchema', {}))}"
        for t in tools
    )


def _build_initial_state(prompt: str, ctx: Any) -> AgentState:
    return {
        "messages":             [{"role": "user", "content": prompt}],
        "pending_tool_calls":   None,
        "final_response":       None,
        "iteration":            0,
        "max_iterations":       ctx.max_iterations,
        "tool_catalog":         _format_tool_catalog(ctx.tools),
        "layout_json_string":   json.dumps(ctx.layout_data),
        "next_action":          None,
        "geometry_id":          None,
        "shape_state":          None,
        "score_state":          None,
        "evaluation_done":      False,
        "constraint_results":   None,
        "violations":           [],
        "modification_iters":   0,
    }
