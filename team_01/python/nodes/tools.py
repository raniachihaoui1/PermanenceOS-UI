from __future__ import annotations

import json
import math
from typing import Any


def _element_material(el: dict[str, Any], fallback: str) -> str:
    return str(el.get("attributes", {}).get("material") or fallback).upper()


def _rough_option_cost(layout: dict[str, Any], fallback_material: str) -> float:
    """Compute a fast material-cost proxy so options can be ranked in UI."""
    unit_cost = {"RCC": 350.0, "STEEL": 12000.0, "TIMBER": 800.0}
    total = 0.0
    for el in layout.get("structure", []):
        attrs = el.get("attributes", {})
        geo = el.get("geometry", [])
        mat = _element_material(el, fallback_material)
        key = next((k for k in unit_cost if k in mat), "RCC")

        if len(geo) == 2:
            span = math.dist(geo[0], geo[1])
            depth_m = float(attrs.get("depth", 300)) / 1000.0
            width_m = float(attrs.get("width", 200)) / 1000.0
            vol = span * width_m * depth_m
        else:
            h = float(attrs.get("height", 3.5))
            dims = str(attrs.get("dimensions", "200x200")).lower().split("x")
            if len(dims) == 2:
                b = float(dims[0]) / 1000.0
                d = float(dims[1]) / 1000.0
            else:
                b = d = 0.2
            vol = h * b * d

        total += vol * unit_cost[key]
    return round(total, 2)


def build_structural_grid_with_options(
    layout: dict[str, Any],
    user_prompt: str = "",
    material: str = "RCC",
) -> dict[str, Any]:
    """Return structural options payload expected by the Streamlit UI."""
    from nodes.evaluate import evaluate_structure
    from nodes.modify import apply_material_override

    base_layout = layout if isinstance(layout, dict) else {}

    try:
        from nodes.tag_and_audit import generate_structure
        options_raw = generate_structure(base_layout)
    except Exception:
        # Fallback keeps UI operational if tag_and_audit import/execution fails.
        options_raw = [base_layout]

    if not isinstance(options_raw, list) or not options_raw:
        options_raw = [base_layout]

    options: list[dict[str, Any]] = []
    for i, option_layout in enumerate(options_raw, start=1):
        working = option_layout if isinstance(option_layout, dict) else base_layout
        layout_with_material = json.loads(apply_material_override(json.dumps(working), material))

        eval_result = evaluate_structure(json.dumps(layout_with_material))
        summary = eval_result.get("summary", {}) if isinstance(eval_result, dict) else {}
        failures = int(summary.get("beam_failures", 0)) + int(summary.get("column_failures", 0))

        structure = layout_with_material.get("structure", [])
        spans = [
            float(el.get("attributes", {}).get("length", 0.0))
            for el in structure
            if len(el.get("geometry", [])) == 2
        ]
        max_span = max(spans) if spans else 0.0

        options.append(
            {
                "label": f"Option {i}",
                "spacing": round(max_span, 2),
                "failures": failures,
                "cost": _rough_option_cost(layout_with_material, material),
                "layout": layout_with_material,
                "evaluation": eval_result,
            }
        )

    return {
        "material": material,
        "prompt": user_prompt,
        "options": options,
    }


def get_action_tools() -> list[dict]:
    """Return the local tool catalog exposed to the reason node."""
    return [
        {
            "name": "tag_and_audit",
            "description": (
                "Generate a structural column/beam grid from layout JSON and "
                "return the updated layout JSON."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "layout_json": {
                        "type": "string",
                        "description": "Full layout JSON string.",
                    },
                    "typology": {
                        "type": "string",
                        "description": "Grid strategy. Defaults to column_grid.",
                        "enum": ["column_grid", "perimeter_load_bearing", "shear_wall"],
                    },
                    "grid_spacing": {
                        "type": "number",
                        "description": "Preferred grid spacing in meters.",
                    },
                },
                "required": ["layout_json"],
                "additionalProperties": False,
            },
        }
    ]
