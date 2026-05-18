from __future__ import annotations
import json
from typing import Any
from _runtime.session import save_session


# ---------------------------------------------------------------------------
# Tool node — executes MCP tool calls requested by the reason node.
# ---------------------------------------------------------------------------

def build_tool_node(mcp_client, allowed_tools, workspace_path):
    """Return a tool node function ready to be added to a LangGraph StateGraph."""

    allowed_names = {t["name"] for t in allowed_tools if t.get("name")}

    def tool_node(state):

        for call in state["pending_tool_calls"]:

            # Stop the process if max number of iterations is reached
            state["iteration"] += 1
            if state["iteration"] > state["max_iterations"]:
                raise RuntimeError("Max iterations exceeded")

            # Validate the tool name against the allowed list
            tool_name = call["name"]
            if tool_name not in allowed_names:
                raise RuntimeError(f"Tool '{tool_name}' is not in the allowed tools list")

            print(f"Calling tool: {tool_name} with arguments: {call['arguments']}")

            # Strip null and empty-string values the LLM occasionally emits —
            # MCP tools reject unexpected null fields
            tool_args = {k: v for k, v in call["arguments"].items()
                         if v is not None and v != ""}

            # Check if this tool declares layout_json in its inputSchema —
            # if yes inject it automatically without relying on the LLM to include it
            tool_schema = next(
                (t for t in allowed_tools if t.get("name") == tool_name), {}
            )
            needs_layout = "layout_json" in (
                tool_schema
                .get("inputSchema", {})
                .get("properties", {})
            )
            if needs_layout:
                tool_args["layout_json"] = state["layout_json_string"]

            # Execute the tool via the MCP client
            tool_output = mcp_client.call_tool(tool_name, tool_args)

            # workspace_path is set in AgentState in graph.py — tools.py reads it from state
            try:
                updated = json.loads(tool_output.strip())
                if isinstance(updated, dict):
                    if "rooms" in updated:
                        # Full layout returned — replace the session entirely
                        state["layout_json_string"] = json.dumps(updated)
                        save_session(updated, workspace_path)
                    elif "doors" in updated:
                        # widen_doors returns only the doors array —
                        # merge into the current layout instead of replacing entirely
                        current = json.loads(state["layout_json_string"])
                        current["doors"] = updated["doors"]
                        state["layout_json_string"] = json.dumps(current)
                        save_session(current, workspace_path)
            except (json.JSONDecodeError, AttributeError, KeyError):
                pass

            # Append the tool call to conversation history, excluding layout_json
            # to keep logs readable — the full JSON is already in state
            state["messages"].append({
                "role": "assistant",
                "content": json.dumps({
                    "action": "tool",
                    "final_response": "",
                    "tool_calls": [{"name": tool_name, "arguments": {
                        k: v for k, v in tool_args.items() if k != "layout_json"
                    }}],
                }),
            })

            # Truncate the tool result log to avoid flooding the console
            print(f"Tool result: {tool_output[:500]}")

            state["messages"].append({
                "role": "user",
                "content": f"Tool result: {tool_output[:500]}",
            })

        state["pending_tool_calls"] = None
        return state

    return tool_node
