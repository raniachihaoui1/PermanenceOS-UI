from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from _runtime.llm import write_tool_result


# ---------------------------------------------------------------------------
# Tool node - executes MCP tool calls (and the local select_layout
# pseudo-tool) requested by the reason node.
# ---------------------------------------------------------------------------

def build_tool_node(mcp_client, allowed_tools, edited_layout_dir, layout_input_dir):
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
    # width=0 for fields that don't apply to the tool being called. Filter
    # each call down to the properties this specific tool's inputSchema
    # actually declares.
    tool_property_names: dict[str, set[str]] = {
        t["name"]: set((t.get("inputSchema", {}).get("properties") or {}).keys())
        for t in allowed_tools
        if t.get("name")
    }

    def tool_node(state):

        for call in state["pending_tool_calls"]:

            # Check if we're about to exceed max iterations BEFORE incrementing
            if state["iteration"] >= state["max_iterations"]:
                print(f"Max iterations ({state['max_iterations']}) reached in tool node. Skipping remaining tool calls.")
                break
            
            state["iteration"] += 1
            if state["iteration"] > state["max_iterations"]:
                print(f"Max iterations exceeded after tool execution (iteration {state['iteration']} > {state['max_iterations']})")
                # Set a final response to gracefully exit instead of raising
                state["final_response"] = "The agent reached its maximum number of iterations. Unable to complete the full task."
                state["pending_tool_calls"] = None
                return state

            tool_name = call["name"]
            if tool_name not in allowed_names:
                raise RuntimeError(f"Tool '{tool_name}' is not in the allowed tools list")

            # Track the old layout before tool execution (to detect changes)
            old_layout_string = state.get("layout_json_string", "")

            # 1) Strip nulls. 2) Filter to this tool's declared properties.
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
                
                # Generate a summary message for select_layout
                summary_msg = _generate_tool_result_summary(
                    tool_name, 
                    tool_args, 
                    tool_output, 
                    old_layout_string,
                    state.get("layout_json_string", "")
                )
                
                # For select_layout, include a compact result
                _append_tool_messages(state, tool_name, printable_args, summary_msg)
                print(f"Tool result: {summary_msg}")
                continue

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

                # Only persist when the result is actually a layout (has a
                # 'rooms' key). Refresh state so subsequent calls see the
                # updated version, AND save it to <edited_layout_dir>/
                # <layoutId>_modified.json. We DO NOT write scalar results
                # like {"area": 40} - that would clobber the saved layout.
                try:
                    updated = json.loads(tool_output.strip())
                    if isinstance(updated, dict) and "rooms" in updated:
                        state["layout_json_string"] = json.dumps(updated)

                        layout_id = updated.get("layoutId") or "edited"
                        output_path = edited_layout_dir / f"{layout_id}_modified.json"
                        write_tool_result(tool_output, output_path)
                        print(f"  Saved updated layout: {output_path}")
                except (json.JSONDecodeError, AttributeError):
                    pass

            # Generate a summary message to help the LLM understand what happened
            summary_msg = _generate_tool_result_summary(
                tool_name, 
                tool_args, 
                tool_output, 
                old_layout_string,
                state.get("layout_json_string", "")
            )
            
            # Only include the summary - don't add the full result which can confuse the LLM
            # If the task is complete, the LLM needs to see a clear completion message
            _append_tool_messages(state, tool_name, printable_args, summary_msg)
            print(f"Tool result: {summary_msg}")

        state["pending_tool_calls"] = None
        return state

    return tool_node


# ---------------------------------------------------------------------------
# select_layout pseudo-tool implementation
# ---------------------------------------------------------------------------

def handle_select_layout(layout_input_dir: Path, state: dict) -> str:
    """List JSON files, prompt the user, load the chosen one, update state.

    Safety net: if a layout is already loaded in state, return it immediately
    instead of re-prompting. Protects against small models (Llama-3.1-8B)
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

def _generate_tool_result_summary(
    tool_name: str,
    tool_args: dict,
    tool_output: str,
    old_layout_string: str,
    new_layout_string: str
) -> str:
    """Generate a human-readable summary of what the tool did.
    
    Helps the LLM understand whether the task is complete by comparing
    before/after states and providing clear feedback.
    """
    try:
        result = json.loads(tool_output.strip())
    except (json.JSONDecodeError, ValueError):
        return f"Tool '{tool_name}' executed with arguments {tool_args}."
    
    # For layout-modifying tools, detect if anything changed
    if tool_name in ("remove_furniture_piece", "add_furniture", "edit_room"):
        try:
            old_layout = json.loads(old_layout_string) if old_layout_string else {}
            new_layout = json.loads(new_layout_string) if new_layout_string else {}
            
            # Detect changes in furniture
            old_furniture = _extract_all_furniture(old_layout)
            new_furniture = _extract_all_furniture(new_layout)
            
            if old_furniture != new_furniture:
                removed = old_furniture - new_furniture
                added = new_furniture - old_furniture
                
                changes = []
                if removed:
                    changes.append(f"Removed: {', '.join(sorted(removed))}")
                if added:
                    changes.append(f"Added: {', '.join(sorted(added))}")
                
                if changes:
                    return (
                        f"✓ SUCCESS: Layout successfully modified. {' '.join(changes)}. "
                        f"TASK COMPLETE - RETURN action='final' NOW."
                    )
            else:
                # Nothing changed - be VERY explicit this is complete
                room_name = tool_args.get("room_name", "the room")
                furniture_name = tool_args.get("furniture_name", "the requested item")
                if tool_name == "remove_furniture_piece":
                    # Make it absolutely clear: task is done, stop calling tools
                    return (
                        f"✓ TASK COMPLETE: '{furniture_name}' not found in {room_name}. "
                        f"This furniture either doesn't exist or was already removed. "
                        f"STOP CALLING TOOLS. Return action='final' immediately with your response."
                    )
        except (json.JSONDecodeError, KeyError, AttributeError):
            pass
    
    # For query tools (compute_*, list_*, etc.), just confirm execution
    if tool_name.startswith("compute_") or tool_name.startswith("list_"):
        if isinstance(result, dict) and "error" not in result:
            return f"✓ {tool_name} executed successfully."
    
    return f"Tool '{tool_name}' executed with arguments {tool_args}."


def _extract_all_furniture(layout: dict) -> set[str]:
    """Extract all furniture items from a layout as a set of 'room:furniture' pairs.
    
    Furniture is stored at the top level with roomId references.
    """
    furniture = set()
    try:
        # Get mapping of room IDs to room names
        room_id_to_name = {}
        for room in layout.get("rooms", []):
            room_id = room.get("id", "")
            room_name = room.get("name", "")
            if room_id and room_name:
                room_id_to_name[room_id] = room_name
        
        # Extract furniture with room references
        for item in layout.get("furniture", []):
            item_name = item.get("name", "")
            room_id = item.get("attributes", {}).get("roomId", "")
            room_name = room_id_to_name.get(room_id, "")
            
            if room_name and item_name:
                furniture.add(f"{room_name}:{item_name}")
    except (KeyError, TypeError, AttributeError):
        pass
    return furniture


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
