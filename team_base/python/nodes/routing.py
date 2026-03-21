from typing import Annotated, Any, Callable, TypedDict

from langgraph.types import Send

from nodes.domain_registry import AVAILABLE_DOMAINS


def _merge_domain_responses(
    existing: dict[str, str] | None,
    incoming: dict[str, str] | None,
) -> dict[str, str]:
    """
    Merge partial domain response dictionaries produced by parallel branches.
    """

    merged: dict[str, str] = {}
    if isinstance(existing, dict):
        merged.update(existing)
    if isinstance(incoming, dict):
        merged.update(incoming)
    return merged


class WorkflowState(TypedDict):
    '''
    The outer workflow state decides which domain-specific sub-agent should run.

    Think of this as the "project manager" state. It does not store the inner
    tool-calling conversation history. Instead, it stores the user's prompt,
    the chosen route, and the finished result from each domain sub-agent.
    '''

    user_prompt: str
    selected_domains: list[str]
    domain_responses: Annotated[dict[str, str], _merge_domain_responses]
    final_response: str | None


def create_route_after_reason(dbg: Callable[[str], None]) -> Callable[[dict[str, Any]], str]:
    '''
    Decide whether to finish the workflow or run the tool node next.
    '''

    def route_after_reason(state: dict[str, Any]) -> str:
        if state["final_response"] is not None:
            dbg("[graph][route] reason -> finish")
            return "finish"
        dbg("[graph][route] reason -> run_tool")
        return "run_tool"

    return route_after_reason


def create_route_after_classifier(dbg: Callable[[str], None]) -> Callable[[WorkflowState], str | list[Send]]:
    '''
    Decide which top-level branch should run next based on selected_domains.

    - one selected domain -> run that domain node directly
    - multiple selected domains -> return Send packets for parallel execution
    '''

    def route_after_classifier(state: WorkflowState) -> str:
        selected_domains = state["selected_domains"]
        if not selected_domains:
            raise RuntimeError("Workflow classifier returned no selected domains")

        unique_domains = list(dict.fromkeys(selected_domains))
        if len(unique_domains) == 1:
            next_node = f"run_{unique_domains[0]}"
            dbg(f"[graph][route] classify -> {next_node}")
            return next_node

        dbg("[graph][route] classify -> direct multi-send")
        return [
            Send(
                f"run_{domain}",
                {
                    "user_prompt": state["user_prompt"],
                    "selected_domains": unique_domains,
                    "domain_responses": state.get("domain_responses", {}),
                    "final_response": state.get("final_response"),
                },
            )
            for domain in AVAILABLE_DOMAINS
        ]

    return route_after_classifier


def create_route_after_run_domain(domain_name: str, dbg: Callable[[str], None]) -> Callable[[WorkflowState], str]:
    '''
    Route after one domain branch:
    - If this is the only selected domain, go straight to combine
        - If multiple domains are selected, wait for the explicit graph join edge.
    '''

    def route_after_run_domain(state: WorkflowState) -> str:
        selected_domains = state["selected_domains"]
        selected_set = set(selected_domains)

        if domain_name not in selected_set:
            dbg(f"[graph][route] run_{domain_name} -> wait_for_parallel_join (domain not selected)")
            return "wait_for_parallel_join"

        if len(selected_set) == 1:
            dbg(f"[graph][route] run_{domain_name} -> combine")
            return "combine"

        dbg(f"[graph][route] run_{domain_name} -> wait_for_parallel_join")
        return "wait_for_parallel_join"

    return route_after_run_domain


