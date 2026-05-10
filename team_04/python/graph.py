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
# graph.py â€” TerraPilot agent graph.
#
# Architecture: 9-node category-based pipeline
#
# Each node has ONE named, unambiguous role.  Tool groups map 1-to-1 to nodes:
#
#   Node               Kind    Tool category           Tools
#   â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
#   write_report       LLM     Report writing          (no tools â€” LLM only)
#   bake_output        AUTO    Output                  bake_geometry_id_04
#   tool               SHARED  Tool executor           (all phases share this)
#
# Flow:
#   START â†’ read_site â”€â”€(tool loop)â”€â–º plan_form â”€â”€(tool loop)â”€â–º check_constraints
#             check_constraints â”€â”€[access violation]â”€â”€â–º fix_orientation â”€â”€(tool loop)â”€â–ºâ”
#             check_constraints â”€â”€[form violation]â”€â”€â”€â”€â–º fix_form â”€â”€(tool loop)â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¤
#             check_constraints â”€â”€[clean or â‰¤4 cycles]â–º evaluate â†’ write_report â†’ bake_output â†’ END
#                                                                         â–²
#             fix_orientation â”€(done)â”€â–º check_constraints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¤ (loop â‰¤ 4Ã—)
#             fix_form        â”€(done)â”€â–º check_constraints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
#
# Key improvement over previous design
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Previous:  LLM nodes were called repeatedly in the same phase â€” once to plan
#            tool calls, again to process results, again to decide what to do
#            next.  It was impossible to tell whether a node's output was
#            planning the next step or summarising the last one.
#
# Now:       Each LLM node is called in exactly TWO modes, written into the prompt:
#              MODE A (planning)  â€” no tool results yet â†’ action="tool"
#              MODE B (summary)   â€” results received â†’ action="final" + phase summary
#            The summary is appended to messages as an assistant message, making
#            the conversation log a clear, structured timeline of what happened.
#
#            write_report does NOT call tools (baking is handled by bake_output AUTO).
#            evaluate and check_constraints are fully AUTO â€” no LLM needed.
# =============================================================================


# â”€â”€ Tool name sets per category â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    # Phase tracking â€” one of: "site" | "form" | "fix_orient" | "fix_form" | "report"
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
    Priority: access/orientation â†’ fix_orientation first (often cascades to fix others).
    Form violations â†’ fix_form.
    Clean or max cycles â†’ evaluate.
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
            else "âœ“ All 5 constraints satisfied â€” no violations."
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
                eval_parts.append(f"[{tool_name}]: ERROR â€” {exc}")

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
            print("[bake_output] No geometry_id â€” skipping bake.")
            return {}
        try:
            raw  = mcp_client.call_tool("bake_geometry_id_04", {
                "geometry_id": geom_id,
                "layer_name":  "TerraPilot_Output",
            })
            data = json.loads(raw).get("data", {})
            print(f"[bake_output] Baked â†’ Rhino GUID: {data.get('rhino_guid', 'unknown')}")
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

    # â”€â”€ LLM nodes (5) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    read_site       = build_site_reader_node(ctx.llm, site_catalog)
    plan_form       = build_form_planner_node(ctx.llm, form_catalog)
    fix_orientation = build_orientation_fixer_node(ctx.llm, orient_catalog)
    fix_form        = build_form_modifier_node(ctx.llm, modify_catalog)
    write_report    = build_report_writer_node(ctx.llm)

    # â”€â”€ AUTO nodes (3) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    check_constraints = _build_constraint_checker_node(ctx.mcp_client)
    evaluate          = _build_evaluate_node(ctx.mcp_client)
    bake_output       = _build_bake_node(ctx.mcp_client)

    # â”€â”€ Shared tool executor (1) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    # â”€â”€ Pipeline wiring â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    # After evaluate â†’ write report â†’ bake â†’ done
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
# Entry point â€” called from main.py and the notebook.
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

