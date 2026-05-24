from __future__ import annotations

import argparse
import json
from pathlib import Path

from _runtime.config import load_llm_only_settings
# Loaded the LLM-only settings helper so main.py can skip MCP config loading.
from _runtime.bootstrap import bootstrap
from _runtime.llm import create_chat_llm
# Loaded the direct chat model constructor for the LLM-only branch.
from graph import run_agent
from nodes.reason import run_llm_only_reasoning
# Loaded the direct reasoning helper that prints a plain LLM response without tools.
from nodes.structural_grid import build_structural_grid_with_options, dump_layout, load_layout
# Added the structural grid helper import so main.py can run a no-MCP structural grid mode.
try:
    from graph import run_local_graph
except ImportError:
    run_local_graph = None


REPO_ROOT = Path(__file__).resolve().parents[2]
# Resolved the repository root so the default layout and output files can be found reliably.
DEFAULT_LAYOUT_PATH = REPO_ROOT / "layout_input" / "layout_schema.json"
# Pointed the simple-grid mode at the shared layout schema input.
DEFAULT_OUTPUT_PATH = REPO_ROOT / "team_01_edited_layout.json"
# Set the default output file for the generated layout.


def _print_llm_banner(llm_settings: object) -> None:
    provider = getattr(llm_settings, "llm_provider", "local")
    model = getattr(llm_settings, "llm_model", "unknown")
    base_url = getattr(llm_settings, "base_url", "unknown")
    print(f"LLM provider: {provider} | model: {model} | endpoint: {base_url}")


def main():

    # Process the command line arguments (the user instruction)
    # Receive the argunment with a prompt for the agent, e.g. "delete the kitchen"
    parser = argparse.ArgumentParser(description="Run the Grasshopper MCP agent.")
    parser.add_argument("prompt", help="Your instruction for the agent (e.g. 'delete the kitchen')")
    parser.add_argument("--remote", action="store_true", help="Use the old MCP/LLM workflow instead of the local agent.")
    # Added an explicit remote switch so the default command stays fully local.
    parser.add_argument("--llm-only", action="store_true", help="Skip MCP and run a direct LLM-only response.")
    # Added a pure LLM mode that bypasses bootstrap() and never touches MCP.
    parser.add_argument("--simple-grid", action="store_true", help="Generate local structural grid options and save the recommended layout.")
    # Added a switch that skips MCP and uses the fully local structural grid path.
    parser.add_argument("--material", choices=["RCC", "STEEL", "TIMBER"], help="Material to apply to the generated grid when using --simple-grid.")
    # Added a material chooser so the generated grid can use RCC, STEEL, or TIMBER.
    parser.add_argument("--layout", default=str(DEFAULT_LAYOUT_PATH), help="Layout JSON to use for --simple-grid.")
    # Added an override for the input layout file used by simple-grid mode.
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="Where to write the generated layout for --simple-grid.")
    # Added an override for the generated output file path.
    args = parser.parse_args()

    # Parsed the CLI arguments before choosing between the local LangGraph workflow and the remote workflow.
    if not args.remote:
        # Entered the fully local branch when the user did not explicitly request the old MCP path.
        llm_settings = load_llm_only_settings()
        # Loaded the provider details so the terminal can show which local model will be used.
        _print_llm_banner(llm_settings)
        # Printed the active LM Studio settings before the graph starts.
        if run_local_graph is not None:
            report = run_local_graph(args.prompt, args.layout, args.output, material=args.material)
            # Ran the offline LangGraph workflow that creates options, evaluates them, modifies the grid, re-evaluates, and compares.
            print(report)
            # Printed the local agent report so the full reasoning stays visible in the terminal.
        else:
            # Fallback path when graph.py intentionally exposes only the remote graph API.
            layout = load_layout(args.layout)
            bundle = build_structural_grid_with_options(layout, args.prompt, material=args.material)
            dump_layout(bundle["recommended"]["layout"], args.output)
            print(json.dumps(bundle, indent=2, ensure_ascii=False))
        return
        # Stopped here so LM Studio and MCP are skipped by default.

    if args.llm_only:
        # Entered the direct LLM branch when the user explicitly requests --llm-only.
        llm_settings = load_llm_only_settings()
        # Loaded the provider settings without requiring mcp.json.
        _print_llm_banner(llm_settings)
        # Printed the provider summary before invoking the direct model.
        llm = create_chat_llm(
            api_key=llm_settings.api_key,
            base_url=llm_settings.base_url,
            llm_model=llm_settings.llm_model,
            timeout_seconds=30,
            model_kwargs={},
        )
        # Built the chat model directly from the provider configuration.
        layout_data = json.loads(DEFAULT_LAYOUT_PATH.read_text(encoding="utf-8"))
        # Loaded the shared layout schema as context for the model.
        response = run_llm_only_reasoning(llm, args.prompt, layout_data)
        # Ran the model without MCP, tool calls, or the agent graph.
        print(response)
        # Printed the plain-text LLM response directly.
        return
        # Stopped here so the MCP bootstrap path is skipped entirely.

    if args.simple_grid:
        # Entered the local mode branch when the user explicitly requests --simple-grid.
        layout = load_layout(args.layout)
        # Loaded the source layout JSON from disk.
        bundle = build_structural_grid_with_options(layout, args.prompt, material=args.material)
        # Built several structural grid options and selected the recommended one.
        dump_layout(bundle["recommended"]["layout"], args.output)
        # Wrote the recommended layout back to the requested output file.
        print(json.dumps(bundle, indent=2, ensure_ascii=False))
        # Printed the full set of local options so the user can compare them.
        return
        # Stopped here so MCP/LLM bootstrapping is skipped in local mode.

    # Kept the original MCP/LLM path unchanged for normal agent runs.
    ctx = bootstrap()
    # Bootstrapped the original MCP-based agent context for normal runs.
    response = run_agent(args.prompt, ctx)
    # Ran the original agent graph with the user's prompt.

    print("\nAgent response:\n")
    # Added a label before the final response output.
    safe_response = response.encode("ascii", errors="replace").decode("ascii")
    # Sanitized the response so terminal output stays ASCII-safe.
    print(safe_response)
    # Printed the final response text.

    mcp_client = getattr(ctx, "mcp_client", None)
    if mcp_client is not None:
        mcp_client.close()
    # Closed MCP client only when present in the active runtime context.


if __name__ == "__main__":
    main()
