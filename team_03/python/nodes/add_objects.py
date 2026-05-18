from __future__ import annotations
import json
import re
from typing import Any
from _runtime.session import save_session


# ---------------------------------------------------------------------------
# objects_list parser — converts the LLM's compact string format to the
# JSON array the GH place_objects script expects.
#
# LLM produces:  "cnc_machine:2.0x1.5x1.2:x=5.0,y=3.0"
# GH expects:    [{"name": "cnc_machine", "position": [5.0, 3.0],
#                  "size": [2.0, 1.5, 1.2]}]
#
# Multiple objects can be comma-separated or newline-separated in the string.
# Items with no x=/y= coordinates are skipped — a position is required.
# ---------------------------------------------------------------------------

_OBJECT_PATTERN = re.compile(
    r'([a-zA-Z_][a-zA-Z0-9_ ]*)'        # name (allows spaces)
    r':(\d+\.?\d*)[x*](\d+\.?\d*)[x*](\d+\.?\d*)'  # WxDxH
    r'(?::x=([\d.]+),y=([\d.]+))?'      # optional :x=X,y=Y
)


def _parse_objects_list(objects_str: str) -> list[dict]:
    # Walk every regex match in the string — handles comma-separated,
    # newline-separated, or single-item input from the LLM.
    results = []
    for m in _OBJECT_PATTERN.finditer(objects_str):
        name, w, d, h, x, y = m.groups()
        if x is None or y is None:
            # Position is required; skip items the LLM forgot to coordinate.
            continue
        results.append({
            "name":     name.strip(),
            "position": [float(x), float(y)],
            "size":     [float(w), float(d), float(h)],
        })
    return results


# ---------------------------------------------------------------------------
# Object placement node — places ONE object at a time via the MCP tool.
# Collision detection is NOT done here — it runs as a separate graph step
# after this node returns. This node only places and saves.
# ---------------------------------------------------------------------------

def build_add_objects_node(mcp_client, workspace_path):
    """Return a node closure that places one object via the place_objects MCP tool.

    Capture mcp_client and workspace_path at build time (same closure pattern
    as build_tool_node and build_visibility_node) so add_objects_node(state)
    only needs the live graph state as its argument.
    """

    def add_objects_node(state):

        # Iteration guard — prevents infinite loops in the graph.
        # Every node increments the shared counter; the graph stops if it
        # exceeds max_iterations set in .env via settings.
        state["iteration"] += 1
        if state["iteration"] > state["max_iterations"]:
            raise RuntimeError("Max iterations exceeded")

        # ---------------------------------------------------------------------------
        # Guard: nothing queued → skip.
        # The reason node sets object_to_place before routing here.
        # If it's missing or empty the graph wired incorrectly — warn and bail out
        # rather than crashing, so the graph can continue to the next step.
        # ---------------------------------------------------------------------------
        object_to_place = state.get("object_to_place")
        if not object_to_place:
            print("[add_objects] Warning: object_to_place is empty — skipping placement.")
            return state

        # ---------------------------------------------------------------------------
        # Parse objects_list from LLM string format to JSON array.
        # The LLM emits "name:WxDxH:x=X,y=Y" but the GH script expects a JSON
        # array of dicts. Convert here so GH never has to handle raw strings.
        # If the LLM already sent a list (e.g. from a retry), use it directly.
        # ---------------------------------------------------------------------------
        raw_objects = object_to_place.get("objects_list", "")
        if isinstance(raw_objects, str):
            parsed_objects = _parse_objects_list(raw_objects)
            objects_list_json = json.dumps(parsed_objects)
        else:
            # Already a list — re-serialize to ensure valid JSON string.
            objects_list_json = json.dumps(raw_objects)

        # ---------------------------------------------------------------------------
        # Call the MCP place_objects tool with the coordinates the LLM decided.
        # layout_json is always injected here — never trusted from the LLM output
        # to guarantee the tool receives the latest saved state.
        # ---------------------------------------------------------------------------
        tool_args = {
            "layout_json": state["layout_json_string"],
            "room_name": object_to_place["room_name"],
            "objects_list": objects_list_json,
            "user_profile": object_to_place.get("user_profile", "standard"),
            "clear_room": object_to_place.get("clear_room", False),
        }
        tool_output = mcp_client.call_tool("place_objects", tool_args)

        # ---------------------------------------------------------------------------
        # Parse tool output — place_objects can return two different shapes:
        #   a) Full updated layout (has "rooms") → replace session entirely.
        #   b) Result summary only (has "placed"/"failed") → store for the next node.
        # Either way, save_session keeps workspace/session_active.json in sync
        # so a crash between placements doesn't lose work.
        # ---------------------------------------------------------------------------
        try:
            parsed = json.loads(tool_output.strip())
            if isinstance(parsed, dict):
                if "rooms" in parsed:
                    # Full layout returned — update state and persist to disk
                    state["layout_json_string"] = json.dumps(parsed)
                    save_session(parsed, workspace_path)
                else:
                    # Summary only — store so collision or reason nodes can inspect it
                    state["last_placement_result"] = parsed
        except (json.JSONDecodeError, AttributeError):
            pass

        # Append tool call to conversation history.
        # Exclude layout_json from logged arguments — it's large and already in state.
        state["messages"].append({
            "role": "assistant",
            "content": json.dumps({
                "action": "tool",
                "final_response": "",
                "tool_calls": [{"name": "place_objects", "arguments": {
                    k: v for k, v in tool_args.items() if k != "layout_json"
                }}],
            }),
        })
        state["messages"].append({
            "role": "user",
            "content": f"Tool result: {tool_output[:500]}",
        })

        # Clear object_to_place so the graph knows this placement step is complete.
        # The router or next node checks this field to decide what to run next.
        state["object_to_place"] = None

        return state

    return add_objects_node
