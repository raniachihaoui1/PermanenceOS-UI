from __future__ import annotations
import json
from typing import Any, TypedDict
from langgraph.graph import END, START, StateGraph
from nodes.reason import (
    build_site_reader_node,
    build_form_planner_node,
    build_orientation_fixer_node,
    build_form_modifier_node,
    build_report_writer_node,
)
from nodes.tools import build_tool_node


# =============================================================================
# graph.py — TerraPilot agent graph.
#
# Architecture: 9-node category-based pipeline
#
# Each node has ONE named, unambiguous role.  Tool groups map 1-to-1 to nodes:
#
#   Node               Kind    Tool category           Tools
#   ─────────────────────────────────────────────────────────────────────────
#   read_site          LLM     Site reading            site_boundary_reader_04
#                                                      context_reader_04
#                                                      legal_constraints_reader_04
#   plan_form          LLM     Shape generation        shape_library_loader_04
#                                                      parametric_shape_generator_04
#   check_constraints  AUTO    Constraint checking     site_fit_checker_04
#                                                      setback_checker_04
#                                                      area_requirement_checker_04
#                                                      adjacency_access_checker_04
#                                                      tree_constraint_checker_04
#   fix_orientation    LLM     Orientation tools       rotate_mirror_tool_04
#                                                      scale_shape_tool_04 (offset)
#   fix_form           LLM     Modification tools      scale_shape_tool_04
#                                                      stretch_arm_tool_04
#                                                      width_modifier_tool_04
#                                                      courtyard_modifier_tool_04
#                                                      bend_angle_tool_04
#                                                      terrace_step_tool_04
#   evaluate           AUTO    Evaluation              spatial_intention_evaluator_04
#                                                      performance_evaluator_04
#                                                      shape_integrity_evaluator_04
#   write_report       LLM     Report writing          (no tools — LLM only)
#   bake_output        AUTO    Output                  bake_geometry_id_04
#   tool               SHARED  Tool executor           (all phases share this)
#
# Flow:
#   START → read_site ──(tool loop)─► plan_form ──(tool loop)─► check_constraints
#             check_constraints ──[access violation]──► fix_orientation ──(tool loop)─►┐
#             check_constraints ──[form violation]────► fix_form ──(tool loop)──────────┤
#             check_constraints ──[clean or ≤4 cycles]► evaluate → write_report → bake_output → END
#                                                                         ▲
#             fix_orientation ─(done)─► check_constraints ────────────────┤ (loop ≤ 4×)
#             fix_form        ─(done)─► check_constraints ────────────────┘
#
# Key improvement over previous design
# ──────────────────────────────────────
# Previous:  LLM nodes were called repeatedly in the same phase — once to plan
#            tool calls, again to process results, again to decide what to do
#            next.  It was impossible to tell whether a node's output was
#            planning the next step or summarising the last one.
#
# Now:       Each LLM node is called in exactly TWO modes, written into the prompt:
#              MODE A (planning)  — no tool results yet → action="tool"
#              MODE B (summary)   — results received → action="final" + phase summary
#            The summary is appended to messages as an assistant message, making
#            the conversation log a clear, structured timeline of what happened.
#
#            write_report does NOT call tools (baking is handled by bake_output AUTO).
#            evaluate and check_constraints are fully AUTO — no LLM needed.
# =============================================================================


