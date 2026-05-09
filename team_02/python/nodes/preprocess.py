"""
nodes/preprocess.py — PREPROCESSING node from the Comfort Copilot state graph.

This is the grey PREPROCESSING box in the state graph.
Runs BEFORE any LLM call. Pure Python — deterministic, no AI involved.

Responsibilities:
  1. Read the raw user prompt
  2. Detect the request intent (what depth of analysis is needed)
  3. Detect which persona the user mentioned, if any
  4. Flag if a persona is still missing (so the reason node knows to ask)

Intent categories (matches state graph paths):
  "inspire"          → atmosphere / image generation path (Phase 3)
  "comfort_full"     → ANALYZE → DETECT → SUGGEST (full chain)
  "comfort_detect"   → ANALYZE → DETECT only
  "comfort_analyze"  → ANALYZE only (compute comfort scores)
  "chitchat"         → no tools, conversational response
"""

from __future__ import annotations
from typing import Any
from personas import detect_persona_in_text


# ---------------------------------------------------------------------------
# Keyword maps — checked in priority order (most specific first)
# ---------------------------------------------------------------------------

_INSPIRE_KEYWORDS: tuple[str, ...] = (
    "inspire", "inspiration", "atmosphere", "mood", "aesthetic",
    "vibe", "feel like", "generate image", "create image", "imagine",
)

_COMFORT_FULL_KEYWORDS: tuple[str, ...] = (
    "improve", "suggest", "suggestion", "recommendation",
    "what should i", "what can i", "what to change", "what would you",
    "fix", "make better", "enhance", "upgrade",
    "how to fix", "how to improve", "how can i",
)

_COMFORT_DETECT_KEYWORDS: tuple[str, ...] = (
    "detect", "conflict", "conflicts", "problem", "problems",
    "issue", "issues", "what is wrong", "what's wrong",
    "failing", "fails", "what fails", "poor", "bad comfort",
    "below threshold",
)

_COMFORT_ANALYZE_KEYWORDS: tuple[str, ...] = (
    "comfort", "analyze", "analyse", "analysis", "score", "scores",
    "thermal", "visual", "acoustic", "spatial", "olfactory", "tactile",
    "how comfortable", "assess", "assessment", "evaluate", "check",
    "wellbeing", "sensorial", "sensory", "multi-sensory",
)


# ---------------------------------------------------------------------------
# Intent detection
# ---------------------------------------------------------------------------

def detect_intent(prompt: str, has_image: bool = False) -> str:
    """
    Classify the user prompt into one of five intent strings.

    Priority order (highest to lowest):
      inspire > comfort_full > comfort_detect > comfort_analyze > chitchat

    Args:
        prompt    : raw user input text
        has_image : True if the user attached an image (locks to inspire)

    Returns:
        One of: "inspire", "comfort_full", "comfort_detect",
                "comfort_analyze", "chitchat"
    """
    if has_image:
        return "inspire"

    lower = prompt.lower()

    if any(kw in lower for kw in _INSPIRE_KEYWORDS):
        return "inspire"

    if any(kw in lower for kw in _COMFORT_FULL_KEYWORDS):
        return "comfort_full"

    if any(kw in lower for kw in _COMFORT_DETECT_KEYWORDS):
        return "comfort_detect"

    if any(kw in lower for kw in _COMFORT_ANALYZE_KEYWORDS):
        return "comfort_analyze"

    return "chitchat"


def needs_layout(prompt: str, intent: str) -> bool:
    """
    Return True if this request will need a layout file.
    All comfort intents require a layout.
    """
    if intent.startswith("comfort"):
        return True
    # Also catch layout-adjacent words in chitchat / unknown intents
    lower = prompt.lower()
    layout_words = (
        "room", "kitchen", "bedroom", "bathroom", "living", "hallway",
        "apartment", "flat", "layout", "floor plan", "building", "space",
    )
    return any(w in lower for w in layout_words)


# ---------------------------------------------------------------------------
# Preprocess node — wired into the StateGraph in graph.py
# ---------------------------------------------------------------------------

def build_preprocess_node() -> Any:
    """
    Return the preprocessing node function ready to be added to a LangGraph
    StateGraph via graph.add_node("preprocess", preprocess_node).

    What it writes to state:
      intent            (str)        — detected intent string
      persona_detected  (str | None) — persona name found in prompt, or None
      needs_persona_ask (bool)       — True when intent is comfort but no
                                       persona was found; reason node should
                                       ask the user before calling any tools
    """

    def preprocess_node(state: dict) -> dict:

        # ── Extract the raw user prompt ──────────────────────────────────
        messages = state.get("messages", [])
        raw_prompt = ""
        if messages:
            content = messages[0].get("content", "")
            # Strip any layout section injected by _build_initial_state
            raw_prompt = content.split("Current layout")[0]
            raw_prompt = raw_prompt.replace("User request:", "").strip()

        print(f"\n[preprocess] Prompt  : {raw_prompt[:140]}")

        # ── 1. Detect intent ─────────────────────────────────────────────
        intent = detect_intent(raw_prompt)
        print(f"[preprocess] Intent  : {intent}")

        # ── 2. Detect persona ────────────────────────────────────────────
        persona = detect_persona_in_text(raw_prompt)
        print(f"[preprocess] Persona : {persona or 'not found'}")

        # ── 3. Flag missing persona for comfort requests ─────────────────
        needs_persona_ask = intent.startswith("comfort") and persona is None

        # ── Write results to state ───────────────────────────────────────
        state["intent"]             = intent
        state["persona_detected"]   = persona
        state["needs_persona_ask"]  = needs_persona_ask

        return state

    return preprocess_node
