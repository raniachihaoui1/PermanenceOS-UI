from __future__ import annotations

import json
from typing import Any, Callable

from nodes.domain_registry import AVAILABLE_DOMAINS


def _build_classifier_response_format() -> dict[str, Any]:
    # Schema is generated from the domain registry so new domains can be added
    # in one place.
    return {
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "domain_route",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "selected_domains": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": list(AVAILABLE_DOMAINS),
                            },
                            "minItems": 1,
                            "uniqueItems": True,
                        }
                    },
                    "required": ["selected_domains"],
                    "additionalProperties": False,
                },
            },
        }
    }


CLASSIFIER_RESPONSE_FORMAT = _build_classifier_response_format()


def _build_classifier_prompt() -> str:
    domain_bullets = "\n".join(f"- {domain}" for domain in AVAILABLE_DOMAINS)
    domain_examples = []
    for domain in AVAILABLE_DOMAINS:
        domain_examples.append(f"- {domain}-only request -> [\"{domain}\"]")

    if len(AVAILABLE_DOMAINS) > 1:
        combined_domains = "\", \"".join(AVAILABLE_DOMAINS)
        domain_examples.append(f"- asks for multiple domains -> [\"{combined_domains}\"]")

    examples_text = "\n".join(domain_examples)

    return f"""You are routing a geometry request inside a LangGraph workflow.
Choose one or more domains from this list:
{domain_bullets}

Select every domain needed to answer the request.
Examples:
{examples_text}

Return strictly valid JSON with exactly this shape:
{{
  \"selected_domains\": [\"{AVAILABLE_DOMAINS[0]}\", ...]
}}

Output rules:
- Return JSON only.
- Do not use markdown code fences.
- Do not add explanation before or after the JSON object.
"""


CLASSIFIER_PROMPT = _build_classifier_prompt()


def _strip_markdown_code_fence(content: str) -> str:
    stripped = content.strip()
    if not stripped.startswith("```"):
        return stripped

    lines = stripped.splitlines()
    if len(lines) < 3:
        return stripped
    if not lines[-1].strip().startswith("```"):
        return stripped

    return "\n".join(lines[1:-1]).strip()


def create_classifier_node(llm: Any, dbg: Callable[[str], None]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """
    Build a very small node whose only job is to decide which domain workflow
    should run next.
    """

    def classifier_node(state: dict[str, Any]) -> dict[str, Any]:
        dbg("[graph][classify] Enter node")

        result = llm.invoke(
            [
                {"role": "system", "content": CLASSIFIER_PROMPT},
                {"role": "user", "content": state["user_prompt"]},
            ]
        )
        content = result.content
        if not isinstance(content, str):
            raise RuntimeError("Classifier response content must be a string")

        parsed = json.loads(_strip_markdown_code_fence(content))
        selected_domains = parsed.get("selected_domains")
        if not isinstance(selected_domains, list) or not selected_domains:
            raise RuntimeError("Classifier must return a non-empty 'selected_domains' list")

        allowed_domains = set(AVAILABLE_DOMAINS)
        normalized_domains: list[str] = []
        for domain in selected_domains:
            if not isinstance(domain, str):
                raise RuntimeError("Each selected domain must be a string")
            if domain not in allowed_domains:
                raise RuntimeError(f"Unsupported selected domain: {domain}")
            if domain not in normalized_domains:
                normalized_domains.append(domain)

        dbg(f"[graph][classify] Decision={normalized_domains}")
        return {"selected_domains": normalized_domains}

    return classifier_node