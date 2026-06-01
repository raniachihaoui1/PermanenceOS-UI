from __future__ import annotations
import json
import math
from pathlib import Path
from typing import Any
from _runtime.llm import write_tool_result


# ---------------------------------------------------------------------------
# Action tool catalogue — used by the reason node and the Streamlit app.
# ---------------------------------------------------------------------------

def get_action_tools() -> list[dict]:
    """Return tool definitions (name, description, inputSchema) for the LLM."""
    return [
        {
            "name": "tag_and_audit",
            "description": (
                "Generate a structural column/beam grid for the current floor plan. "
                "Call ONLY when the user explicitly requests structure generation. "
                "Required args: layout_json (injected automatically), typology, grid_spacing."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "layout_json": {"type": "string", "description": "Floor plan JSON (injected)"},
                    "typology": {
                        "type": "string",
                        "enum": ["column_grid", "perimeter_load_bearing", "shear_wall"],
                        "description": "Structural typology — use column_grid unless specified",
                    },
                    "grid_spacing": {
                        "type": "number",
                        "description": "Target column grid spacing in metres (default 4.0)",
                    },
                },
                "required": ["layout_json", "typology", "grid_spacing"],
            },
        },
        {
            "name": "modify_structure",
            "description": (
                "Apply a targeted structural modification: remove an element, add a column, "
                "or set an attribute on an element."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "layout_json": {"type": "string", "description": "Floor plan JSON (injected)"},
                    "action": {
                        "type": "string",
                        "enum": ["remove", "add_column", "set_attribute"],
                        "description": "Type of modification",
                    },
                    "element_id": {
                        "type": "string",
                        "description": "ID of the element to modify or remove",
                    },
                    "attribute": {
                        "type": "string",
                        "description": "Attribute name (for set_attribute action)",
                    },
                    "value": {
                        "type": "string",
                        "description": "New attribute value (for set_attribute action)",
                    },
                    "position": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Column position [x, y] (for add_column action)",
                    },
                },
                "required": ["layout_json", "action"],
            },
        },
        {
            "name": "evaluate_structure",
            "description": (
                "Run first-principles structural checks (bending, shear, deflection, buckling) "
                "on the current layout."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "layout_json": {"type": "string", "description": "Floor plan JSON (injected)"},
                },
                "required": ["layout_json"],
            },
        },
        {
            "name": "compare_structure",
            "description": "Summarise structural changes between two layout states.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "before_json": {"type": "string", "description": "Previous layout JSON"},
                    "after_json":  {"type": "string", "description": "Updated layout JSON"},
                },
                "required": ["before_json", "after_json"],
            },
        },
    ]


def format_load_path_for_llm(load_path_result: dict | None) -> str:
    """Format load-path analysis as a compact text block for LLM context injection."""
    if not load_path_result:
        return ""
    elements       = load_path_result.get("elements", [])
    narrative      = load_path_result.get("narrative", "")
    critical_path  = load_path_result.get("critical_path", [])
    anchor_columns = load_path_result.get("anchor_columns", [])

    lines = ["LOAD PATH ANALYSIS:", narrative]
    if anchor_columns:
        lines.append(f"Anchor columns (primary load points): {', '.join(anchor_columns)}")
    if critical_path:
        lines.append(f"Critical path: {' → '.join(critical_path)}")
    lines.append("Stress Hierarchy (highest utilisation first):")
    for e in elements[:10]:
        util_pct = f"{e['utilization'] * 100:.0f}%"
        trib = f"  trib={e['tributary_area_m2']}m²" if e.get("tributary_area_m2") else ""
        pkn  = f"  P={e['P_kN']}kN" if e.get("P_kN") else ""
        lines.append(
            f"  {e['id']:8s} {e['role']:20s} {util_pct:5s} "
            f"[{e['load_responsibility']}]{trib}{pkn}  {e['details']}"
        )
    return "\n".join(lines)