# ── Tool name sets per category ───────────────────────────────────────────────
_SITE_TOOL_NAMES   = {
    "site_boundary_reader_04",
    "context_reader_04",
    "legal_constraints_reader_04",
}
_FORM_TOOL_NAMES   = {
    "shape_library_loader_04",
    "parametric_shape_generator_04",
}
_ORIENT_TOOL_NAMES = {
    "rotate_mirror_tool_04",
    "scale_shape_tool_04",
}
_MODIFY_TOOL_NAMES = {
    "scale_shape_tool_04",
    "stretch_arm_tool_04",
    "width_modifier_tool_04",
    "courtyard_modifier_tool_04",
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
_SHAPE_TOOL_NAMES = {"parametric_shape_generator_04", "shape_library_loader_04"}

# Maximum correction cycles before forcing evaluation
_MAX_MOD_ITERS = 4


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class AgentState(TypedDict, total=False):
    messages:             list[dict[str, Any]]
    pending_tool_calls:   list[dict[str, Any]] | None
    final_response:       str | None
    iteration:            int
    max_iterations:       int
    tool_catalog:         str          # full catalog (kept for reference)
    layout_json_string:   str

    # Phase tracking — one of: "site" | "form" | "fix_orient" | "fix_form" | "report"
    phase:                str
    geometry_id:          str | None
    evaluation_done:      bool

    # Constraint correction loop
    constraint_results:   dict[str, Any] | None
    violations:           list[str]               # ["fit","setback","area","access","trees"]
    modification_iters:   int                     # correction cycles so far


# ---------------------------------------------------------------------------
# Violation categorisation
# ---------------------------------------------------------------------------

def _categorize_violations(results: dict[str, Any]) -> list[str]:
    """Map raw checker results to violation category names."""
    violations: list[str] = []

    fit = results.get("site_fit_checker_04", {}).get("data", {})
    if not fit.get("fits_within_site", True):
        violations.append("fit")

    setback = results.get("setback_checker_04", {}).get("data", {})
    if not setback.get("compliant", True):
        violations.append("setback")

    area = results.get("area_requirement_checker_04", {}).get("data", {})
    if not area.get("meets_requirement", True):
        violations.append("area")

    access = results.get("adjacency_access_checker_04", {}).get("data", {})
    if not access.get("access_adequate", True):
        violations.append("access")

    trees = results.get("tree_constraint_checker_04", {}).get("data", {})
    if not trees.get("no_conflicts", True):
        violations.append("trees")

    return violations


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def _route_after_read_site(state: AgentState) -> str:
    """read_site: execute pending tool calls, or advance to form planning."""
    return "tool" if state.get("pending_tool_calls") else "plan_form"


def _route_after_plan_form(state: AgentState) -> str:
    """plan_form: execute pending tool calls, or advance to constraint checking."""
    return "tool" if state.get("pending_tool_calls") else "check_constraints"


def _route_after_constraints(state: AgentState) -> str:
    """
    check_constraints: route based on violations found.
    Priority: access/orientation → fix_orientation first (often cascades to fix others).
    Form violations → fix_form.
    Clean or max cycles → evaluate.
    """
    violations = state.get("violations", [])
    mod_iters  = state.get("modification_iters", 0)

    if not violations or mod_iters >= _MAX_MOD_ITERS:
        return "evaluate"

    if "access" in violations:
        return "fix_orientation"

    if any(v in violations for v in ["fit", "setback", "area", "trees"]):
        return "fix_form"

    return "evaluate"


def _route_after_fix_orientation(state: AgentState) -> str:
    """fix_orientation: execute tools, or loop back to constraint checking."""
    return "tool" if state.get("pending_tool_calls") else "check_constraints"


def _route_after_fix_form(state: AgentState) -> str:
    """fix_form: execute tools, or loop back to constraint checking."""
    return "tool" if state.get("pending_tool_calls") else "check_constraints"


def _route_after_tool(state: AgentState) -> str:
    """After any tool execution: return to the reason node for the current phase."""
    return {
        "site":       "read_site",
        "form":       "plan_form",
        "fix_orient": "fix_orientation",
        "fix_form":   "fix_form",
    }.get(state.get("phase", "site"), "read_site")


# ---------------------------------------------------------------------------
# AUTO node: check_constraints
# ---------------------------------------------------------------------------

def _build_constraint_checker_node(mcp_client: Any) -> Any:
    """Runs all 5 constraint tools automatically.  No LLM involved."""

    def check_constraints(state: AgentState) -> dict:
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

        violations  = _categorize_violations(results)
        result_text = json.dumps(results, indent=2)
        viol_text   = (
            f"Violations detected: {violations}"
            if violations
            else "✓ All 5 constraints satisfied — no violations."
        )

        messages = list(state.get("messages", []))
        messages.append({
            "role": "user",
            "content": (
                f"=== CONSTRAINT CHECK RESULTS (cycle {cycle} of {_MAX_MOD_ITERS}) ===\n"
                f"{result_text}\n\n"
                f"{viol_text}\n"
                f"{'Next: apply targeted correction.' if violations else 'Next: proceed to evaluation.'}"
            ),
        })

        print(f"[check_constraints] cycle={cycle}  violations={violations}")
        return {
            "messages":           messages,
            "constraint_results": results,
            "violations":         violations,
            "pending_tool_calls": None,
            "modification_iters": cycle,
        }

    return check_constraints


# ---------------------------------------------------------------------------
# AUTO node: evaluate
# ---------------------------------------------------------------------------

def _build_evaluate_node(mcp_client: Any) -> Any:
    """Runs all 3 evaluation tools automatically.  No LLM involved."""

    def evaluate(state: AgentState) -> dict:
        geom_id    = state.get("geometry_id")
        eval_parts: list[str] = []

        for tool_name in _EVAL_TOOL_NAMES:
            args = {"geometry_id": geom_id} if geom_id else {}
            try:
                result = mcp_client.call_tool(tool_name, args)
                eval_parts.append(f"[{tool_name}]:\n{result}")
            except Exception as exc:
                eval_parts.append(f"[{tool_name}]: ERROR — {exc}")

        messages = list(state.get("messages", []))
        messages.append({
            "role": "user",
            "content": (
                "=== EVALUATION COMPLETE ===\n\n"
                + "\n\n".join(eval_parts)
                + "\n\nAll 3 evaluators done.  Proceed to final report."
            ),
        })

        print("[evaluate] All 3 evaluators complete.")
        return {
            "messages":           messages,
            "evaluation_done":    True,
            "pending_tool_calls": None,
        }

    return evaluate


# ---------------------------------------------------------------------------
# AUTO node: bake_output
# ---------------------------------------------------------------------------

def _build_bake_node(mcp_client: Any) -> Any:
    """Bakes the final geometry to Rhino automatically.  No LLM involved."""

    def bake_output(state: AgentState) -> dict:
        geom_id = state.get("geometry_id")
        if not geom_id:
            print("[bake_output] No geometry_id — skipping bake.")
            return {}
        try:
            raw  = mcp_client.call_tool("bake_geometry_id_04", {
                "geometry_id": geom_id,
                "layer_name":  "TerraPilot_Output",
            })
            data = json.loads(raw).get("data", {})
            print(f"[bake_output] Baked → Rhino GUID: {data.get('rhino_guid', 'unknown')}")
        except Exception as exc:
            print(f"[bake_output] Bake failed: {exc}")
        return {}

    return bake_output


# ---------------------------------------------------------------------------
# Shared tool executor with geometry_id extraction
# ---------------------------------------------------------------------------

def _build_tracked_tool_node(ctx: Any) -> Any:
    inner = build_tool_node(ctx.mcp_client, ctx.tools, ctx.edited_layout_path)

    def tracked_tool(state: AgentState) -> dict:
        pending    = state.get("pending_tool_calls") or []
        tool_names = [c.get("name", "") for c in pending]
        result     = inner(state)

        # Auto-extract geometry_id from shape tool responses
        if any(t in _SHAPE_TOOL_NAMES for t in tool_names):
            for msg in reversed(result.get("messages", [])):
                if msg.get("role") == "user" and msg.get("content", "").startswith("Tool result:"):
                    try:
                        payload = json.loads(msg["content"].removeprefix("Tool result:").strip())
                        gid = payload.get("data", {}).get("geometry_id")
                        if gid:
                            result["geometry_id"] = gid
                    except Exception:
                        pass
                    break

        return result

    return tracked_tool


# ---------------------------------------------------------------------------
# Phase catalog builder
# ---------------------------------------------------------------------------

def _fmt_phase_catalog(all_tools: list[dict], names: set[str]) -> str:
    return "\n".join(
        f"- {t['name']}: {t.get('description', '')} | inputSchema={json.dumps(t.get('inputSchema', {}))}"
        for t in all_tools if t.get("name") in names
    )


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------

def build_graph(ctx: Any) -> Any:
    all_tools = ctx.tools

    # Per-category tool catalogs for LLM phase prompts
    site_catalog   = _fmt_phase_catalog(all_tools, _SITE_TOOL_NAMES)
    form_catalog   = _fmt_phase_catalog(all_tools, _FORM_TOOL_NAMES)
    orient_catalog = _fmt_phase_catalog(all_tools, _ORIENT_TOOL_NAMES)
    modify_catalog = _fmt_phase_catalog(all_tools, _MODIFY_TOOL_NAMES)

    # ── LLM nodes (5) ────────────────────────────────────────────────────────
    read_site       = build_site_reader_node(ctx.llm, site_catalog)
    plan_form       = build_form_planner_node(ctx.llm, form_catalog)
    fix_orientation = build_orientation_fixer_node(ctx.llm, orient_catalog)
    fix_form        = build_form_modifier_node(ctx.llm, modify_catalog)
    write_report    = build_report_writer_node(ctx.llm)

    # ── AUTO nodes (3) ───────────────────────────────────────────────────────
    check_constraints = _build_constraint_checker_node(ctx.mcp_client)
    evaluate          = _build_evaluate_node(ctx.mcp_client)
    bake_output       = _build_bake_node(ctx.mcp_client)

    # ── Shared tool executor (1) ─────────────────────────────────────────────
    tool = _build_tracked_tool_node(ctx)

    graph = StateGraph(AgentState)

    # Register all 9 nodes
    graph.add_node("read_site",         read_site)
    graph.add_node("plan_form",         plan_form)
    graph.add_node("check_constraints", check_constraints)
    graph.add_node("fix_orientation",   fix_orientation)
    graph.add_node("fix_form",          fix_form)
    graph.add_node("evaluate",          evaluate)
    graph.add_node("write_report",      write_report)
    graph.add_node("bake_output",       bake_output)
    graph.add_node("tool",              tool)

    # ── Pipeline wiring ───────────────────────────────────────────────────────
    graph.add_edge(START, "read_site")

    graph.add_conditional_edges(
        "read_site", _route_after_read_site,
        {"tool": "tool", "plan_form": "plan_form"},
    )
    graph.add_conditional_edges(
        "plan_form", _route_after_plan_form,
        {"tool": "tool", "check_constraints": "check_constraints"},
    )
    graph.add_conditional_edges(
        "check_constraints", _route_after_constraints,
        {
            "fix_orientation": "fix_orientation",
            "fix_form":        "fix_form",
            "evaluate":        "evaluate",
        },
    )
    graph.add_conditional_edges(
        "fix_orientation", _route_after_fix_orientation,
        {"tool": "tool", "check_constraints": "check_constraints"},
    )
    graph.add_conditional_edges(
        "fix_form", _route_after_fix_form,
        {"tool": "tool", "check_constraints": "check_constraints"},
    )

    # After evaluate → write report → bake → done
    graph.add_edge("evaluate",     "write_report")
    graph.add_edge("write_report", "bake_output")
    graph.add_edge("bake_output",  END)

    # After any tool call, return to the current phase's reason node
    graph.add_conditional_edges(
        "tool", _route_after_tool,
        {
            "read_site":       "read_site",
            "plan_form":       "plan_form",
            "fix_orientation": "fix_orientation",
            "fix_form":        "fix_form",
        },
    )

    return graph.compile()


# ---------------------------------------------------------------------------
# Entry point — called from main.py and the notebook.
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
        "messages":           [{"role": "user", "content": prompt}],
        "pending_tool_calls": None,
        "final_response":     None,
        "iteration":          0,
        "max_iterations":     ctx.max_iterations,
        "tool_catalog":       _format_tool_catalog(ctx.tools),
        "layout_json_string": json.dumps(ctx.layout_data),
        "phase":              "site",
        "geometry_id":        None,
        "evaluation_done":    False,
        "constraint_results": None,
        "violations":         [],
        "modification_iters": 0,
    }

