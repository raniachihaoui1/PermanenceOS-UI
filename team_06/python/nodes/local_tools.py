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



# ---------------------------------------------------------------------------
# Local tools catalog — tools available directly (not via MCP).
# ---------------------------------------------------------------------------

def get_local_tools() -> list[dict[str, Any]]:
    """Return definitions of all local (non-MCP) tools."""
    return [
        {
            "name": "layout_filter",
            "description": "This tool selects a layout based on its layoutId. Use this after layout_matcher to get the full layout JSON for the best match, or to select a specific layout by ID.",
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
            "name": "layout_matcher",
            "description": "This tool finds layouts that match a natural language description. It returns metadata about the best-matching layouts, including their layoutIds and similarity scores. Use this to search for relevant layouts before using layout_filter to select one.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "User's natural language description of desired apartment (e.g., 'cozy 2-bedroom with open kitchen')"
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of top results to return (default: 3)",
                        "default": 3
                    },
                    "min_score": {
                        "type": "number",
                        "description": "Minimum similarity score 0-1 to include results (default: 0.5)",
                        "default": 0.5
                    }
                },
                "required": ["query"]
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
            if tool_name not in ["layout_filter", "layout_matcher"]:
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
                
            elif tool_name == "layout_matcher":
                all_descriptions = _load_all_descriptions()
                query_text = tool_args.get("query") or tool_args.get("description")
                
                raw_output = match_layouts(
                    query=query_text,
                    all_descriptions=all_descriptions,
                    top_k=tool_args.get("top_k", 3),
                    min_score=tool_args.get("min_score", 0.15)
                )
                tool_output = raw_output
                
                # Save candidate layouts with layoutId and score only
                candidates = []
                for match in raw_output.get("matches", []):
                    candidates.append({
                        "layoutId": match["layoutId"],
                        "score": match["score"]
                    })
                state["candidate_layouts"] = candidates
                
                # Update session state with search action
                state["last_action"] = f"Searched for: {query_text}"
                print(f"[local_tool] Updated state: candidate_layouts with {len(candidates)} results")
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