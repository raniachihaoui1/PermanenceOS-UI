"""Session persistence — save/load conversation state between CLI runs."""

import json
from pathlib import Path


SESSION_FILE = Path(__file__).parent.parent / ".session.json"


def save_session_state(state: dict) -> None:
    """Save agent state to disk for next run. Trim old messages to keep conversation size manageable."""
    messages = state.get("messages", [])
    
    # Keep only recent messages to avoid token limit issues on resume
    # Skip the huge initial context message (usually messages[0]), keep last N messages
    if len(messages) > 1:
        # Keep: skip first message (has full layout JSON), keep all tool calls/results after
        trimmed_messages = messages[1:] if len(messages) > 4 else messages
    else:
        trimmed_messages = messages
    
    persistent_state = {
        "messages": trimmed_messages,
        "layout_id": state.get("layout_id"),
        "layout_schema": state.get("layout_schema"),
    }
    with open(SESSION_FILE, "w") as f:
        json.dump(persistent_state, f, indent=2)
    print(f"[Session saved to {SESSION_FILE.name}]")


def load_session_state() -> dict | None:
    """Load previous session state from disk, or None if no session."""
    if SESSION_FILE.exists():
        with open(SESSION_FILE, "r") as f:
            return json.load(f)
    return None


def clear_session() -> None:
    """Clear the saved session (for starting fresh conversation)."""
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()
        print("[Session cleared]")