from nodes.tools import build_tool_node


# =============================================================================
# graph.py — TerraPilot agent graph.
#
# Architecture: 8-node phase-gated pipeline
#
#   START → site_reason ──(tools)──► tool ──► site_reason
#                      └──(done)──► form_reason ──(tools)──► tool ──► form_reason
#                                               └──(done)──► check_constraints
#                                                            ├──(access)──► orient_reason ──(tools)──► tool ──► orient_reason
#                                                            │                             └──(done)──► check_constraints (≤4 cycles)
#                                                            ├──(form)────► modify_reason ──(tools)──► tool ──► modify_reason
#                                                            │                             └──(done)──► check_constraints (≤4 cycles)
#                                                            └──(clean)──► auto_evaluate ──► synthesise_reason ──► END
#
# Nodes:
#   site_reason       LLM — reads site geometry, context, legal limits
#   form_reason       LLM — selects typology, generates initial building form
#   check_constraints AUTO — runs all 5 constraint checkers, categorises violations
#   orient_reason     LLM — fixes orientation / access violations (rotate, offset)
#   modify_reason     LLM — fixes form violations (scale, stretch, bend, terrace...)
#   auto_evaluate     AUTO — runs 3 evaluators (spatial, performance, integrity)
#   synthesise_reason LLM — bakes geometry, generates final architectural narrative
#   tool              SHARED — executes MCP tool calls for all LLM phase nodes
# =============================================================================


