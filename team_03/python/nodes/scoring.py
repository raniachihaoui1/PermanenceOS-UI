"""
nodes/scoring.py — Weighted multi-tool layout quality score and grade.

Aggregates results from collision, visibility, path, reachability, and
orientation into a single 0-100 score plus a letter grade and recommendation.

No Rhino. Pure Python. No external dependencies.
"""

from __future__ import annotations
import json
from typing import Any


# ---------------------------------------------------------------------------
# Default weights — must sum to 1.0.
# Collision is heaviest: safety violations are non-negotiable and must be
# resolved before any other quality metric matters.
# Path is second: blocked routes make a layout functionally unusable regardless
# of how well everything else scores.
# ---------------------------------------------------------------------------

DEFAULT_WEIGHTS: dict[str, float] = {
    "collision":    0.30,
    "visibility":   0.20,
    "path":         0.25,
    "reachability": 0.15,
    "orientation":  0.10,
}

# ---------------------------------------------------------------------------
# Grade thresholds — maps lower bound to letter grade.
# Follows a conventional academic scale; F below 40 flags genuinely broken
# layouts that should not advance to the approval checkpoint.
# ---------------------------------------------------------------------------

GRADE_THRESHOLDS: dict[int, str] = {
    90: "A",
    75: "B",
    60: "C",
    40: "D",
    0:  "F",
}


# ---------------------------------------------------------------------------
# Grade helper
# ---------------------------------------------------------------------------

def _grade(score: float) -> str:
    # Walk thresholds from highest to lowest; first match wins.
    for threshold in sorted(GRADE_THRESHOLDS, reverse=True):
        if score >= threshold:
            return GRADE_THRESHOLDS[threshold]
    return "F"


# ---------------------------------------------------------------------------
# Per-tool score functions — all return float 0–100.
# A None result means that tool did not run for this layout; returning 50
# keeps the score neutral rather than rewarding or penalising a missing check.
# Orientation is the exception: a missing check means no constraints were
# defined, so no penalty applies and it returns 100.
# ---------------------------------------------------------------------------

def _collision_score(collision_results: dict | None) -> float:
    # Unknown result → neutral 50 so it doesn't skew the total.
    if collision_results is None:
        return 50.0
    if collision_results.get("pass"):
        # Full clearance on all checks — perfect score.
        return 100.0
    summary = collision_results.get("summary", {})
    # Proportional scoring based on blocked and warning areas.
    # This allows the score to improve when furniture is repositioned,
    # even if structural violations (e.g. bathroom turning radius) persist.
    # Compute total layout area from grid dimensions for normalization.
    # Python collision node uses "grid_meta"; MCP result uses "grid".
    grid = collision_results.get("grid_meta") or collision_results.get("grid", {})
    cols = grid.get("cols", 1)
    rows = grid.get("rows", 1)
    resolution = grid.get("resolution_m", 0.2)
    total_area = cols * rows * resolution * resolution

    blocked_area = summary.get("blocked_area_m2", 0.0)
    warning_area = summary.get("warning_area_m2", 0.0)

    if total_area <= 0:
        return 0.0

    # blocked_pct: fraction of layout that is impassable
    # warning_pct: fraction of layout below spec but still passable
    blocked_pct = blocked_area / total_area
    warning_pct = warning_area / total_area

    # Score: 100 if no issues, drops proportionally.
    # Blocked areas penalized 3x more heavily than warnings.
    score = 100.0 * (1.0 - blocked_pct * 3.0 - warning_pct * 1.0)
    return max(0.0, min(100.0, score))


def _visibility_score(visibility_results: list | None) -> float:
    # Unknown → neutral 50.
    if visibility_results is None:
        return 50.0
    total = len(visibility_results)
    if total == 0:
        # No pairs to check (no objects placed yet) — no penalty.
        return 100.0
    # Count pairs where seated sightline is unblocked.
    visible = sum(1 for p in visibility_results if p.get("visible_seated"))
    return (visible / total) * 100.0


def _path_score(path_results: dict | None) -> float:
    # Unknown → neutral 50.
    if path_results is None:
        return 50.0
    pairs = path_results.get("pairs", [])
    total = len(pairs)
    if total == 0:
        return 100.0
    # Reachability ratio: proportion of pairs that have a valid path.
    unreachable = sum(1 for p in pairs if p.get("status") == "unreachable")
    reachable_ratio = (total - unreachable) / total
    # Worst-case distance penalty: longer detours reduce the distance sub-score.
    # Beyond 200 m the distance sub-score hits 0.
    worst = path_results.get("worst_case", {})
    worst_distance = worst.get("distance", 0.0) or 0.0
    distance_score = max(0.0, 100.0 - worst_distance * 0.5)
    # Combine: connectivity matters more (70%) than distance efficiency (30%).
    return reachable_ratio * 0.7 * 100.0 + distance_score * 0.3


