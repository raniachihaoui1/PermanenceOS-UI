# =============================================================================
# agent_graph.py — The "brain" of the AI agent
# =============================================================================

from __future__ import annotations

import json
from typing import Any, Callable, TypedDict

from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from execution_graph_ascii import print_execution_graph_ascii
from mcp_client import McpClient
from nodes.classifier_node import CLASSIFIER_RESPONSE_FORMAT, create_classifier_node
from nodes.domain_registry import AVAILABLE_DOMAINS, DOMAIN_REGISTRY
from nodes.reason_node import create_reason_node
from nodes.routing import (
    WorkflowState,
    create_route_after_reason,
    create_route_after_classifier,
    create_route_after_run_domain,
)
from nodes.tool_node import create_tool_node, get_llm_response_format


class AgentState(TypedDict):
    '''
    Represents the state of the AI agent during its reasoning and tool-calling loop.
    This includes the conversation history, any pending tool calls, the final response 
    if available, the current iteration count, the maximum allowed iterations, and a 
    formatted catalog of available tools.
    '''

    messages: list[dict[str, str]]
    pending_tool_calls: list[dict[str, Any]] | None
    final_response: str | None
    iteration: int
    max_iterations: int
    tool_catalog: str


def _format_tools(tools: list[dict[str, Any]]) -> str:
    '''
    Formats the list of available tools into a human-readable string.
    Each tool is represented with its name, description, and input schema.
    This reflects the definitions in the Swiftlet definition for each tool.
    '''

    lines: list[str] = []
    for tool in tools:
        name = str(tool.get("name", "<unknown>"))
        description = str(tool.get("description", ""))
        input_schema = json.dumps(tool.get("inputSchema", {}))
        lines.append(f"- {name}: {description} | inputSchema={input_schema}")
    return "\n".join(lines)


def build_initial_state(user_prompt: str, tools: list[dict[str, Any]], max_iterations: int) -> AgentState:
    '''
    Builds the initial state for the AI agent, including the user prompt,
    the formatted tool catalog, and the maximum number of iterations allowed.
    '''

    return {
        "messages": [{"role": "user", "content": user_prompt}],
        "pending_tool_calls": None,
        "final_response": None,
        "iteration": 0,
        "max_iterations": max_iterations,
        "tool_catalog": _format_tools(tools),
    }


def _build_workflow_initial_state(user_prompt: str) -> WorkflowState:
    '''
    The parent graph starts with just the user prompt. The classifier fills in
    selected_domains, and the runner nodes fill in domain-specific answers.
    '''

    return {
        "user_prompt": user_prompt,
        "selected_domains": [],
        "domain_responses": {},
        "final_response": None,
    }


def _create_chat_llm(
    api_key: str,
    base_url: str,
    llm_model: str,
    timeout_seconds: float,
    model_kwargs: dict[str, Any] | None = None,
) -> ChatOpenAI:
    '''
    Both the classifier and the domain sub-agents use the same model settings.
    This helper keeps that setup in one place so the code stays easy to read.
    '''

    return ChatOpenAI(
        api_key=api_key,
        base_url=base_url,
        model=llm_model,
        timeout=timeout_seconds,
        temperature=0,
        model_kwargs=model_kwargs or {},
    )


