from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nodes.evaluate import DEFAULT_SECTIONS


MATERIAL_CHOICES = ("RCC", "STEEL", "TIMBER")
DEFAULT_WALL_TOLERANCE_M = 0.45


@dataclass(frozen=True)
class GridPlan:
    material: str
    spacing: float
    x_lines: list[float]
    y_lines: list[float]
    columns: list[dict[str, Any]]
    beams: list[dict[str, Any]]


@dataclass(frozen=True)
class GridOption:
    label: str
    spacing: float
    rationale: str
    plan: GridPlan
    score: float


def normalize_material(raw_value: str) -> str:
    token = raw_value.strip().upper().replace("-", "").replace("_", "")
    if "STEEL" in token:
        return "STEEL"
    if "TIMBER" in token or "WOOD" in token:
        return "TIMBER"
    return "RCC"


def ask_material(prompt_text: str | None = None) -> str:
    if prompt_text:
        material = normalize_material(prompt_text)
        if material in MATERIAL_CHOICES and material == prompt_text.strip().upper():
            return material

    print("Material first: choose RCC, Steel, or Timber.")
    chosen = input("Material: ").strip()
    return normalize_material(chosen)


def _layout_outline(layout: dict[str, Any]) -> list[list[float]]:
    outline = layout.get("outline") or []
    if len(outline) >= 4:
        return outline

    rooms = layout.get("rooms") or []
    points: list[list[float]] = []
    for room in rooms:
        points.extend(room.get("geometry") or [])
    if points:
        return points
    return [[0.0, 0.0], [10.0, 0.0], [10.0, 8.0], [0.0, 8.0], [0.0, 0.0]]


def _axis_bounds(points: list[list[float]]) -> tuple[float, float, float, float]:
    xs = [float(pt[0]) for pt in points]
    ys = [float(pt[1]) for pt in points]
    return min(xs), max(xs), min(ys), max(ys)


def _choose_spacing(longest_side_m: float) -> float:
    if longest_side_m <= 6:
        return 3.0
    if longest_side_m <= 12:
        return 4.0
    if longest_side_m <= 18:
        return 5.0
    return min(6.0, round(longest_side_m / 4.0, 2))


def _candidate_spacings(base_spacing: float) -> list[float]:
    candidates = [base_spacing * 0.85, base_spacing, base_spacing * 1.15]
    cleaned: list[float] = []
    for value in candidates:
        rounded = round(max(2.5, min(6.0, value)), 2)
        if rounded not in cleaned:
            cleaned.append(rounded)
    return cleaned


def _grid_positions(start: float, end: float, spacing: float) -> list[float]:
    if end <= start:
        return [round(start, 3)]

    positions = [round(start, 3)]
    current = start + spacing
    while current < end - spacing * 0.25:
        positions.append(round(current, 3))
        current += spacing
    if positions[-1] != round(end, 3):
        positions.append(round(end, 3))
    return sorted(dict.fromkeys(positions))


def _extract_axis_walls(layout: dict[str, Any]) -> tuple[list[float], list[float]]:
    vertical: list[float] = []
    horizontal: list[float] = []

    def _collect(points: list[list[float]]) -> None:
        if len(points) < 2:
            return
        for p1, p2 in zip(points, points[1:]):
            x1, y1 = float(p1[0]), float(p1[1])
            x2, y2 = float(p2[0]), float(p2[1])
            if math.isclose(x1, x2, abs_tol=1e-6):
                vertical.append(round(x1, 3))
            if math.isclose(y1, y2, abs_tol=1e-6):
                horizontal.append(round(y1, 3))

    _collect(layout.get("outline") or [])
    for room in layout.get("rooms") or []:
        _collect(room.get("geometry") or [])
    for element in layout.get("structure") or []:
        _collect(element.get("geometry") or [])

    return sorted(dict.fromkeys(vertical)), sorted(dict.fromkeys(horizontal))


def _reconcile_positions(
    positions: list[float],
    wall_positions: list[float],
    tolerance_m: float,
) -> list[float]:
    if not positions:
        return []

    confirmed: list[float] = []
    for index, position in enumerate(positions):
        if index in (0, len(positions) - 1):
            confirmed.append(round(position, 3))
            continue

        if not wall_positions:
            continue

        nearest = min(wall_positions, key=lambda value: abs(value - position))
        if abs(nearest - position) <= tolerance_m:
            confirmed.append(round(nearest, 3))

    return sorted(dict.fromkeys(confirmed))


def _element_sections(material: str) -> tuple[dict[str, Any], str, str]:
    sections = DEFAULT_SECTIONS.get(material, DEFAULT_SECTIONS["RCC"])
    beam_width = str(sections["beam_width_mm"])
    beam_depth = str(sections["beam_depth_mm"])
    column_dims = str(sections["col_dims"])
    return sections, f"{beam_width}x{beam_depth}", column_dims


