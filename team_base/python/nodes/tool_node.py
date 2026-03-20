from __future__ import annotations

import json
from typing import Any, Callable

from mcp_client import McpClient


def create_tool_node(
    mcp_client: McpClient,
    dbg: Callable[[str], None],
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def tool_node(state: dict[str, Any]) -> dict[str, Any]:
        dbg("[graph][tool] Enter node")
        if not state["pending_tool_calls"]:
            raise RuntimeError("Tool node called without pending tool call")

        for pending_tool in state["pending_tool_calls"]:
            state["iteration"] += 1
            if state["iteration"] > state["max_iterations"]:
                raise RuntimeError("Max iterations exceeded")

            tool_name = pending_tool["tool_name"]
            tool_arguments = pending_tool["arguments"]

            dbg(
                f"[graph][tool] Calling tool | iteration={state['iteration']} | "
                f"name={tool_name} | args={tool_arguments}"
            )

            tool_output = mcp_client.call_tool(tool_name, tool_arguments)
            dbg(f"[graph][tool] Tool output: {tool_output}")

            state["messages"].append(
                {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "tool_call": {
                                "name": tool_name,
                                "arguments": tool_arguments,
                            }
                        }
                    ),
                }
            )
            state["messages"].append(
                {
                    "role": "user",
                    "content": f"Tool result: {tool_output}",
                }
            )

        state["pending_tool_calls"] = None
        return state

    return tool_node
