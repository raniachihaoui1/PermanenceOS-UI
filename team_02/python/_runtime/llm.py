from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path
from typing import Any
from langchain_openai import ChatOpenAI


# ---------------------------------------------------------------------------
# LLM factory
# ---------------------------------------------------------------------------

def create_chat_llm(
    api_key: str,
    base_url: str,
    llm_model: str,
    timeout_seconds: float,
    model_kwargs: dict[str, Any] | None = None,
) -> ChatOpenAI:
    return ChatOpenAI(
        api_key=api_key,
        base_url=base_url,
        model=llm_model,
        timeout=timeout_seconds,
        temperature=0,
        # Bound the response so an unconstrained model can't run forever.
        # Our JSON decisions are short - 512 tokens is plenty for the
        # action/final_response/tool_calls envelope plus a handful of args.
        max_tokens=512,
        model_kwargs=model_kwargs or {},
    )


# ---------------------------------------------------------------------------
# Response format selection
# ---------------------------------------------------------------------------

LLM_DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["final", "tool"]},
        "final_response": {"type": "string"},
        "tool_calls": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "arguments": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
                },
                "required": ["name", "arguments"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["action", "final_response", "tool_calls"],
    "additionalProperties": False,
}


def _build_arguments_schema(tools: list[dict[str, Any]]) -> dict[str, Any]:
    merged_properties: dict[str, Any] = {}
    for tool in tools:
        input_schema = tool.get("inputSchema")
        if not isinstance(input_schema, dict):
            continue
        properties = input_schema.get("properties")
        if not isinstance(properties, dict):
            continue
        for property_name, property_schema in properties.items():
            if property_name in merged_properties:
                continue
            if not isinstance(property_schema, dict):
                continue
            nullable_schema = dict(property_schema)
            property_type = nullable_schema.get("type")
            if isinstance(property_type, str):
                nullable_schema["type"] = [property_type, "null"]
            merged_properties[property_name] = nullable_schema
    return {
        "type": "object",
        "properties": merged_properties,
        "required": list(merged_properties.keys()),
        "additionalProperties": False,
    }


def get_llm_response_format(tools: list[dict[str, Any]]) -> dict[str, Any]:
    # NOTE: LMStudio's OpenAI-compatible server only accepts
    # response_format types 'json_schema' or 'text'. Real OpenAI also
    # supports 'json_object', but LMStudio rejects it with HTTP 400.
    #
    # We use 'text' (no format constraint) here:
    #   - 'json_schema' with strict=true causes constrained-generation
    #     hangs on Llama-3.1-8B against our merged schema.
    #   - 'text' lets the model generate freely; the system prompt in
    #     nodes/reason.py shows the exact JSON shape to emit, and the
    #     parser below tolerates small structural variations.
    _ = tools
    return {
        "response_format": {"type": "text"},
    }


# ---------------------------------------------------------------------------
# LLM response parsing (internal helpers)
# ---------------------------------------------------------------------------

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


def _extract_json_object(text: str) -> str | None:
    """Find the first balanced top-level JSON object in arbitrary text."""
    in_string = False
    escape = False
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start != -1:
                return text[start:i + 1]
    return None


def _parse_llm_json(content: str) -> dict[str, Any]:
    content = _strip_markdown_code_fence(content)

    # First try: parse the whole string.
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Second try: extract first balanced { ... } from prose.
    candidate = _extract_json_object(content)
    if candidate is not None:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    # Third try: NDJSON with 'tool_call' per line.
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if lines:
        try:
            tool_calls: list[dict[str, Any]] = []
            for line in lines:
                parsed_line = json.loads(line)
                if isinstance(parsed_line, dict) and isinstance(parsed_line.get("tool_call"), dict):
                    tool_calls.append(parsed_line["tool_call"])
            if tool_calls:
                return {"tool_calls": tool_calls}
        except json.JSONDecodeError:
            pass

    raise RuntimeError(f"Could not parse JSON from LLM response: {content[:500]}")


def _normalize_llm_decision(parsed: dict[str, Any]) -> dict[str, Any]:
    action = parsed.get("action")

    if action == "final":
        return {"action": "final", "final_response": parsed.get("final_response", "")}

    if action == "tool":
        tool_calls = parsed.get("tool_calls")
        if not isinstance(tool_calls, list) or not tool_calls:
            raise RuntimeError("LLM tool decision must include a non-empty 'tool_calls' array")
        return {
            "action": "tool",
            "tool_calls": [{"name": t["name"], "arguments": t.get("arguments", {})} for t in tool_calls],
        }

    if "final_response" in parsed:
        return {"action": "final", "final_response": parsed["final_response"]}

    tool_call = parsed.get("tool_call")
    if isinstance(tool_call, dict):
        return {
            "action": "tool",
            "tool_calls": [{"name": tool_call["name"], "arguments": tool_call.get("arguments", {})}],
        }

    tool_calls = parsed.get("tool_calls")
    if isinstance(tool_calls, list) and tool_calls:
        return {
            "action": "tool",
            "tool_calls": [{"name": t["name"], "arguments": t.get("arguments", {})} for t in tool_calls],
        }

    raise RuntimeError("LLM response must include either 'final_response' or 'tool_call'")


# ---------------------------------------------------------------------------
# Public entry used by reason nodes
# ---------------------------------------------------------------------------

def call_llm(llm: Any, system_prompt: str, messages: list[dict[str, str]], tool_catalog: str) -> dict[str, Any]:
    formatted_prompt = system_prompt.format(tool_catalog=tool_catalog)
    llm_messages = [{"role": "system", "content": formatted_prompt}] + messages

    result = llm.invoke(llm_messages)
    content = result.content
    if not isinstance(content, str):
        raise RuntimeError("LLM response content must be a string")

    try:
        return _normalize_llm_decision(_parse_llm_json(content))
    except Exception:
        print("\n[llm] Raw LLM response before crash:")
        print(content)
        raise


# ---------------------------------------------------------------------------
# Tool output persistence helper used by tool nodes
# ---------------------------------------------------------------------------

def write_tool_result(tool_output: str, path: Path) -> None:
    """Write the MCP tool output to a file, pretty-printing JSON if possible."""
    stripped = tool_output.strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        text = tool_output if tool_output.endswith("\n") else tool_output + "\n"
    else:
        text = json.dumps(parsed, indent=2, ensure_ascii=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
