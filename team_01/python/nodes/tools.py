from __future__ import annotations
import json
import math
from typing import Any
from _runtime.llm import write_tool_result
from nodes.modify import (
    _generate_column_grid, apply_material_override,
    apply_minimum_sections, upgrade_element_section,
    add_midspan_column, remove_element,
    BEAM_SECTION_UPGRADE, COL_SECTION_UPGRADE,
    BEAM_DIM_UPGRADE, COL_DIM_UPGRADE,
)
from nodes.evaluate import evaluate_structure
from nodes.comparison import _slim_diff_for_llm


# ── Tool catalog (schema exposed to the LLM in the system prompt) ──────────────

LOCAL_ACTION_TOOLS: list[dict[str, Any]] = [
    {
        "name": "tag_and_audit",
        "description": "Create structural grid when none exists, or audit existing structure without overwriting.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "layout_json":   {"type": "string"},
                "typology":      {"type": "string"},
                "grid_spacing":  {"type": "number"},
                "material":      {"type": "string"},
            },
            "required": [],
            "additionalProperties": True,
        },
    },
    {
        "name": "modify_structure",
        "description": "Apply a local structural edit (remove, add_column, or set_attribute).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "layout_json": {"type": "string"},
                "operation":   {"type": "string"},
                "element_id":  {"type": "string"},
                "x":           {"type": "number"},
                "y":           {"type": "number"},
                "attributes":  {"type": "object"},
            },
            "required": ["operation"],
            "additionalProperties": True,
        },
    },
    {
        "name": "evaluate_structure",
        "description": "Evaluate current structure from first principles (EC2/EC3/EN338).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "layout_json": {"type": "string"},
            },
            "required": [],
            "additionalProperties": True,
        },
    },
    {
        "name": "compare_structure",
        "description": "Compare original and current structure arrays and summarize changes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "before_layout_json": {"type": "string"},
                "after_layout_json":  {"type": "string"},
            },
            "required": [],
            "additionalProperties": True,
        },
    },
]


def get_action_tools() -> list[dict[str, Any]]:
    return [dict(tool) for tool in LOCAL_ACTION_TOOLS]


# ── Structural grid generator (3 spacing variants) ─────────────────────────────

def _quick_cost(layout: dict) -> float:
    """Rough material cost estimate (volume × unit price)."""
    structure = layout.get("structure", [])
    total = 0.0
    for el in structure:
        attrs = el.get("attributes", {})
        mat = attrs.get("material", "RCC").upper()
        geom = el.get("geometry", [])
        if len(geom) == 2:
            length_m = math.dist(geom[0], geom[1])
            w = float(attrs.get("width", 200)) / 1000
            d = float(attrs.get("depth", 300)) / 1000
            vol = w * d * length_m
        else:
            h = float(attrs.get("height", 3.5))
            dims = attrs.get("dimensions", "200x200")
            try:
                wx, dy = (float(p) for p in dims.split("x", 1))
            except Exception:
                wx, dy = 200.0, 200.0
            vol = (wx / 1000) * (dy / 1000) * h
        if "STEEL" in mat:
            total += vol * 7850 * 2.0
        elif "TIMBER" in mat:
            total += vol * 700.0
        else:
            total += vol * 200.0
    return round(total, 2)