def _reachability_score(reachability_results: dict | None) -> float:
    # Unknown → neutral 50.
    if reachability_results is None:
        return 50.0
    summary = reachability_results.get("summary", {})
    total = summary.get("total", 0)
    if total == 0:
        # Nothing to check — treat as fully reachable.
        return 100.0
    reachable = summary.get("reachable", 0)
    return (reachable / total) * 100.0


def _orientation_score(orientation_results: dict | None) -> float:
    # None means orientation was not checked — no penalty applies.
    if orientation_results is None:
        return 100.0
    summary = orientation_results.get("summary", {})
    total = summary.get("total", 0)
    if total == 0:
        # No orientation constraints defined for this layout — full score.
        return 100.0
    facing_ok = summary.get("facing_ok", 0)
    return (facing_ok / total) * 100.0


# ---------------------------------------------------------------------------
# Recommendation
# ---------------------------------------------------------------------------

def _recommendation(collision_s: float, total_score: float) -> str:
    if collision_s < 30.0:
        return "Significant collision issues — review blocked areas"
    if total_score < 60.0:
        return "Layout needs significant improvement"
    if total_score < 75.0:
        return "Layout acceptable but has room for improvement"
    return "Layout is well optimized"


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------

def compute_scores(
    visibility_results,
    path_results,
    reachability_results,
    orientation_results,
    collision_results,
    space_config: dict | None = None,
) -> dict[str, Any]:
    """
    Aggregate all tool results into a weighted layout quality score.

    Args:
        visibility_results:   list from check_visibility(), or None
        path_results:         dict from check_paths(),        or None
        reachability_results: dict from check_reachability(), or None
        orientation_results:  dict from check_orientation(),  or None
        collision_results:    dict from check_collision(),    or None
        space_config:         optional space_type_agent output; may contain
                              "tool_weights" to override DEFAULT_WEIGHTS

    Returns:
        dict with total_score, grade, breakdown, recommendation
    """
    # Resolve weights — space_config may override individual tool weights
    # when the layout type has different quality priorities (e.g. industrial
    # layouts care far more about forklift clearance than visibility).
    weights = dict(DEFAULT_WEIGHTS)
    if space_config and "tool_weights" in space_config:
        weights.update(space_config["tool_weights"])

    # Normalize weights to sum to 1.0 — space_config may inject
    # partial overrides that don't sum correctly.
    weight_sum = sum(weights.values())
    if weight_sum > 0 and abs(weight_sum - 1.0) > 0.01:
        print(f"[scoring] Warning: tool_weights sum to {weight_sum:.3f}, normalizing to 1.0")
        weights = {k: v / weight_sum for k, v in weights.items()}

    # Compute raw 0-100 score for each tool.
    scores = {
        "collision":    _collision_score(collision_results),
        "visibility":   _visibility_score(visibility_results),
        "path":         _path_score(path_results),
        "reachability": _reachability_score(reachability_results),
        "orientation":  _orientation_score(orientation_results),
    }

    # Weighted sum — each tool contributes (score × weight) to the total.
    total = sum(scores[tool] * weights[tool] for tool in scores)

    # Build per-tool breakdown for the report and for LLM consumption.
    breakdown: dict[str, dict] = {
        tool: {
            "score":    round(scores[tool], 1),
            "weight":   weights[tool],
            "weighted": round(scores[tool] * weights[tool], 2),
        }
        for tool in scores
    }

    return {
        "total_score":    round(total, 1),
        "grade":          _grade(total),
        "breakdown":      breakdown,
        "recommendation": _recommendation(scores["collision"], total),
    }


# ---------------------------------------------------------------------------
# LangGraph node — same pattern as visibility.py.
# No MCP call: scoring is pure Python and produces no GH visualization.
# ---------------------------------------------------------------------------

def build_scoring_node():
    """Return a scoring node ready to be added to a LangGraph StateGraph."""

    def scoring_node(state):
        # Returns an update dict instead of mutating state.

        print("Running scoring analysis...")

        # Pull each tool's results from state — any may be None if that node
        # hasn't run yet or was skipped for the current layout mode.
        result = compute_scores(
            visibility_results   = state.get("visibility_results"),
            path_results         = state.get("path_results"),
            reachability_results = state.get("reachability_results"),
            orientation_results  = state.get("orientation_results"),
            collision_results    = state.get("collision_results"),
            space_config         = state.get("space_config"),
        )

        print(f"Score: {result['total_score']} — Grade: {result['grade']}")

        return {
            "scoring_results": result,
            "messages": [
                {
                    "role": "assistant",
                    "content": json.dumps({
                        "action": "tool",
                        "final_response": "",
                        "tool_calls": [{"name": "scoring", "arguments": {
                            "total_score": result["total_score"],
                            "grade":       result["grade"],
                        }}],
                    }),
                },
                {
                    "role": "user",
                    "content": (
                        f"Scoring complete. Score: {result['total_score']}, "
                        f"Grade: {result['grade']}. {result['recommendation']}"
                    ),
                },
            ],
        }

    return scoring_node
