from typing import Any
import json
from pathlib import Path
from tools.layout_utils import load_and_save_layout

_SYSTEM_PROMPT = "You are picking the best floor layout. Reply with ONLY the layout ID (e.g., 'layout-1')."

def build_choice_node(llm: Any) -> Any:
    """Auto-select if 1 result, LLM picks if multiple."""
    
    def choice(state: dict) -> dict:
        search_json = state.get("search_results_json_string", "[]")
        user_prompt = state.get("user_prompt", "")
        iteration = state.get("iteration", 0)
        
        try:
            candidates = json.loads(search_json)
        except:
            candidates = []
        
        if not candidates:
            return {"final_response": "No candidates to choose from."}
        
        # Auto-select if only 1
        if len(candidates) == 1:
            selected_id = candidates[0]["id"]
        else:
            # Ask LLM
            cands_text = "\n".join([
                f"- {c['id']}: {c['description']} (score: {c.get('score', 'N/A')})"
                for c in candidates
            ])
            prompt = f"User needs: {user_prompt}\n\nOptions:\n{cands_text}\n\nBest layout?"
            
            response = llm.invoke(_SYSTEM_PROMPT + "\n\n" + prompt)
            selected_id = response.content.strip().split()[0]
        
        # Load layout via layout_utils (single source of truth)
        repo_root = Path(__file__).resolve().parent.parent.parent
        reference_path = repo_root / "team_06_reference_layout.json"
        load_and_save_layout(selected_id, state, reference_path)
        
        # Get the layout from state (now set by load_and_save_layout)
        layout_json = state.get("layout_json_string")
        
        return {
            "layout_json_string": layout_json,
            "iteration": iteration + 1,
        }
    
    return choice