def build_structural_grid_with_options(
    layout: dict,
    prompt: str,
    material: str = "RCC",
) -> dict:
    """
    Generate Conservative / Balanced / Open column-grid variants.
    Returns {options: [...], recommended: {...}} where each option has
    {label, spacing, layout, score, rationale, failures, cost}.
    """
    variants = [
        ("Conservative", 4.25),
        ("Balanced",     5.0),
        ("Open",         5.75),
    ]
    base_json = json.dumps(layout)
    options = []

    for label, spacing in variants:
        grid_json    = _generate_column_grid(base_json, spacing)
        grid_json    = apply_material_override(grid_json, material)
        grid_layout  = json.loads(grid_json)

        try:
            ev       = evaluate_structure(grid_json)
            summary  = ev.get("summary", {})
            failures = summary.get("beam_failures", 0) + summary.get("column_failures", 0)
        except Exception:
            failures = 0

        n_el  = len(grid_layout.get("structure", []))
        cost  = _quick_cost(grid_layout)
        # Lower score = better: penalise failures heavily, slight preference for compact grids
        score = round(failures * 100 + abs(n_el - 20) * 2 + cost * 0.001, 2)

        options.append({
            "label":    label,
            "spacing":  spacing,
            "layout":   grid_layout,
            "score":    score,
            "rationale": (
                f"{n_el} elements at {spacing}m spacing, "
                f"{failures} structural failures, cost ~€{cost:,.0f}"
            ),
            "failures": failures,
            "cost":     cost,
        })

    # Allow prompt keywords to bias the recommendation
    lower = prompt.lower() if prompt else ""
    if any(k in lower for k in ("conservative", "tight", "dense", "small spacing")):
        recommended = next((o for o in options if o["label"] == "Conservative"), None)
    elif any(k in lower for k in ("open", "wide", "large spacing", "minimal column")):
        recommended = next((o for o in options if o["label"] == "Open"), None)
    else:
        recommended = None
    if recommended is None:
        recommended = min(options, key=lambda o: o["score"])
    return {"options": options, "recommended": recommended}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _extract_user_prompt(state: dict[str, Any]) -> str:
    for msg in state.get("messages", []):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if "User request:" in content:
            return content.split("User request:", 1)[-1].split("\n", 1)[0].strip()
        return content.strip()
    return ""


