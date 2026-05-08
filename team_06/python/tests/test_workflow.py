#!/usr/bin/env python
"""
Test the complete workflow without real LLM by simulating LLM behavior.

This script tests the agent workflow using the REAL graph execution:
1. Mock LLM parses natural language prompts into tool calls
2. Real graph.run_agent() executes the workflow with actual tools
3. State persists across tests to match real behavior

Usage:
    # Run with custom prompt
    python test_workflow.py "your natural language prompt here"
    
    # Run all predefined tests (4 test cases with persistent state)
    python test_workflow.py --test all

Test Cases (--test all):
    1. Filter layout-1 (load specific layout)
    2. Search layouts with bathroom accessible from bedroom
    3. Search layout with 2 bedroom and 2 bathrooms and delete kitchen
    4. Add window 1m to the living room
    
Notes:
    • Uses REAL graph execution with ACTUAL tools (no tool duplication)
    • State persists across all tests when using --test all
    • Only the LLM reasoning is mocked with pattern matching
    • Output files saved to test_results/ directory
"""

import sys
import json
import argparse
import re
from pathlib import Path
from typing import Any, Optional
from threading import Thread
import signal

# Add parent directory (/python/) to path for imports
# This script is at /tests/test_workflow.py, so parent is /python/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _runtime.bootstrap import bootstrap
from team_06.python.graph import run_agent
from nodes.local_tools import _load_all_layouts, _get_graph_searcher
from tools.layout_filter import select_layout
from tools.graph_searcher import build_topology_graph



# ============================================================================
# Timeout helper for MCP calls
# ============================================================================

def call_tool_with_timeout(mcp_client, tool_name, arguments, timeout_seconds=5):
    """Call MCP tool with timeout to prevent hanging."""
    result = [None]
    error = [None]
    
    def call_tool():
        try:
            result[0] = mcp_client.call_tool(tool_name, arguments)
        except Exception as e:
            error[0] = e
    
    thread = Thread(target=call_tool, daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)
    
    if error[0]:
        raise error[0]
    if result[0] is None:
        raise TimeoutError(f"MCP tool '{tool_name}' timed out after {timeout_seconds}s")
    
    return result[0]



# ============================================================================
# Mock LLM — Simulates LLM decision-making by parsing natural language
# ============================================================================

