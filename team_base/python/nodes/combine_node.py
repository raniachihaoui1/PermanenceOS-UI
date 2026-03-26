from __future__ import annotations

from nodes.domain_registry import DOMAIN_REGISTRY
from nodes.routing import WorkflowState
from langchain_openai import ChatOpenAI
from nodes.tool_node import get_llm_response_format, create_chat_llm


def combine_results_node(state: WorkflowState) -> WorkflowState:
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

    # Run an LLM call to combine the results into a final response
    llm = create_chat_llm(
        api_key=state.get("api_key", ""),
        base_url=state.get("base_url", ""),
        llm_model=state.get("llm_model", ""),
        timeout_seconds=state.get("timeout_seconds", 30),
    )
    print(
        f"""
        api_key={state.get("api_key", "")}
        base_url={state.get("base_url", "")}
        llm_model={state.get("llm_model", "")}
        timeout_seconds={state.get("timeout_seconds", 30)}
        input={final_response}

        """
    )
    final_response = llm.invoke(final_response)


    if not isinstance(final_response, str):
        raise RuntimeError("Workflow combine step did not produce a final response")

    state["final_response"] = final_response
    return state
