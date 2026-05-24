from __future__ import annotations
import json
from typing import Any
from nodes.comparison import summarize_local_comparison
from nodes.evaluate import evaluate_structure
from nodes.structural_grid import build_structural_grid_with_options
from _runtime.llm import write_tool_result


# ---------------------------------------------------------------------------
# Local action catalog
# ---------------------------------------------------------------------------

LOCAL_ACTION_TOOLS: list[dict[str, Any]] = [
    {
        "name": "tag_and_audit",
        "description": "Create structural grid when none exists, or audit existing structure without overwriting.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "layout_json": {"type": "string"},
                "typology": {"type": "string"},
                "grid_spacing": {"type": "number"},
                "material": {"type": "string"},
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
                "operation": {"type": "string"},
                "element_id": {"type": "string"},
                "x": {"type": "number"},
                "y": {"type": "number"},
                "attributes": {"type": "object"},
            },
            "required": ["operation"],
            "additionalProperties": True,
        },
    },
    {
        "name": "evaluate_structure",
        "description": "Evaluate current structure from first principles.",
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
                "after_layout_json": {"type": "string"},
            },
            "required": [],
            "additionalProperties": True,
        },
    },
]


def get_action_tools() -> list[dict[str, Any]]:
    return [dict(tool) for tool in LOCAL_ACTION_TOOLS]


def _extract_user_prompt(state: dict[str, Any]) -> str:
    for message in state.get("messages", []):
        if message.get("role") != "user":
            continue
        content = message.get("content", "")
        if "User request:" in content:
            return content.split("User request:", 1)[-1].split("\n", 1)[0].strip()
        return content.strip()
    return ""


def _apply_local_modify(layout: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    operation = str(args.get("operation", "")).strip().lower()
    structure = list(layout.get("structure") or [])
    updated = json.loads(json.dumps(layout))

    if operation == "remove":
        element_id = str(args.get("element_id", "")).strip()
        updated["structure"] = [item for item in structure if item.get("id") != element_id]
        return updated

    if operation == "add_column":
        x = float(args.get("x", 0.0))
        y = float(args.get("y", 0.0))
        new_id = str(args.get("element_id") or f"C_LOCAL_{len(structure) + 1}")
        attributes = dict(args.get("attributes") or {})
        attributes.setdefault("type", "structural_column")
        attributes.setdefault("material", "RCC")
        attributes.setdefault("dimensions", "200x200")
        structure.append(
            {
                "id": new_id,
                "name": f"Column_{new_id}",
                "geometry": [[round(x, 3), round(y, 3)]],
                "attributes": attributes,
            }
        )
        updated["structure"] = structure
        return updated

    if operation == "set_attribute":
        element_id = str(args.get("element_id", "")).strip()
        patch = dict(args.get("attributes") or {})
        for item in structure:
            if item.get("id") == element_id:
                attrs = item.setdefault("attributes", {})
                attrs.update(patch)
        updated["structure"] = structure
        return updated

    return updated


def build_tool_node(edited_layout_path, allowed_tools=None):
    """Return a local action node compatible with the existing graph/reason contract."""

    tools = allowed_tools or LOCAL_ACTION_TOOLS
    allowed_names = {t["name"] for t in tools if t.get("name")}

    def tool_node(state):
        print(f"\n{'='*50}")
        print("  NODE: ACTION")
        print(f"{'='*50}")

        last_tool_name = None

        for call in state["pending_tool_calls"]:
            state["iteration"] += 1
            if state["iteration"] > state["max_iterations"]:
                raise RuntimeError("Max iterations exceeded")

            tool_name = call["name"]
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
                    prompt = _extract_user_prompt(state)
                    material = str(
                        tool_args.get("material") or state.get("material_override") or "RCC"
                    ).upper()
                    bundle = build_structural_grid_with_options(current_layout, prompt, material=material)
                    updated_layout = bundle["recommended"]["layout"]
                    tool_output_obj = updated_layout
                else:
                    # Audit-only mode: do not overwrite existing structure.
                    tool_output_obj = current_layout

            elif tool_name == "modify_structure":
                updated_layout = _apply_local_modify(current_layout, tool_args)
                tool_output_obj = updated_layout

            elif tool_name == "evaluate_structure":
                evaluation = evaluate_structure(state["layout_json_string"])
                state["evaluation_result"] = json.dumps(evaluation)
                tool_output_obj = {"evaluation": evaluation}

            elif tool_name == "compare_structure":
                before_layout = tool_args.get("before_layout_json") or state.get("original_layout_json_string") or state["layout_json_string"]
                after_layout = tool_args.get("after_layout_json") or state["layout_json_string"]
                comparison = summarize_local_comparison(before_layout, after_layout)
                state["comparison_result"] = comparison
                tool_output_obj = {"comparison": comparison}

            else:
                raise RuntimeError(f"Unsupported local action: {tool_name}")

            tool_output = json.dumps(tool_output_obj, ensure_ascii=False)

            if isinstance(tool_output_obj, dict) and ("layoutId" in tool_output_obj or "rooms" in tool_output_obj):
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
            print(f"Tool result: {tool_output[:200]}..." if len(tool_output) > 200 else f"Tool result: {tool_output}")

        state["pending_tool_calls"] = None
        state["came_from"] = "tag_and_audit" if last_tool_name == "tag_and_audit" else "modify"
        return state

    return tool_node