# ── Tool name sets per phase ──────────────────────────────────────────────────
_SITE_TOOL_NAMES   = {"site_boundary_reader_04", "context_reader_04", "legal_constraints_reader_04"}
_FORM_TOOL_NAMES   = {"shape_library_loader_04", "parametric_shape_generator_04"}
_ORIENT_TOOL_NAMES = {"rotate_mirror_tool_04", "scale_shape_tool_04"}
_MODIFY_TOOL_NAMES = {
    "scale_shape_tool_04", "stretch_arm_tool_04", "width_modifier_tool_04",
    "courtyard_modifier_tool_04", "bend_angle_tool_04", "terrace_step_tool_04",
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
_SHAPE_TOOL_NAMES = {"parametric_shape_generator_04", "shape_library_loader_04"}

# Maximum orient/modify correction cycles before forcing evaluation
_MAX_MOD_ITERS = 4


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class AgentState(TypedDict, total=False):
    messages:             list[dict[str, Any]]
    pending_tool_calls:   list[dict[str, Any]] | None
    final_response:       str | None
    iteration:            int
    max_iterations:       int
    tool_catalog:         str        # full catalog kept for reference / notebook use
    layout_json_string:   str

    # Phase tracking
    phase:                str        # "site"|"form"|"orient"|"modify"|"synthesise"
    geometry_id:          str | None
    evaluation_done:      bool

    # Constraint correction loop
    constraint_results:   dict[str, Any] | None   # per-tool checker results
    violations:           list[str]               # ["fit","setback","area","access","trees"]
    modification_iters:   int                     # number of check_constraints runs so far


# ---------------------------------------------------------------------------
# Violation categorisation
# ---------------------------------------------------------------------------

def _categorize_violations(results: dict[str, Any]) -> list[str]:
    """Parse checker results and return a list of violation category names."""
    violations: list[str] = []

    fit = results.get("site_fit_checker_04", {}).get("data", {})
    if not fit.get("fits_within_site", True):
        violations.append("fit")

    setback = results.get("setback_checker_04", {}).get("data", {})
    if not setback.get("compliant", True):
        violations.append("setback")

    area = results.get("area_requirement_checker_04", {}).get("data", {})
    if not area.get("meets_requirement", True):
        violations.append("area")

    access = results.get("adjacency_access_checker_04", {}).get("data", {})
    if not access.get("access_adequate", True):
        violations.append("access")

    trees = results.get("tree_constraint_checker_04", {}).get("data", {})
    if not trees.get("no_conflicts", True):
        violations.append("trees")

    return violations


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def _route_after_site(state: AgentState) -> str:
    """After site_reason: execute tools OR advance to form placement."""
    if state.get("pending_tool_calls"):
        return "tool"
    return "form_reason"


def _route_after_form(state: AgentState) -> str:
    """After form_reason: execute tools OR advance to constraint checking."""
    if state.get("pending_tool_calls"):
        return "tool"
    return "check_constraints"


def _route_after_constraints(state: AgentState) -> str:
    """Route to orientation fix, form fix, or evaluation based on violations."""
    violations = state.get("violations", [])
    mod_iters  = state.get("modification_iters", 0)

    # Force evaluation after too many cycles or when all constraints pass
    if not violations or mod_iters >= _MAX_MOD_ITERS:
        return "evaluate"

    # Fix orientation/access first — rotation often resolves other violations too
    if "access" in violations:
        return "orient"

    # Fix form violations (fit, setback, area, trees)
    if any(v in violations for v in ["fit", "setback", "area", "trees"]):
        return "modify"

    return "evaluate"


def _route_after_orient(state: AgentState) -> str:
    """After orient_reason: execute tools OR re-check constraints."""
    if state.get("pending_tool_calls"):
        return "tool"
    return "check_constraints"


def _route_after_modify(state: AgentState) -> str:
    """After modify_reason: execute tools OR re-check constraints."""
    if state.get("pending_tool_calls"):
        return "tool"
    return "check_constraints"


def _route_after_tool(state: AgentState) -> str:
    """After any tool execution: return to the reason node for the current phase."""
    phase_map = {
        "site":       "site_reason",
        "form":       "form_reason",
        "orient":     "orient_reason",
        "modify":     "modify_reason",
        "synthesise": "synthesise_reason",
    }
    return phase_map.get(state.get("phase", "site"), "synthesise_reason")


def _route_after_synthesise(state: AgentState) -> str:
    """After synthesise_reason: execute bake tool OR finish."""
    if state.get("pending_tool_calls"):
        return "tool"
    return "finish"


# ---------------------------------------------------------------------------
# Automatic constraint-checking node
# ---------------------------------------------------------------------------

def _build_constraint_checker_node(mcp_client: Any) -> Any:
    """Runs all 5 constraint tools automatically and categorises violations."""

    def check_constraints(state: AgentState) -> dict:
        geom_id     = state.get("geometry_id")
        layout_json = state.get("layout_json_string", "{}")
        results: dict[str, Any] = {}

        for tool_name in _CONSTRAINT_TOOL_NAMES:
            args: dict[str, Any] = {"layout_json": layout_json}
            if geom_id:
                args["geometry_id"] = geom_id
            try:
                raw = mcp_client.call_tool(tool_name, args)
                results[tool_name] = json.loads(raw)
            except Exception as exc:
                results[tool_name] = {"success": False, "error": str(exc)}

        violations  = _categorize_violations(results)
        result_text = json.dumps(results, indent=2)
        viol_text   = (
            f"Violations detected: {violations}" if violations
            else "No violations — all constraints satisfied."
        )

        messages = list(state.get("messages", []))
        messages.append({
            "role": "user",
            "content": f"=== Constraint Check Results ===\n{result_text}\n\n{viol_text}",
        })

        print(f"[check_constraints] Violations: {violations}")

        return {
            "messages":           messages,
            "constraint_results": results,
            "violations":         violations,
            "pending_tool_calls": None,
            "modification_iters": state.get("modification_iters", 0) + 1,
        }

    return check_constraints


# ---------------------------------------------------------------------------
# Automatic evaluation node
# ---------------------------------------------------------------------------

def _build_auto_evaluate_node(mcp_client: Any) -> Any:
    """Runs all 3 evaluators automatically, then advances phase to synthesise."""

    def auto_evaluate(state: AgentState) -> dict:
        geom_id    = state.get("geometry_id")
        eval_parts: list[str] = []

        for tool_name in _EVAL_TOOL_NAMES:
            args = {"geometry_id": geom_id} if geom_id else {}
            try:
                result = mcp_client.call_tool(tool_name, args)
                eval_parts.append(f"[{tool_name}]:\n{result}")
            except Exception as exc:
                eval_parts.append(f"[{tool_name}]: ERROR — {exc}")

        messages = list(state.get("messages", []))
        messages.append({
            "role": "user",
            "content": (
                "=== Automatic Evaluation Complete ===\n\n"
                + "\n\n".join(eval_parts)
                + "\n\nAll evaluators done. Proceeding to final synthesis."
            ),
        })

        print("[auto_evaluate] All 3 evaluators complete.")

        return {
            "messages":           messages,
            "evaluation_done":    True,
            "phase":              "synthesise",
            "final_response":     None,
            "pending_tool_calls": None,
        }

    return auto_evaluate


# ---------------------------------------------------------------------------
# Tracked tool node — shared executor with geometry_id extraction
# ---------------------------------------------------------------------------

def _build_tracked_tool_node(ctx: Any) -> Any:
    inner = build_tool_node(ctx.mcp_client, ctx.tools, ctx.edited_layout_path)

    def tracked_tool(state: AgentState) -> dict:
        pending    = state.get("pending_tool_calls") or []
        tool_names = [c.get("name", "") for c in pending]

        result = inner(state)

        # Auto-extract geometry_id when a shape tool is executed
        if any(t in _SHAPE_TOOL_NAMES for t in tool_names):
            for msg in reversed(result.get("messages", [])):
                if msg.get("role") == "user" and msg.get("content", "").startswith("Tool result:"):
                    try:
                        payload = json.loads(msg["content"].removeprefix("Tool result:").strip())
                        gid = payload.get("data", {}).get("geometry_id")
                        if gid:
                            result["geometry_id"] = gid
                    except Exception:
                        pass
                    break

        return result

    return tracked_tool