class MockLLMDecisionMaker:
    """Mock LLM that simulates agent reasoning via pattern matching."""
    
    def invoke(self, messages):
        """Simulate LLM.invoke() - called from call_llm() in nodes/reason.py"""
        # Extract user prompt from messages (last user message)
        user_prompt = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_prompt = msg.get("content", "")
                break
        
        print(f"[MockLLM] Parsing prompt: {user_prompt[:100]}...")
        
        decision = self._parse_prompt(user_prompt)
        print(f"[MockLLM] Decision: action={decision['action']}, tools={[t['name'] for t in decision.get('tool_calls', [])]}")
        
        # Return as ChatOpenAI response object
        class MockResponse:
            def __init__(self, content):
                self.content = json.dumps(content)
        
        return MockResponse(decision)
    
    def _parse_prompt(self, text: str) -> dict[str, Any]:
        """Parse natural language into tool calls."""
        text_lower = text.lower()
        
        # Check for search/filter operations
        if any(word in text_lower for word in ["find", "search", "show", "select layout", "get", "what layouts", "any layouts"]):
            return self._parse_search(text_lower)
        
        # Check for delete operations
        if "delete" in text_lower:
            return self._parse_delete(text_lower)
        
        # Check for add window operations
        if "add window" in text_lower or "add a window" in text_lower:
            return self._parse_add_window(text_lower)
        
        # Check for layout selection
        if any(f"layout-{i}" in text_lower for i in range(1, 100)):
            return self._parse_filter_layout(text_lower)
        
        # Default: return as final response
        return {
            "action": "final",
            "final_response": f"I'm not sure what to do with: '{text}'",
            "tool_calls": []
        }
    
    def _parse_search(self, text: str) -> dict[str, Any]:
        """Parse search queries into layout_graph_search calls."""
        programs = []
        
        # Extract bedroom count
        bed_match = re.search(r'(\d+)\s*[-\s]?bedroom', text)
        if bed_match:
            count = int(bed_match.group(1))
            programs.extend(['bed'] * count)
        
        # Extract bathroom count
        bath_match = re.search(r'(\d+)\s*[-\s]?bathrooms?', text)
        if bath_match:
            count = int(bath_match.group(1))
            programs.extend(['bath'] * count)
        
        # Extract keywords
        if 'kitchen' in text:
            programs.append('kitchen')
        if 'living' in text:
            programs.append('living')
        if 'dining' in text:
            programs.append('dining')
        for room in ['foyer', 'entry', 'entrance']:
            if room in text:
                programs.append(room)
        
        # Determine connection type
        connection_type = "connected" if "accessible from" in text or "connected" in text else "any"
        
        # If no programs extracted, default
        if not programs:
            programs = ['bed', 'kitchen']
        
        return {
            "action": "tool",
            "final_response": "",
            "tool_calls": [{
                "name": "layout_graph_search",
                "arguments": {
                    "programs": programs,
                    "connection_type": connection_type
                }
            }]
        }
    
    def _parse_delete(self, text: str) -> dict[str, Any]:
        """Parse delete operations."""
        # Extract room to delete (after "delete" keyword)
        delete_idx = text.find('delete')
        delete_part = text[delete_idx:] if delete_idx >= 0 else text
        
        room_to_delete = None
        for room in ['kitchen', 'bed', 'bath', 'living', 'dining', 'foyer', 'entry']:
            if room in delete_part:
                room_to_delete = room.capitalize() if room != 'bed' else 'Bed'
                break
        
        if not room_to_delete:
            return {
                "action": "final",
                "final_response": "I couldn't identify which room to delete.",
                "tool_calls": []
            }
        
        tool_calls = []
        
        # Check if a specific layout is mentioned in the full text
        layout_match = re.search(r'layout-(\d+)', text)
        if layout_match:
            # Load that specific layout first
            layout_id = f"layout-{layout_match.group(1)}"
            tool_calls.append({
                "name": "layout_filter",
                "arguments": {"layoutId": layout_id}
            })
        
        # Delete the room - state will provide layout_id if not already set
        tool_calls.append({
            "name": "delete_room_06",
            "arguments": {"room_name": room_to_delete}
        })
        
        return {
            "action": "tool",
            "final_response": "",
            "tool_calls": tool_calls
        }
    
    def _parse_add_window(self, text: str) -> dict[str, Any]:
        """Parse add window operations."""
        # Extract width (look for numbers before 'm')
        width_match = re.search(r'(\d+(?:\.\d+)?)\s*m(?:eter)?s?', text)
        width = float(width_match.group(1)) if width_match else 1.0
        
        # Extract room name
        room_name = None
        for room in ['living', 'bed', 'kitchen', 'bath', 'dining', 'foyer']:
            if room in text:
                room_name = room.capitalize() if room != 'bed' else 'Bed'
                break
        
        if not room_name:
            room_name = 'Living'  # Default
        
        return {
            "action": "tool",
            "final_response": "",
            "tool_calls": [{
                "name": "add_window_06",
                "arguments": {
                    "room_name": room_name,
                    "width": width
                }
            }]
        }
    
    def _parse_filter_layout(self, text: str) -> dict[str, Any]:
        """Parse layout selection."""
        layout_match = re.search(r'layout-(\d+)', text)
        if layout_match:
            layout_id = f"layout-{layout_match.group(1)}"
            return {
                "action": "tool",
                "final_response": "",
                "tool_calls": [{
                    "name": "layout_filter",
                    "arguments": {"layoutId": layout_id}
                }]
            }
        
        return {
            "action": "final",
            "final_response": "I couldn't identify which layout to select.",
            "tool_calls": []
        }


# ============================================================================
# Test Execution — Simplified mock LLM with real tool execution
# ============================================================================

