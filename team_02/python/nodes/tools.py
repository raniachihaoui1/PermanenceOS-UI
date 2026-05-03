from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from _runtime.llm import write_tool_result


# ---------------------------------------------------------------------------
# Tool node - executes MCP tool calls (and the local select_layout
# pseudo-tool) requested by the reason node.
# ---------------------------------------------------------------------------

def build_tool_node(mcp_client, allowed_tools, edited_layout_path, layout_input_dir):
    """Return a tool node function ready to be added to a LangGraph StateGraph."""

    allowed_names = {t["name"] for t in allowed_tools if t.get("name")}

    # Tools that declare layout_json in their inputSchema. We always inject
    # the current layout for these (don't trust the LLM to include it).
    tools_needing_layout = {
        t["name"]
        for t in allowed_tools
        if t.get("name") != "select_layout"
        and "layout_json" in (t.get("inputSchema", {}).get("properties") or {})
    }

    # Per-tool property allow-list. The structured-output schema in llm.py
    # merges every tool's properties into one shared object and marks them all
    # required, so the LLM sends placeholder values like room_name='' or
    # width=0 for fields that don't apply to the tool being called. Those
    # leak into MCP and cause silent failures. Filter each call down to the
    # properties this specific tool's inputSchema declares.
    tool_property_names: dict[str, set[str]] = {
        t["name"]: set((t.get("inputSchema", {}).get("properties") or {}).keys())
        for t in allowed_tools
        if t.get("name")
    }

    def tool_node(state):

        for call in state["pending_tool_calls"]:

            state["iteration"] += 1
            if state["iteration"] > state["max_iterations"]:
                raise RuntimeError("Max iterations exceeded")

            tool_name = call["name"]
            if tool_name not in allowed_names:
                raise RuntimeError(f"Tool '{tool_name}' is not in the allowed tools list")

            # 1) Strip nulls the LLM may have included as placeholders.
            # 2) Filter to only the properties this specific tool's inputSchema
            #    declares - drops cross-tool leakage from the merged schema
            #    (e.g. room_name='' on compute_total_area).
            allowed_props = tool_property_names.get(tool_name, set())
            tool_args = {
                k: v
                for k, v in call["arguments"].items()
                if v is not None and k in allowed_props
            }

            # ---------------- Python-side pseudo-tool -----------------------
            if tool_name == "select_layout":
                tool_output = handle_select_layout(layout_input_dir, state)
                printable_args: dict[str, Any] = {}
                print(f"select_layout -> {tool_output[:200]}")

            # ---------------- Regular MCP tool ------------------------------
            else:
                if tool_name in tools_needing_layout:
                    if not state.get("layout_json_string"):
                        tool_output = json.dumps({
                            "error": (
                                "No layout is loaded. Call the 'select_layout' "
                                "tool first so the user can choose a JSON file."
                            )
                        })
                        _append_tool_messages(state, tool_name, tool_args, tool_output)
                        print(f"Tool result: {tool_output}")
                        continue
                    tool_args["layout_json"] = state["layout_json_string"]

                printable_args = {
                    k: (f"<layout {len(v)} chars>" if k == "layout_json" else v)
                    for k, v in tool_args.items()
                }
                print(f"Calling tool: {tool_name} with arguments: {printable_args}")
                tool_output = mcp_client.call_tool(tool_name, tool_args)

                write_tool_result(tool_output, edited_layout_path)

                # Refresh state['layout_json_string'] only when the result
                # looks like an updated layout (has a 'rooms' key). Don't let
                # scalar results like {"area": 40} clobber the layout.
                try:
                    updated = json.loads(tool_output.strip())
                    if isinstance(updated, dict) and "rooms" in updated:
                        state["layout_json_string"] = json.dumps(updated)
                except (json.JSONDecodeError, AttributeError):
                    pass

            _append_tool_messages(state, tool_name, printable_args, tool_output)
            print(f"Tool result: {tool_output[:300]}{'...' if len(tool_output) > 300 else ''}")

        state["pending_tool_calls"] = None
        return state

    return tool_node


# ---------------------------------------------------------------------------
# select_layout pseudo-tool implementation
# ---------------------------------------------------------------------------

def handle_select_layout(layout_input_dir: Path, state: dict) -> str:
    """List JSON files, prompt the user, load the chosen one, update state.

    Safety net: if a layout is already loaded in state, return it immediately
    instead of re-prompting. This protects against small models (Llama-3.1-8B)
    that re-call select_layout in a loop ignoring the system prompt rule.
    """
    existing = state.get("layout_json_string")
    if existing:
        try:
            layout_data = json.loads(existing)
            return json.dumps({
                "loaded": "(already loaded)",
                "note": "A layout is already loaded. Use it for the user's request; do NOT call select_layout again.",
                "layout": layout_data,
            })
        except json.JSONDecodeError:
            pass

    if not layout_input_dir.exists():
        return json.dumps({"error": f"Layout directory not found: {layout_input_dir}"})

    layout_files = sorted(layout_input_dir.glob("*.json"))
    if not layout_files:
        return json.dumps({"error": f"No JSON files found in {layout_input_dir}"})

    if len(layout_files) == 1:
        selected = layout_files[0]
        print(f"\nUsing the only available layout: {selected.name}")
    else:
        print("\nAvailable layouts:")
        for i, file in enumerate(layout_files, 1):
            print(f"  {i}. {file.name}")
        while True:
            try:
                choice = input("\nSelect a layout (enter number): ").strip()
                index = int(choice) - 1
                if 0 <= index < len(layout_files):
                    selected = layout_files[index]
                    break
                print(f"Please enter a number between 1 and {len(layout_files)}")
            except ValueError:
                print("Invalid input. Please enter a number.")

    try:
        layout_data = json.loads(selected.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return json.dumps({"error": f"Failed to read {selected.name}: {exc}"})

    state["layout_json_string"] = json.dumps(layout_data)
    print(f"Loaded: {selected.name}")

    return json.dumps({
        "loaded": selected.name,
        "layout": layout_data,
    })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _append_tool_messages(state: dict, tool_name: str, arguments: dict, tool_output: str) -> None:
    state["messages"].append({
        "role": "assistant",
        "content": json.dumps({
            "action": "tool",
            "final_response": "",
            "tool_calls": [{"name": tool_name, "arguments": arguments}],
        }),
    })
    state["messages"].append({
        "role": "user",
        "content": f"Tool result: {tool_output}",
    })