def _apply_local_modify(layout: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    operation = str(args.get("operation", "")).strip().lower()
    structure = list(layout.get("structure") or [])
    updated   = json.loads(json.dumps(layout))

    if operation == "remove":
        element_id  = str(args.get("element_id", "")).strip()
        updated_str = remove_element(json.dumps(layout), element_id)
        return json.loads(updated_str)

    if operation == "add_column":
        x      = float(args.get("x", 0.0))
        y      = float(args.get("y", 0.0))
        new_id = str(args.get("element_id") or f"C_LOCAL_{len(structure) + 1}")
        attrs  = dict(args.get("attributes") or {})
        attrs.setdefault("type", "structural_column")
        attrs.setdefault("material", "RCC")
        attrs.setdefault("dimensions", "200x200")
        structure.append({
            "id":       new_id,
            "name":     f"Column_{new_id}",
            "geometry": [[round(x, 3), round(y, 3)]],
            "attributes": attrs,
        })
        updated["structure"] = structure
        return updated

    if operation == "set_attribute":
        element_id = str(args.get("element_id", "")).strip()
        patch      = dict(args.get("attributes") or {})
        for item in structure:
            if item.get("id") == element_id:
                item.setdefault("attributes", {}).update(patch)
        updated["structure"] = structure
        return updated

    return updated


# ── Combined action node (LLM tool calls + structural changes from evaluate) ───

def build_tool_node(edited_layout_path, allowed_tools=None):
    tools         = allowed_tools or LOCAL_ACTION_TOOLS
    allowed_names = {t["name"] for t in tools if t.get("name")}

    def tool_node(state):
        print(f"\n{'='*50}")
        print("  NODE: ACTION")
        print(f"{'='*50}")

        # Snapshot layout before any modification (for comparison node diff)
        if not state.get("original_layout_json_string"):
            state["original_layout_json_string"] = state["layout_json_string"]

        # ── Structural change dispatched by the evaluate menu ─────────────────
        change = state.get("pending_structural_change")
        if change:
            layout_str = state["layout_json_string"]
            t          = change["type"]
            print(f"  Applying structural change: {t}")

            if t == "tier_upgrade":
                layout_str = apply_material_override(layout_str, change["tier"])
                state["material_override"] = change["tier"]

            elif t == "material_switch":
                layout_str = apply_material_override(layout_str, change["material"])
                state["material_override"] = change["material"]

            elif t == "upgrade_element":
                layout_str = upgrade_element_section(
                    layout_str, change["element_id"], change["new_section"]
                )

            elif t == "midspan_column":
                layout_str = add_midspan_column(
                    layout_str, change["beam_id"], change["material"]
                )

            elif t in ("auto_upgrade_beams", "auto_upgrade_columns"):
                result = json.loads(state.get("evaluation_result", "{}"))
                if t == "auto_upgrade_beams":
                    for b in result.get("beams", []):
                        if b["bend_PASS"] and b["shear_PASS"] and b["defl_TL_PASS"] and b["defl_LL_PASS"]:
                            continue
                        cur = b.get("section_mm", "")
                        if cur in BEAM_SECTION_UPGRADE:
                            nxt, _, _ = BEAM_SECTION_UPGRADE[cur]
                            layout_str = upgrade_element_section(layout_str, b["id"], nxt)
                        elif cur in BEAM_DIM_UPGRADE:
                            nxt, _, _ = BEAM_DIM_UPGRADE[cur]
                            layout_str = upgrade_element_section(layout_str, b["id"], nxt)
                else:
                    for c in result.get("columns", []):
                        if c["stress_PASS"] and c["buckling_PASS"]:
                            continue
                        cur = c.get("section_mm", "")
                        if cur in COL_SECTION_UPGRADE:
                            nxt, _ = COL_SECTION_UPGRADE[cur]
                            layout_str = upgrade_element_section(layout_str, c["id"], nxt)
                        elif cur in COL_DIM_UPGRADE:
                            nxt = COL_DIM_UPGRADE[cur]
                            layout_str = upgrade_element_section(layout_str, c["id"], nxt)

            elif t == "find_minimum":
                layout_str = apply_minimum_sections(layout_str, change["material"])
                state["material_override"] = change["material"]
                state["find_minimum_done"] = True

            elif t == "remove_element":
                layout_str = remove_element(layout_str, change["element_id"])

            state["layout_json_string"]    = layout_str
            state["pending_structural_change"] = None
            state["came_from"]             = "structural_change"
            write_tool_result(layout_str, edited_layout_path)
            return state

        # ── LLM-directed tool calls ───────────────────────────────────────────
        last_tool_name = None

        for call in state["pending_tool_calls"]:
            state["iteration"] += 1
            if state["iteration"] > state["max_iterations"]:
                raise RuntimeError("Max iterations exceeded")

            tool_name      = call["name"]
            last_tool_name = tool_name
            if tool_name not in allowed_names:
                raise RuntimeError(f"Tool '{tool_name}' is not in the allowed tools list")

            print(f"Calling tool: {tool_name} with arguments: {call['arguments']}")

            tool_args = {k: v for k, v in call["arguments"].items() if v is not None}
            if "layout_json" in tool_args:
                tool_args["layout_json"] = state["layout_json_string"]

            current_layout = json.loads(state["layout_json_string"])

            if tool_name == "tag_and_audit":
                structure_count = len(current_layout.get("structure", []))
                if structure_count == 0:
                    prompt_text = _extract_user_prompt(state)
                    material    = str(
                        tool_args.get("material") or state.get("material_override") or "RCC"
                    ).upper()
                    bundle         = build_structural_grid_with_options(
                        current_layout, prompt_text, material=material
                    )
                    tool_output_obj = bundle["recommended"]["layout"]
                else:
                    tool_output_obj = current_layout

            elif tool_name == "modify_structure":
                tool_output_obj = _apply_local_modify(current_layout, tool_args)

            elif tool_name == "evaluate_structure":
                evaluation = evaluate_structure(state["layout_json_string"])
                state["evaluation_result"] = json.dumps(evaluation)
                tool_output_obj = {"evaluation": evaluation}

            elif tool_name == "compare_structure":
                before = (
                    tool_args.get("before_layout_json")
                    or state.get("original_layout_json_string")
                    or state["layout_json_string"]
                )
                after      = tool_args.get("after_layout_json") or state["layout_json_string"]
                comparison = _slim_diff_for_llm(before, after)
                state["comparison_result"] = comparison
                tool_output_obj = {"comparison": comparison}

            else:
                raise RuntimeError(f"Unsupported local action: {tool_name}")

            tool_output = json.dumps(tool_output_obj, ensure_ascii=False)

            if isinstance(tool_output_obj, dict) and (
                "layoutId" in tool_output_obj or "rooms" in tool_output_obj
            ):
                state["layout_json_string"] = json.dumps(tool_output_obj)
                write_tool_result(tool_output, edited_layout_path)

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
            print(
                f"Tool result: {tool_output[:200]}..."
                if len(tool_output) > 200 else
                f"Tool result: {tool_output}"
            )

        state["pending_tool_calls"] = None
        state["came_from"] = (
            "tag_and_audit" if last_tool_name == "tag_and_audit" else "modify"
        )
        return state

    return tool_node