def build_structural_grid_with_options(
    layout: dict,
    _unused: str = "",
    *,
    material: str = "RCC",
    sdl_kNm2: float = 3.5,
    ll_kNm2: float = 2.0,
) -> dict:
    """
    Generate structural grid options for the given layout.
    Returns {"options": [...]} where each option has:
      label, spacing (max beam span m), failures, cost (USD), layout, evaluation.
    """
    from nodes.tag_and_audit import generate_structure
    from nodes.evaluate import evaluate_structure
    from nodes.modify import apply_material_override, DEFAULT_SECTIONS

    raw_options = generate_structure(layout)
    if not isinstance(raw_options, list):
        raw_options = [raw_options] if isinstance(raw_options, dict) else []

    _cost_m3 = {"RCC": 350.0, "STEEL": 12_000.0, "TIMBER": 800.0}
    mat_key = "RCC" if "RCC" in material.upper() else ("STEEL" if "STEEL" in material.upper() else "TIMBER")
    cost_m3 = _cost_m3.get(mat_key, 350.0)
    sec = DEFAULT_SECTIONS.get(material, DEFAULT_SECTIONS["RCC"])
    beam_d = sec["beam_depth_mm"] / 1000.0
    beam_w = sec["beam_width_mm"] / 1000.0
    col_dims = sec["col_dims"]
    if "x" in col_dims:
        cw, cd = (float(v) / 1000.0 for v in col_dims.split("x", 1))
    else:
        cw = cd = float(col_dims) / 1000.0
    col_h = 3.0  # assumed storey height

    options = []
    for i, opt_layout in enumerate(raw_options):
        if not isinstance(opt_layout, dict):
            continue

        opt_str = apply_material_override(json.dumps(opt_layout), material)

        ev = None
        failures = 0
        try:
            ev = evaluate_structure(opt_str, ll_kNm2=ll_kNm2, sdl_kNm2=sdl_kNm2)
            if ev:
                s = ev.get("summary", {})
                failures = s.get("beam_failures", 0) + s.get("column_failures", 0)
        except Exception:
            pass

        structure = opt_layout.get("structure", [])
        beams = [el for el in structure if len(el.get("geometry", [])) == 2]
        cols  = [el for el in structure if len(el.get("geometry", [])) == 1]

        max_span = max(
            (math.dist(bm["geometry"][0], bm["geometry"][1]) for bm in beams),
            default=0.0,
        )

        beam_vol = sum(math.dist(bm["geometry"][0], bm["geometry"][1]) * beam_d * beam_w for bm in beams)
        col_vol  = len(cols) * cw * cd * col_h
        cost = (beam_vol + col_vol) * cost_m3

        options.append({
            "label":      f"Option {i + 1}",
            "spacing":    round(max_span, 2),
            "failures":   failures,
            "cost":       round(cost),
            "layout":     json.loads(opt_str),
            "evaluation": ev,
        })

    return {"options": options}


# ---------------------------------------------------------------------------
# Tool node — executes MCP tool calls requested by the reason node.
# ---------------------------------------------------------------------------

def build_tool_node(mcp_client, allowed_tools, edited_layout_path):
    """Return a tool node function ready to be added to a LangGraph StateGraph."""

    allowed_names = {t["name"] for t in allowed_tools if t.get("name")}

    def tool_node(state):

        # Iterate over the pending tool calls
        for call in state["pending_tool_calls"]:

            # Stop the process if max number of iterations is reached
            state["iteration"] += 1
            if state["iteration"] > state["max_iterations"]:
                raise RuntimeError("Max iterations exceeded")


            # Get the tool name and check its valid
            tool_name = call["name"]
            if tool_name not in allowed_names:
                raise RuntimeError(f"Tool '{tool_name}' is not in the allowed tools list")
            
            print(f"Calling tool: {tool_name} with arguments: {call['arguments']}")

            # Cleanup any null values accidentally included by the LLM
            tool_args = {k: v for k, v in call["arguments"].items() if v is not None}

            # Inject layout_json
            if "layout_json" in tool_args:
                tool_args["layout_json"] = state["layout_json_string"]

            # Call the tool
            tool_output = mcp_client.call_tool(tool_name, tool_args)

            # Only persist results that look like a layout (have layoutId or rooms)
            try:
                _parsed = json.loads(tool_output.strip())
                if isinstance(_parsed, dict) and ("layoutId" in _parsed or "rooms" in _parsed):
                    write_tool_result(tool_output, edited_layout_path)
            except (json.JSONDecodeError, AttributeError):
                pass

            # If the tool returned valid JSON, update the layout in state so
            # subsequent tool calls in this loop receive the latest layout.
            try:
                updated = json.loads(tool_output.strip())
                if isinstance(updated, dict):
                    state["layout_json_string"] = json.dumps(updated)
            except (json.JSONDecodeError, AttributeError):
                pass

            # Append the tool call and its result to the conversation history
            state["messages"].append({
                "role": "assistant",
                "content": json.dumps({
                    "action": "tool",
                    "final_response": "",
                    "tool_calls": [{"name": tool_name, "arguments": tool_args}],
                }),
            })
            
            state["messages"].append({
                "role": "user",
                "content": f"Tool result: {tool_output}",
            })
            print(f"Tool result: {tool_output}")

        state["pending_tool_calls"] = None
        return state

    return tool_node
