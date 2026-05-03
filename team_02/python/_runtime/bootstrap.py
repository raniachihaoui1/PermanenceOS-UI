from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from _runtime.config import load_settings
from _runtime.mcp_client import McpClient
from _runtime.llm import create_chat_llm, get_llm_response_format


@dataclass
class Context:
    """Everything the agent graph needs to run - passed from main.py into graph.py."""
    llm: Any
    mcp_client: McpClient
    tools: list[dict[str, Any]]
    layout_data: dict[str, Any]
    max_iterations: int
    edited_layout_dir: Path  # Where mutated layouts are written, e.g. team_02/resulting_layout/
    layout_input_dir: Path   # Where the select_layout pseudo-tool looks for JSON files


# Python-side pseudo-tool. Not an MCP tool - it's intercepted in nodes/tools.py
# and runs locally (terminal prompt -> file read -> state update). Listed in
# the tool catalog so the LLM knows it exists and can choose to call it.
SELECT_LAYOUT_TOOL: dict[str, Any] = {
    "name": "select_layout",
    "description": (
        "Prompt the user (in the terminal) to pick a layout JSON file from "
        "the layout_input directory and load it into the agent's context. "
        "Takes no arguments. Call this once, before any other tool, when "
        "(and only when) the user's request requires a layout. After this "
        "returns successfully, subsequent layout-dependent tool calls will "
        "operate on the chosen layout."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    },
}


def select_layout(repo_root: Path) -> Path:
    """Discover available layout files and prompt the user to select one.

    Searches for JSON files in layout_input/ directory.
    Returns the Path to the selected layout file.
    """
    layout_dir = repo_root / "layout_input"
    layout_files = sorted(layout_dir.glob("*.json"))
    if not layout_files:
        raise FileNotFoundError(f"No JSON files found in {layout_dir}")

    if len(layout_files) == 1:
        print(f"Using layout: {layout_files[0].name}")
        return layout_files[0]

    print("\nAvailable layouts:")
    for i, file in enumerate(layout_files, 1):
        print(f"  {i}. {file.name}")

    while True:
        try:
            choice = input("\nSelect a layout (enter number): ").strip()
            index = int(choice) - 1
            if 0 <= index < len(layout_files):
                selected = layout_files[index]
                print(f"Selected: {selected.name}\n")
                return selected
            print(f"Please enter a number between 1 and {len(layout_files)}")
        except ValueError:
            print("Invalid input. Please enter a number.")


def bootstrap(layout_path: Path | None = None) -> Context:
    settings = load_settings()

    team_dir = Path(__file__).resolve().parents[2]
    layout_input_dir = team_dir / "randomized_layouts"

    if layout_path is not None:
        layout_data: dict[str, Any] = json.loads(layout_path.read_text(encoding="utf-8"))
    else:
        layout_data = {}

    mcp_client = McpClient(settings.mcp_endpoint, settings.request_timeout_seconds)
    mcp_client.initialize()
    mcp_tools = mcp_client.list_tools()
    print(f"Discovered MCP tools: {[t.get('name') for t in mcp_tools]}")

    tools = mcp_tools + [SELECT_LAYOUT_TOOL]
    print(f"Plus Python-side pseudo-tool: {SELECT_LAYOUT_TOOL['name']}")

    llm = create_chat_llm(
        api_key=settings.api_key,
        base_url=settings.base_url,
        llm_model=settings.llm_model,
        timeout_seconds=settings.request_timeout_seconds,
        model_kwargs=get_llm_response_format(tools),
    )

    edited_layout_dir = team_dir / "resulting_layout"
    edited_layout_dir.mkdir(parents=True, exist_ok=True)

    return Context(
        llm=llm,
        mcp_client=mcp_client,
        tools=tools,
        layout_data=layout_data,
        max_iterations=settings.max_iterations,
        edited_layout_dir=edited_layout_dir,
        layout_input_dir=layout_input_dir,
    )
