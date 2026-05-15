from __future__ import annotations
import json
from _runtime.llm import write_tool_result


def build_modify_node(mcp_client, allowed_tools, edited_layout_path):

    allowed_names = {t["name"] for t in allowed_tools if t.get("name")}

    def modify_node(state):
        print("\nModifying layout...")

        # Save original layout before first modification
        if not state.get("original_layout_json_string"):
            state["original_layout_json_string"] = state["layout_json_string"]

        for call in state["pending_tool_calls"]:
            state["iteration"] += 1
            if state["iteration"] > state["max_iterations"]:
                raise RuntimeError("Max iterations exceeded")

            tool_name = call["name"]
            if tool_name not in allowed_names:
                raise RuntimeError(f"Tool '{tool_name}' is not in the allowed tools list")

            print(f"Calling tool: {tool_name} with arguments: {call['arguments']}")

            tool_args = {k: v for k, v in call["arguments"].items() if v is not None}

            if "layout_json" in tool_args:
                tool_args["layout_json"] = state["layout_json_string"]

            tool_output = mcp_client.call_tool(tool_name, tool_args)

            try:
                _parsed = json.loads(tool_output.strip())
                if isinstance(_parsed, dict) and ("layoutId" in _parsed or "rooms" in _parsed):
                    write_tool_result(tool_output, edited_layout_path)
            except (json.JSONDecodeError, AttributeError):
                pass

            try:
                updated = json.loads(tool_output.strip())
                if isinstance(updated, dict):
                    state["layout_json_string"] = json.dumps(updated)
            except (json.JSONDecodeError, AttributeError):
                pass

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
        state["came_from"] = "modify"
        return state

    return modify_node