def _build_columns(
    x_lines: list[float],
    y_lines: list[float],
    material: str,
    beam_profile: str,
    column_dims: str,
) -> list[dict[str, Any]]:
    columns: list[dict[str, Any]] = []
    for x_index, x in enumerate(x_lines):
        for y_index, y in enumerate(y_lines):
            columns.append(
                {
                    "id": f"C_{x_index + 1}_{y_index + 1}",
                    "name": f"Column_{x_index + 1}_{y_index + 1}",
                    "geometry": [[round(x, 3), round(y, 3)]],
                    "attributes": {
                        "type": "structural_column",
                        "material": material,
                        "dimensions": column_dims,
                        "beamProfile": beam_profile,
                        "conflict": "None",
                    },
                }
            )
    return columns


def _build_beams(
    x_lines: list[float],
    y_lines: list[float],
    material: str,
    beam_profile: str,
    column_dims: str,
) -> list[dict[str, Any]]:
    beams: list[dict[str, Any]] = []

    for y_index, y in enumerate(y_lines):
        for x_index in range(len(x_lines) - 1):
            x1, x2 = x_lines[x_index], x_lines[x_index + 1]
            beams.append(
                {
                    "id": f"BH_{y_index + 1}_{x_index + 1}",
                    "name": f"Beam_H_{y_index + 1}_{x_index + 1}",
                    "geometry": [[round(x1, 3), round(y, 3)], [round(x2, 3), round(y, 3)]],
                    "attributes": {
                        "type": "structural_beam",
                        "orientation": "horizontal",
                        "material": material,
                        "width": beam_profile.split("x", 1)[0],
                        "depth": beam_profile.split("x", 1)[1],
                        "columnDimensions": column_dims,
                        "conflict": "None",
                    },
                }
            )

    for x_index, x in enumerate(x_lines):
        for y_index in range(len(y_lines) - 1):
            y1, y2 = y_lines[y_index], y_lines[y_index + 1]
            beams.append(
                {
                    "id": f"BV_{x_index + 1}_{y_index + 1}",
                    "name": f"Beam_V_{x_index + 1}_{y_index + 1}",
                    "geometry": [[round(x, 3), round(y1, 3)], [round(x, 3), round(y2, 3)]],
                    "attributes": {
                        "type": "structural_beam",
                        "orientation": "vertical",
                        "material": material,
                        "width": beam_profile.split("x", 1)[0],
                        "depth": beam_profile.split("x", 1)[1],
                        "columnDimensions": column_dims,
                        "conflict": "None",
                    },
                }
            )

    return beams


def _score_grid_plan(plan: GridPlan, outline: list[list[float]]) -> float:
    xs = [float(pt[0]) for pt in outline]
    ys = [float(pt[1]) for pt in outline]
    perimeter = (max(xs) - min(xs)) + (max(ys) - min(ys))
    line_count = len(plan.x_lines) + len(plan.y_lines)
    column_count = len(plan.columns)
    beam_count = len(plan.beams)
    balance_bonus = 1.0 if len(plan.x_lines) == len(plan.y_lines) else 0.5
    return (perimeter * 2.0) + (line_count * 1.2) + (column_count * 0.03) + (beam_count * 0.02) - balance_bonus


def generate_structural_grid_options(
    layout: dict[str, Any],
    material: str,
    tolerance_m: float = DEFAULT_WALL_TOLERANCE_M,
) -> list[GridOption]:
    outline = _layout_outline(layout)
    xmin, xmax, ymin, ymax = _axis_bounds(outline)
    width = xmax - xmin
    height = ymax - ymin
    longest_side = max(width, height)
    base_spacing = _choose_spacing(longest_side)
    vertical_walls, horizontal_walls = _extract_axis_walls(layout)

    options: list[GridOption] = []
    for index, spacing in enumerate(_candidate_spacings(base_spacing), start=1):
        x_positions = _grid_positions(xmin, xmax, spacing)
        y_positions = _grid_positions(ymin, ymax, spacing)

        if width >= height:
            x_positions = _reconcile_positions(x_positions, vertical_walls, tolerance_m)
            y_positions = _reconcile_positions(y_positions, horizontal_walls, tolerance_m)
        else:
            y_positions = _reconcile_positions(y_positions, horizontal_walls, tolerance_m)
            x_positions = _reconcile_positions(x_positions, vertical_walls, tolerance_m)

        if len(x_positions) < 2:
            x_positions = [round(xmin, 3), round(xmax, 3)]
        if len(y_positions) < 2:
            y_positions = [round(ymin, 3), round(ymax, 3)]

        _, beam_profile, column_dims = _element_sections(material)
        columns = _build_columns(x_positions, y_positions, material, beam_profile, column_dims)
        beams = _build_beams(x_positions, y_positions, material, beam_profile, column_dims)
        plan = GridPlan(
            material=material,
            spacing=round(spacing, 3),
            x_lines=x_positions,
            y_lines=y_positions,
            columns=columns,
            beams=beams,
        )

        if index == 1:
            rationale = "Conservative spacing with tighter support rhythm."
            label = "Option 1: conservative"
        elif index == 2:
            rationale = "Balanced spacing closest to the layout-derived default."
            label = "Option 2: balanced"
        else:
            rationale = "Wider spacing for a more open structural layout."
            label = "Option 3: open"

        options.append(
            GridOption(
                label=label,
                spacing=round(spacing, 3),
                rationale=rationale,
                plan=plan,
                score=round(_score_grid_plan(plan, outline), 3),
            )
        )

    return options