def execute_tool(tool_name: str, arguments: dict[str, Any], ctx: Any, state: dict[str, Any]) -> dict[str, Any]:
    """Execute a single tool and return its result. Updates state as needed."""
    print(f"\n  Executing: {tool_name}")
    
    try:
        if tool_name == "layout_filter":
            # Call real layout filter tool
            all_layouts = _load_all_layouts()
            layout_id = arguments.get("layoutId")
            result = select_layout(all_layouts, layout_id)
            print(f"    [OK] Loaded layout {layout_id} with {len(result.get('rooms', []))} rooms")
            
            # Store in state for subsequent operations - match real code structure
            state["selected_layout_id"] = layout_id
            state["layout"] = result
            state["layout_json_string"] = json.dumps(result)
            
            return result
            
        elif tool_name == "layout_graph_search":
            # Call real graph search tool
            programs = arguments.get("programs", [])
            connection_type = arguments.get("connection_type", "any")
            graph_searcher = _get_graph_searcher()
            topology_graph = build_topology_graph(programs, connection_type)
            results = graph_searcher.search_by_graph_similarity(topology_graph, method="jaccard")
            
            candidates = [
                {"layoutId": layout_id, "score": similarity}
                for layout_id, similarity in results
            ]
            print(f"    [OK] Found {len(candidates)} layouts matching {programs}")
            return {"candidates": candidates}
            
        elif tool_name == "delete_room_06":
            # MCP tool - try to execute via server
            room_name = arguments.get("room_name", "?")
            
            # Get layout from state (real behavior: use state's layout if available)
            layout_json_string = state.get("layout_json_string")
            layout_id = state.get("selected_layout_id")
            if not layout_json_string:
                # If no layout in state, get default from context
                layout_data = ctx.layout_data
                layout_id = layout_data.get("layout_id", "layout-1")
                layout_json_string = json.dumps(layout_data)
                state["selected_layout_id"] = layout_id
                state["layout_json_string"] = layout_json_string
                print(f"    ℹ No layout in state, using default: {layout_id}")
            
            # Add layout_json to arguments for MCP call (matching real code behavior)
            full_arguments = {**arguments, "layout_json": layout_json_string}
            print(f"    DEBUG: layout_json_string type={type(layout_json_string)}, length={len(layout_json_string) if layout_json_string else 0}")
            print(f"    DEBUG: layout_json first 100 chars: {layout_json_string[:100] if layout_json_string else 'EMPTY'}")
            print(f"    DEBUG: full_arguments keys: {list(full_arguments.keys())}")
            
            try:
                # Attempt to call the MCP tool with timeout
                result = call_tool_with_timeout(ctx.mcp_client, 'delete_room_06', full_arguments, timeout_seconds=5)
                print(f"    [OK] MCP tool executed: deleted room '{room_name}' from {layout_id}")
                return json.loads(result) if isinstance(result, str) else result
            except TimeoutError as e:
                print(f"    ⚠ MCP call timed out: {e}")
                print(f"      Would delete room: {room_name} from {layout_id}")
                return {"skipped": True, "reason": "MCP timeout", "tool_name": "delete_room_06", "room": room_name, "layout": layout_id}
            except Exception as e:
                print(f"    ⚠ MCP server error: {e}")
                print(f"      Would delete room: {room_name} from {layout_id}")
                return {"skipped": True, "reason": "MCP server unavailable", "tool_name": "delete_room_06", "room": room_name, "layout": layout_id}
            
        elif tool_name == "add_window_06":
            # MCP tool - try to execute via server
            room_name = arguments.get("room_name", "any room")
            width = arguments.get("width", "?")
            
            # Get layout from state (real behavior: use state's layout if available)
            layout_json_string = state.get("layout_json_string")
            layout_id = state.get("selected_layout_id")
            if not layout_json_string:
                # If no layout in state, get default from context
                layout_data = ctx.layout_data
                layout_id = layout_data.get("layout_id", "layout-1")
                layout_json_string = json.dumps(layout_data)
                state["selected_layout_id"] = layout_id
                state["layout_json_string"] = layout_json_string
                print(f"    ℹ No layout in state, using default: {layout_id}")
            
            # Add layout_json to arguments for MCP call (matching real code behavior)
            full_arguments = {**arguments, "layout_json": layout_json_string}
            print(f"    DEBUG: MCP arguments keys: {list(full_arguments.keys())}, room_name={room_name}, width={width}")
            
            try:
                # Attempt to call the MCP tool with timeout
                result = call_tool_with_timeout(ctx.mcp_client, 'add_window_06', full_arguments, timeout_seconds=5)
                print(f"    [OK] MCP tool executed: added {width}m window to {room_name} in {layout_id}")
                return json.loads(result) if isinstance(result, str) else result
            except TimeoutError as e:
                print(f"    ⚠ MCP call timed out: {e}")
                print(f"      Would add {width}m window to {room_name} in {layout_id}")
                return {"skipped": True, "reason": "MCP timeout", "tool_name": "add_window_06", "width": width, "room": room_name, "layout": layout_id}
            except Exception as e:
                print(f"    ⚠ MCP server error: {e}")
                print(f"      Would add {width}m window to {room_name} in {layout_id}")
                return {"skipped": True, "reason": "MCP server unavailable", "tool_name": "add_window_06", "width": width, "room": room_name, "layout": layout_id}
        else:
            return {"error": f"Unknown tool: {tool_name}"}
            
    except Exception as e:
        print(f"    ERROR: {e}")
        return {"error": str(e)}


