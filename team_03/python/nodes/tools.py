from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from _runtime.llm import write_tool_result


# Tools que necesitan layout_json inyectado automaticamente
TOOLS_NEEDING_LAYOUT = {
    "check_door_widths",
    "shortest_path",
    "get_visibility",
    "collision_detector_sphere",
    "widen_doors",
}

# Parametros validos por tool (whitelist estricta)
# El LLM puede mandar cualquier cosa, pero solo dejamos pasar lo correcto
TOOL_SCHEMAS = {
    "check_door_widths": {"min_door_width"},
    "widen_doors": {"door_ids", "target_width"},
    "shortest_path": {"start_room", "destination_room"},
    "get_visibility": {"room_name", "radius"},
    "collision_detector_sphere": {
        "sphere_radius_list",
        "point_in_path",
        "destination_room_collision",
        "start_room_collision",
    },
}


def build_tool_node(
    mcp_client,
    allowed_tools,
    edited_layout_path=r"D:\05- IAAC\03- Third Semester\05- AIA Studio\AIA-Studio_HaniKarime\AIA26_Studio\team_03\edited_layout.json",
):
    """Return a tool node function ready to be added to a LangGraph StateGraph."""

    allowed_names = {t["name"] for t in allowed_tools if t.get("name")}

    def tool_node(state):
        for call in state["pending_tool_calls"]:
            state["iteration"] += 1
            if state["iteration"] > state["max_iterations"]:
                raise RuntimeError("Max iterations exceeded")

            tool_name = call["name"]
            if tool_name not in allowed_names:
                raise RuntimeError(f"Tool '{tool_name}' is not in the allowed tools list")

            # 1) Filtrar argumentos: quitar nulls
            raw_args = {k: v for k, v in call["arguments"].items() if v is not None and v != ""}

            # 2) Whitelist por tool: solo dejar los parametros validos
            allowed_params = TOOL_SCHEMAS.get(tool_name, set())
            tool_args = {k: v for k, v in raw_args.items() if k in allowed_params}

            # 3) Inyectar layout_json solo si el tool lo necesita
            if tool_name in TOOLS_NEEDING_LAYOUT:
                tool_args["layout_json"] = state["layout_json_string"]

            print(f"Calling tool: {tool_name} with arguments (cleaned): {list(tool_args.keys())}")

            # 4) Llamar al tool
            tool_output = mcp_client.call_tool(tool_name, tool_args)

            # 5) Guardar resultado
            write_tool_result(tool_output, edited_layout_path)

            # 6) Si vino layout actualizado, refrescar state
            try:
                updated = json.loads(tool_output.strip())
                if isinstance(updated, dict):
                    if "rooms" in updated:
                        state["layout_json_string"] = json.dumps(updated)
                    elif "doors" in updated:
                        # widen_doors devuelve solo doors -> mergear en el layout actual
                        current = json.loads(state["layout_json_string"])
                        current["doors"] = updated["doors"]
                        state["layout_json_string"] = json.dumps(current)
            except (json.JSONDecodeError, AttributeError, KeyError):
                pass

            # 7) Anadir a historial
            state["messages"].append({
                "role": "assistant",
                "content": json.dumps({
                    "action": "tool",
                    "final_response": "",
                    "tool_calls": [{"name": tool_name, "arguments": {k: v for k, v in tool_args.items() if k != "layout_json"}}],
                }),
            })

            state["messages"].append({
                "role": "user",
                "content": f"Tool result: {tool_output}",
            })

            print(f"Tool result: {tool_output[:500]}")  # Recortar log para no saturar terminal

        state["pending_tool_calls"] = None
        return state

    return tool_node