def generate_structural_grid(
    layout: dict[str, Any],
    material: str,
    spacing: float | None = None,
    tolerance_m: float = DEFAULT_WALL_TOLERANCE_M,
) -> GridPlan:
    outline = _layout_outline(layout)
    xmin, xmax, ymin, ymax = _axis_bounds(outline)
    width = xmax - xmin
    height = ymax - ymin

    longest_side = max(width, height)
    spacing = float(spacing or _choose_spacing(longest_side))

    x_positions = _grid_positions(xmin, xmax, spacing)
    y_positions = _grid_positions(ymin, ymax, spacing)
    vertical_walls, horizontal_walls = _extract_axis_walls(layout)

    if width >= height:
        x_positions = _reconcile_positions(x_positions, vertical_walls, tolerance_m)
        y_positions = _reconcile_positions(y_positions, horizontal_walls, tolerance_m)
    else:
        y_positions = _reconcile_positions(y_positions, horizontal_walls, tolerance_m)
        x_positions = _reconcile_positions(x_positions, vertical_walls, tolerance_m)

    if len(x_positions) < 2:
        x_positions = [round(xmin, 3), round(xmax, 3)]
    if len(y_positions) < 2:
        y_positions = [round(ymin, 3), round(ymax, 3)]

    _, beam_profile, column_dims = _element_sections(material)
    columns = _build_columns(x_positions, y_positions, material, beam_profile, column_dims)
    beams = _build_beams(x_positions, y_positions, material, beam_profile, column_dims)

    return GridPlan(
        material=material,
        spacing=round(spacing, 3),
        x_lines=x_positions,
        y_lines=y_positions,
        columns=columns,
        beams=beams,
    )


def apply_structural_grid(layout: dict[str, Any], plan: GridPlan) -> dict[str, Any]:
    updated = json.loads(json.dumps(layout))
    structure = list(updated.get("structure") or [])
    structure.extend(plan.columns)
    structure.extend(plan.beams)
    updated["structure"] = structure
    updated["gridPlan"] = {
        "material": plan.material,
        "spacing": plan.spacing,
        "x_lines": plan.x_lines,
        "y_lines": plan.y_lines,
    }
    return updated


def build_structural_grid_from_prompt(
    layout: dict[str, Any],
    prompt: str,
    material: str | None = None,
) -> dict[str, Any]:
    chosen_material = normalize_material(material) if material else ask_material()
    plan = generate_structural_grid(layout, chosen_material)
    return apply_structural_grid(layout, plan)


def build_structural_grid_with_options(
    layout: dict[str, Any],
    prompt: str,
    material: str | None = None,
) -> dict[str, Any]:
    chosen_material = normalize_material(material) if material else ask_material()
    options = generate_structural_grid_options(layout, chosen_material)
    best_option = min(options, key=lambda option: option.score)

    return {
        "prompt": prompt,
        "material": chosen_material,
        "recommended": {
            "label": best_option.label,
            "spacing": best_option.spacing,
            "rationale": best_option.rationale,
            "score": best_option.score,
            "layout": apply_structural_grid(layout, best_option.plan),
        },
        "options": [
            {
                "label": option.label,
                "spacing": option.spacing,
                "rationale": option.rationale,
                "score": option.score,
                "layout": apply_structural_grid(layout, option.plan),
            }
            for option in options
        ],
    }


def load_layout(path: str | Path) -> dict[str, Any]:
    layout_path = Path(path)
    return json.loads(layout_path.read_text(encoding="utf-8"))


def dump_layout(layout: dict[str, Any], path: str | Path) -> None:
    layout_path = Path(path)
    layout_path.write_text(json.dumps(layout, indent=2, ensure_ascii=False), encoding="utf-8")