def _group_tools_by_domain(tools: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    '''
    Split the MCP tools into the small domain-specific collections used by the
    child agents. Right now the tool names are the simplest source of truth:
    tools containing "volume" go to the volume agent, and tools containing
    "area" go to the area agent.
    '''

    grouped_tools: dict[str, list[dict[str, Any]]] = {
        domain: [] for domain in AVAILABLE_DOMAINS
    }

    for tool in tools:
        tool_name = str(tool.get("name", "")).lower()
        for domain_name in AVAILABLE_DOMAINS:
            domain_config = DOMAIN_REGISTRY[domain_name]
            match_tokens = domain_config.get("tool_name_contains", [])
            if not isinstance(match_tokens, list):
                continue
            if any(str(token).lower() in tool_name for token in match_tokens):
                grouped_tools[domain_name].append(tool)
                break

    return grouped_tools


def _build_domain_prompt(domain_name: str, user_prompt: str) -> str:
    '''
    When a sub-agent runs, we remind it to solve only its own slice of the job.
    That keeps the volume agent from trying to answer area questions, and vice
    versa, even when the original user prompt asks for both.
    '''

    return (
        f"You are the {domain_name} specialist inside a larger workflow. "
        f"Only solve the parts of the request related to {domain_name}.\n\n"
        f"Original user request:\n{user_prompt}"
    )


def _run_domain_agent(
    domain_name: str,
    user_prompt: str,
    tools: list[dict[str, Any]],
    mcp_client: McpClient,
    api_key: str,
    base_url: str,
    llm_model: str,
    debug_graph: bool,
    timeout_seconds: float,
    max_iterations: int,
) -> str:
    '''
    This is the reusable inner agent. We use the exact same logic for both
    volume and area; the only thing that changes is the tool list and the
    small domain-specific instruction added to the user prompt.
    '''

    def dbg(message: str) -> None:
        if debug_graph:
            print(message)

    if not tools:
        raise RuntimeError(f"No {domain_name} tools were found")

    dbg(f"[graph][{domain_name}] Starting domain agent")

    llm = _create_chat_llm(
        api_key=api_key,
        base_url=base_url,
        llm_model=llm_model,
        timeout_seconds=timeout_seconds,
        model_kwargs=get_llm_response_format(tools),
    ) # This is the LLM used by the domain sub-agent

    reason_node = create_reason_node(llm=llm, dbg=dbg) # This node handles the reasoning step in the domain sub-agent
    tool_node = create_tool_node(mcp_client=mcp_client, allowed_tools=tools, dbg=dbg) # This node handles calling the appropriate tool in the domain sub-agent
    route_after_reason = create_route_after_reason(dbg=dbg) # This function decides the next step after the reasoning node

    graph = StateGraph(AgentState) # This is the state graph for the domain sub-agent
    graph.add_node("reason", reason_node) # Add the reasoning node to the domain sub-agent graph
    graph.add_node("tool", tool_node) # Add the tool node to the domain sub-agent graph
    graph.add_edge(START, "reason") # Connect the start of the graph to the reasoning node
    graph.add_conditional_edges(
        "reason",
        route_after_reason,
        {
            "run_tool": "tool",
            "finish": END,
        },
    ) # Add conditional edges from the reasoning node to either the tool node or the end node based on the route
    graph.add_edge("tool", "reason") # Connect the tool node back to the reasoning node for iterative processing

    app = graph.compile() # Compile the domain sub-agent graph into an executable app
    final_state = app.invoke(
        build_initial_state(
            _build_domain_prompt(domain_name, user_prompt),
            tools,
            max_iterations,
        )
    ) # Invoke the domain sub-agent graph with the initial state

    final_response = final_state.get("final_response")
    if not isinstance(final_response, str):
        raise RuntimeError(f"{domain_name.title()} agent finished without a final response")

    if debug_graph:
        print(f"\n{domain_name.title()} sub-agent graph (ASCII):")
        app.get_graph().print_ascii() # Print the ASCII representation of the domain sub-agent graph
        print_execution_graph_ascii(final_state["messages"], final_response) # Print the execution trace of the domain sub-agent graph

    dbg(f"[graph][{domain_name}] Completed successfully")
    return final_response


def _create_domain_runner_node(
    domain_name: str,
    tools: list[dict[str, Any]],
    mcp_client: McpClient,
    api_key: str,
    base_url: str,
    llm_model: str,
    debug_graph: bool,
    timeout_seconds: float,
    max_iterations: int,
) -> Callable[[WorkflowState], WorkflowState]:
    '''
    Create one parent-graph node that runs a domain sub-agent and stores the
    answer in the outer workflow state.
    '''

    def run_domain(state: WorkflowState) -> WorkflowState:
        if domain_name not in state["selected_domains"]:
            # Fan-out may trigger non-selected domain nodes in a larger registry.
            # Returning no updates keeps this branch a no-op.
            return {}

        response = _run_domain_agent(
            domain_name=domain_name,
            user_prompt=state["user_prompt"],
            tools=tools,
            mcp_client=mcp_client,
            api_key=api_key,
            base_url=base_url,
            llm_model=llm_model,
            debug_graph=debug_graph,
            timeout_seconds=timeout_seconds,
            max_iterations=max_iterations,
        )

        # Important for parallel fan-out: each branch returns only its own
        # domain result so the reducer can merge branch outputs safely.
        return {"domain_responses": {domain_name: response}}

    return run_domain


def _combine_results_node(state: WorkflowState) -> WorkflowState:
    '''
    Turn the branch outputs back into one final answer for the user.
    '''

    selected_domains = state["selected_domains"]
    domain_responses = state.get("domain_responses", {})

    if not selected_domains:
        raise RuntimeError("Workflow combine step received no selected domains")

    missing_domains = [domain for domain in selected_domains if domain not in domain_responses]
    if missing_domains:
        raise RuntimeError(f"Workflow combine step is missing responses for: {missing_domains}")

    if len(selected_domains) == 1:
        final_response = domain_responses[selected_domains[0]]
    else:
        sections: list[str] = []
        for domain in selected_domains:
            domain_config = DOMAIN_REGISTRY.get(domain, {})
            label = str(domain_config.get("label", domain.title()))
            sections.append(f"{label} result:\n{domain_responses[domain]}")
        final_response = "\n\n".join(sections)

    if not isinstance(final_response, str):
        raise RuntimeError("Workflow combine step did not produce a final response")

    state["final_response"] = final_response
    return state


def _wait_for_parallel_join_node(state: WorkflowState) -> WorkflowState:
    '''
    This node is a safe sink for each parallel branch in multi-domain mode.

    Why it exists:
    - In multi-domain routes, each branch should finish quietly until all
      selected domains are complete.
    - Using this sink avoids accidentally triggering combine early.
    '''

    # Return no state updates. This node is only a parking place for branches
    # while per-domain conditional routing decides when combine can run.
    return {}


def _build_domain_name_map() -> dict[str, str]:
    """
    Build a reusable map from domain key to graph node name.
    """

    return {domain: f"run_{domain}" for domain in AVAILABLE_DOMAINS}


def run_agent(
    user_prompt: str,
    tools: list[dict[str, Any]],
    mcp_client: McpClient,
    api_key: str,
    base_url: str,
    llm_model: str,
    debug_graph: bool,
    timeout_seconds: float,
    max_iterations: int,
    llm_provider: str,
) -> str:
    '''
    Run a two-level LangGraph workflow.

    Level 1 is a small router graph that decides whether the question is about
    volume, area, or both.

    Level 2 is a reusable domain sub-agent. We run the same inner graph for the
    volume and area branches, but each branch receives only its own tool list.
    That means each tool node has a deliberately small and explicit tool surface.
    '''

    def dbg(message: str) -> None:
        '''
        Prints a debug message if debug_graph is True.
        '''

        if debug_graph:
            print(message)

    dbg("[graph] Initializing agent graph")
    dbg(f"[graph] Model: {llm_model}")
    dbg(f"[graph] Max iterations: {max_iterations}")

    grouped_tools = _group_tools_by_domain(tools)

    classifier_llm = _create_chat_llm(
        api_key=api_key,
        base_url=base_url,
        llm_model=llm_model,
        timeout_seconds=timeout_seconds,
        model_kwargs=CLASSIFIER_RESPONSE_FORMAT,
    )

    classifier_node = create_classifier_node(llm=classifier_llm, dbg=dbg)
    domain_node_names = _build_domain_name_map()
    run_domain_nodes: dict[str, Callable[[WorkflowState], WorkflowState]] = {}
    for domain in AVAILABLE_DOMAINS:
        run_domain_nodes[domain] = _create_domain_runner_node(
            domain_name=domain,
            tools=grouped_tools[domain],
            mcp_client=mcp_client,
            api_key=api_key,
            base_url=base_url,
            llm_model=llm_model,
            debug_graph=debug_graph,
            timeout_seconds=timeout_seconds,
            max_iterations=max_iterations,
        )

    route_after_classifier = create_route_after_classifier(dbg=dbg)
    route_after_run_domain = {
        domain: create_route_after_run_domain(domain_name=domain, dbg=dbg)
        for domain in AVAILABLE_DOMAINS
    }

    # This outer graph does only orchestration. The actual reasoning and tool
    # calls happen inside the reusable domain sub-agents created above.
    graph = StateGraph(WorkflowState)
    graph.add_node("classify", classifier_node)
    graph.add_node("wait_for_parallel_join", _wait_for_parallel_join_node)
    for domain in AVAILABLE_DOMAINS:
        graph.add_node(domain_node_names[domain], run_domain_nodes[domain])
    graph.add_node("combine", _combine_results_node)
    graph.add_edge(START, "classify")

    classify_targets: dict[str, str] = {}
    for domain in AVAILABLE_DOMAINS:
        node_name = domain_node_names[domain]
        classify_targets[node_name] = node_name

    graph.add_conditional_edges(
        "classify",
        route_after_classifier,
        classify_targets,
    )

    # For single-domain requests, these conditional edges send control directly
    # to combine. For multi-domain requests, they route to a sink and wait for the
    # explicit parallel join edge below.
    for domain in AVAILABLE_DOMAINS:
        graph.add_conditional_edges(
            domain_node_names[domain],
            route_after_run_domain[domain],
            {
                "combine": "combine",
                "wait_for_parallel_join": "wait_for_parallel_join",
            },
        )

    # Join point for multi-domain dispatch: combine runs only after all known
    # domain nodes have reported completion (selected domains compute results,
    # non-selected domains no-op).
    graph.add_edge([domain_node_names[domain] for domain in AVAILABLE_DOMAINS], "combine")

    graph.add_edge("combine", END)

    app = graph.compile()
    dbg("[graph] Graph compiled")

    final_state = app.invoke(_build_workflow_initial_state(user_prompt))
    dbg(f"[graph] Final state: {final_state}")
    final_response = final_state.get("final_response")
    if not isinstance(final_response, str):
        raise RuntimeError("Agent finished without a final response")

    print("\nWorkflow graph (ASCII):")
    app.get_graph().print_ascii()

    dbg("[graph] Completed successfully")

    return final_response
