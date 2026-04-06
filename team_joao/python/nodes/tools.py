from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from _runtime.llm import write_tool_result


# ---------------------------------------------------------------------------
# Tool node — executes MCP tool calls requested by the reason node.
# ---------------------------------------------------------------------------

def build_tool_node(mcp_client: Any, allowed_tools: list[dict[str, Any]], edited_layout_path: Path | None = None):
    """Return a tool node function ready to be added to a LangGraph StateGraph."""

    allowed_names = {t["name"] for t in allowed_tools if t.get("name")}

    def tool_node(state: dict[str, Any]) -> dict[str, Any]:
        for call in state["pending_tool_calls"]:
            state["iteration"] += 1
            if state["iteration"] > state["max_iterations"]:
                raise RuntimeError("Max iterations exceeded")

            tool_name = call["name"]
            if tool_name not in allowed_names:
                raise RuntimeError(f"Tool '{tool_name}' is not in the allowed tools list")

            # Strip null values that some LLMs include for unused optional fields
            tool_args = {k: v for k, v in call["arguments"].items() if v is not None}

            # Always inject layout_json from Python state rather than trusting the LLM
            # to reproduce it — LLMs can introduce subtle JSON syntax errors when
            # re-serialising complex nested objects as string arguments.
            if "layout_json" in tool_args:
                tool_args["layout_json"] = state["layout_json_string"]

            tool_output = mcp_client.call_tool(tool_name, tool_args)

            # Persist the updated layout returned by the MCP tool
            if edited_layout_path is not None:
                write_tool_result(tool_output, edited_layout_path)

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

        state["pending_tool_calls"] = None
        return state

    return tool_node
