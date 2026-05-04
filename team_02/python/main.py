import argparse
from _runtime.bootstrap import bootstrap
from graph import run_agent


def main():

    # Process the command line arguments (the user instruction)
    parser = argparse.ArgumentParser(description="Run the Grasshopper MCP agent.")
    parser.add_argument("prompt", help="Your instruction for the agent (e.g. 'delete the kitchen')")
    args = parser.parse_args()

    # No layout is pre-selected. The agent will call the `select_layout`
    # pseudo-tool (handled in nodes/tools.py) when the user's request
    # actually needs a layout — at which point the user is prompted in
    # the terminal to choose a JSON file from layout_input/.
    ctx = bootstrap()
    response = run_agent(args.prompt, ctx)

    # Print the final response
    print("\nAgent response:\n")
    safe_response = response.encode("ascii", errors="replace").decode("ascii")
    print(safe_response)

    # Clean up by properly closing the MCP client connection
    ctx.mcp_client.close()


if __name__ == "__main__":
    main()
