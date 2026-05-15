from __future__ import annotations
import json
import time
from typing import Any


SYSTEM_PROMPT = """You are a structural design comparison analyst for an architect.

You will be given the original layout and the modified layout. Compare them and summarize:
1. What structural elements were added, removed, or changed?
2. Did the modification achieve the intended goal?
3. Any new issues introduced, or issues resolved?

Be concise (3-5 sentences). Your summary will be passed back to the reasoning agent
to decide whether to continue refining or accept the result.

Return strictly valid JSON:
{{
  "action": "final",
  "final_response": "<your comparison here>",
  "tool_calls": []
}}
"""


def build_comparison_node(llm):

    def comparison_node(state):
        print("\nComparing layouts...")

        original = state.get("original_layout_json_string") or state["layout_json_string"]
        context_message = (
            f"Original layout:\n{original}\n\n"
            f"Modified layout:\n{state['layout_json_string']}\n\n"
            "Please compare the two layouts."
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
                    print(f"Comparison LLM failed (attempt {attempt+1}/3), retrying in {wait}s... {e}")
                    time.sleep(wait)

        if result is None:
            raise RuntimeError(f"Comparison LLM failed after 3 attempts: {last_error}")

        print(f"Comparison result: {result}")
        state["comparison_result"] = result
        state["cycle"] = state.get("cycle", 0) + 1
        state["messages"].append({
            "role": "user",
            "content": f"Comparison summary: {result}",
        })
        return state

    return comparison_node
