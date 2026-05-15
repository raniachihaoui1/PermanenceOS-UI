from __future__ import annotations
import json
import time
from typing import Any


SYSTEM_PROMPT = """You are a structural design evaluator for an architect.

Review the current layout JSON and the conversation so far. Assess:
1. Structural integrity — are columns, beams, and load-bearing walls consistent?
2. Conflicts — any MEP, spatial, or constraint violations?
3. Completeness — does the layout satisfy what was asked?

Give a concise evaluation (3-5 sentences). If the design is sound, say so clearly.
If there are issues, list them briefly so the reasoning agent can address them.

Return strictly valid JSON:
{{
  "action": "final",
  "final_response": "<your evaluation here>",
  "tool_calls": []
}}
"""


def build_evaluate_node(llm):

    def evaluate_node(state):
        print("\nEvaluating layout...")

        context_message = (
            f"Current layout:\n{state['layout_json_string']}\n\n"
            "Please evaluate the current state of the layout."
        )
        # Use only the last 4 messages to stay within token limits
        recent = state["messages"][-4:] if len(state["messages"]) > 4 else state["messages"]
        messages = recent + [{"role": "user", "content": context_message}]

        result = None
        last_error = None
        for attempt in range(3):
            try:
                llm_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages
                raw = llm.invoke(llm_messages)
                data = json.loads(raw.content)
                result = data.get("final_response", raw.content)
                break
            except Exception as e:
                last_error = e
                if attempt < 2:
                    wait = 5 * (attempt + 1)
                    print(f"Evaluate LLM failed (attempt {attempt+1}/3), retrying in {wait}s... {e}")
                    time.sleep(wait)

        if result is None:
            raise RuntimeError(f"Evaluate LLM failed after 3 attempts: {last_error}")

        print(f"Evaluation result: {result}")
        state["evaluation_result"] = result
        state["messages"].append({
            "role": "user",
            "content": f"Evaluation feedback: {result}",
        })
        return state

    return evaluate_node
