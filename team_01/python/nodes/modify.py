from __future__ import annotations
from nodes.tools import build_tool_node


def build_modify_node(mcp_client, allowed_tools, edited_layout_path):
    # Keep the existing graph.py call shape unchanged; delegate execution to the local Action Node.
    _ = mcp_client
    return build_tool_node(edited_layout_path=edited_layout_path, allowed_tools=allowed_tools)
