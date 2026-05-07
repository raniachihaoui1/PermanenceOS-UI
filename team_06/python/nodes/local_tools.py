# ============================================================================
# local_tools.py — Local Python tools executed directly in the graph.
#
# These are tools that don't go through MCP — they're called directly
# from the local_tool node for simpler, faster execution.
# ============================================================================

from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from functools import lru_cache

from tools.embedding_matcher import match_layouts
from tools.layout_filter import select_layout
from tools.graph_searcher import GraphSearcher, build_topology_graph


# ---------------------------------------------------------------------------
# File loading — cache JSON files to avoid repeated disk reads.
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_all_layouts() -> list[dict[str, Any]]:
    """Load all layouts from sample_layouts.json."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    repo_root = Path(__file__).resolve().parent.parent.parent
    layouts_path = repo_root / "layout_inputs" / "sample_layouts.json"
    return json.loads(layouts_path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _load_all_descriptions() -> list[dict[str, Any]]:
    """Load layout descriptions from sample_descriptions.json."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    repo_root = Path(__file__).resolve().parent.parent.parent
    descriptions_path = repo_root / "layout_inputs" / "sample_descriptions.json"
    return json.loads(descriptions_path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _get_graph_searcher() -> GraphSearcher:
    """Initialize and cache GraphSearcher instance."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    graphs_path = repo_root / "layout_inputs" / "sample_graphs.json"
    return GraphSearcher(str(graphs_path))



# ---------------------------------------------------------------------------
# Local tools catalog — tools available directly (not via MCP).
# ---------------------------------------------------------------------------

def get_local_tools() -> list[dict[str, Any]]:
    """Return definitions of all local (non-MCP) tools."""
    return [
        {
            "name": "layout_filter",
            "description": "This tool selects a layout based on its layoutId. Use this after layout_graph_search to get the full layout JSON for a selected match.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "layoutId": {
                        "type": "string",
                        "description": "The layout ID (e.g., 'layout-1', 'layout-4')"
                    }
                },
                "required": ["layoutId"]
            }
        },
        {
            "name": "layout_graph_search",
            "description": "Search layouts by topology using a pattern graph. Specify room types and whether they must be connected.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "programs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of room types (e.g., ['bed', 'kitchen', 'living']). INCLUDE DUPLICATES for counts! For '2-bedroom': ['bed', 'bed', 'kitchen']. For '3 bathrooms': ['bath', 'bath', 'bath']. Count matters!"
                    },
                    "connection_type": {
                        "type": "string",
                        "enum": ["any", "connected"],
                        "description": "'any' = rooms exist (any edges), 'connected' = rooms must all be interconnected via doors"
                    }
                },
                "required": ["programs"]
            }
        }
    ]


# ---------------------------------------------------------------------------
# Local tool node — executes local Python tools.
# ---------------------------------------------------------------------------

def build_local_tool_node():
    """Return a local tool node function ready to be added to a LangGraph StateGraph."""

    def local_tool_node(state):
        """Execute pending local tool calls and append results to conversation history."""

        remaining_calls = []  # Tools that aren't local (to pass to run_tool)
        
        # Iterate over the pending local tool calls
        for call in state["pending_tool_calls"]:
            tool_name = call["name"]
            
            # Skip non-local tools
            if tool_name not in ["layout_filter", "layout_graph_search"]:
                remaining_calls.append(call)
                continue
            
            print(f"Calling local tool: {tool_name} with arguments: {call['arguments']}")

            # Cleanup any null values accidentally included by the LLM
            tool_args = {k: v for k, v in call["arguments"].items() if v is not None}

            # Execute the appropriate local tool
            if tool_name == "layout_filter":
                all_layouts = _load_all_layouts()
                tool_output = select_layout(
                    all_layouts=all_layouts,
                    layout_id=tool_args.get("layoutId")
                )
                state["layout_json_string"] = json.dumps(tool_output, indent=2)
                
                # Update session state with selected layout ID
                selected_id = tool_args.get("layoutId")
                state["layout_id"] = selected_id
                state["last_action"] = f"Selected layout {selected_id}"
                print(f"[local_tool] Updated state: layout_id={selected_id}")
                
            elif tool_name == "layout_graph_search":
                graph_searcher = _get_graph_searcher()
                programs = tool_args.get("programs", [])
                connection_type = tool_args.get("connection_type", "any")
                
                # Build topology graph from user intent
                topology_graph = build_topology_graph(programs, connection_type)
                
                # Search using graph similarity
                results = graph_searcher.search_by_graph_similarity(topology_graph, method="jaccard")
                
                # Format results
                candidates = [
                    {"layoutId": layout_id, "score": similarity}
                    for layout_id, similarity in results
                ]
                
                tool_output = {
                    "pattern": f"Rooms: {', '.join(programs)}, connection: {connection_type}",
                    "matches": candidates,
                    "total": len(candidates)
                }
                state["last_action"] = f"Searched for rooms {connection_type}: {', '.join(programs)}"
                state["candidate_layouts"] = candidates
                print(f"[local_tool] Graph search: {len(candidates)} layouts found")
            else:
                tool_output = {"error": f"Unknown tool: {tool_name}"}

            # Append to conversation history
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
                "content": f"Tool result: {json.dumps(tool_output)}",
            })
            
            print(f"[local_tool] Result: {tool_output}")

        state["pending_tool_calls"] = remaining_calls if remaining_calls else None
        return state

    return local_tool_node