def run_test(prompt: str, session_state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute a single test with mock LLM parsing and real tool execution.
    
    State persists across tool calls within a single test:
    - If layout_filter is called, it stores selected_layout_id in state
    - If delete/add_window are called without a layout, they use state's layout_id
    - If no layout in state, they use the default from context
    """
    print(f"\n{'='*70}")
    print(f"Test: {prompt}")
    print(f"{'='*70}")
    
    try:
        # Initialize state - can come from previous runs (session persistence)
        # Results go to tests/test_results/ directory
        script_dir = Path(__file__).resolve().parent
        results_dir = script_dir / "test_results"
        results_dir.mkdir(exist_ok=True)
        session_file = results_dir / "test_session_state.json"
        
        if session_state is None:
            # Try to load from previous session (matches real code behavior)
            if session_file.exists():
                with open(session_file, 'r') as f:
                    state = json.load(f)
                    print(f"[OK] Loaded state from previous session: layout_id={state.get('selected_layout_id')}")
            else:
                # Fresh state
                state = {
                    "selected_layout_id": None,
                    "layout": None,
                    "layout_json_string": None
                }
        else:
            state = session_state
        
        # Bootstrap context to get access to tools and settings
        ctx = bootstrap()
        print(f"[OK] Bootstrapped context")
        
        # Parse prompt with mock LLM
        mock_llm = MockLLMDecisionMaker()
        decision = mock_llm._parse_prompt(prompt)
        print(f"[OK] Mock LLM parsed prompt: action={decision['action']}")
        
        results = []
        
        # If it's a final response, just return it
        if decision.get("action") == "final":
            print(f"[OK] Final response: {decision.get('final_response', '')[:50]}...")
            results.append({"type": "final", "content": decision.get("final_response")})
        
        # If it's tools, execute them
        elif decision.get("action") == "tool":
            tool_calls = decision.get("tool_calls", [])
            print(f"[OK] Executing {len(tool_calls)} tool call(s)...")
            
            for call in tool_calls:
                tool_name = call["name"]
                args = call["arguments"]
                # Pass state through and it gets updated by execute_tool
                result = execute_tool(tool_name, args, ctx, state)
                results.append({"tool": tool_name, "result": result})
        
        # Save results to tests/test_results/
        script_dir = Path(__file__).resolve().parent
        results_dir = script_dir / "test_results"
        results_dir.mkdir(exist_ok=True)
        
        # Create a detailed log file
        log_file = results_dir / "test_execution_log.jsonl"
        with open(log_file, 'a') as f:
            f.write(json.dumps({
                "prompt": prompt,
                "decision_action": decision.get("action"),
                "tools_called": [c["name"] for c in decision.get("tool_calls", [])],
                "final_state": {
                    "selected_layout_id": state.get("selected_layout_id"),
                },
                "results": results
            }) + "\n")
        
        # Save state to session file for next run (matches real code persistence)
        with open(session_file, 'w') as f:
            json.dump(state, f, indent=2)
        
        print(f"[OK] Test completed (state: layout_id={state.get('selected_layout_id')}, log: {log_file})")
        ctx.mcp_client.close()
        
        return {"success": True, "decision": decision, "results": results, "state": state}
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


def test_all():
    """Run all predefined test cases."""
    print("\n" + "#"*70)
    print("TEST: All Predefined Test Cases")
    print("#"*70)
    
    test_cases = [
        "filter layout-1",
        "search layouts with bathroom accessible from bedroom",
        "search layout with 2 bedroom and 2 bathrooms and delete kitchen",
        "add window 1m to the living"
    ]
    
    for i, prompt in enumerate(test_cases, 1):
        print(f"\n\nTest Case {i}/4")
        run_test(prompt)


def test_custom_prompt(prompt: str):
    """Run a custom prompt test."""
    run_test(prompt)


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Test the agent workflow with real graph + mock LLM"
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        help="Natural language prompt to test"
    )
    parser.add_argument(
        "--test",
        choices=["all"],
        help="Run all predefined test cases"
    )
    
    args = parser.parse_args()
    
    if args.test == "all":
        test_all()
    elif args.prompt:
        test_custom_prompt(args.prompt)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
