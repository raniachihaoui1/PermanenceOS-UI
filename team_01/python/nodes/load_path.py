"""
load_path.py — Load-Path Visualizer node.

Sits after evaluate, before cost_flexibility.  Takes the structural evaluation
result and layout geometry to produce a ranked stress-hierarchy:
  - Utilisation ratio per element  (actual / allowable, max of all checks)
  - Load-path trace  (anchor columns → primary girders → secondary beams)
  - Stress-colour attributes for the viewers
  - A "Structural Story" narrative ready for the LLM and Streamlit UI
"""
from __future__ import annotations
import json
import math

# ── Utilisation thresholds ────────────────────────────────────────────────────
_CRIT = 0.90   # ≥ critical  → red
_HIGH = 0.70   # ≥ high      → orange
_MOD  = 0.45   # ≥ moderate  → yellow
               # < moderate  → green

_COLORS: dict[str, str] = {
    "Critical": "#ff3333",
    "High":     "#ff8800",
    "Moderate": "#ffcc00",
    "Safe":     "#33cc66",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _util_label(u: float) -> str:
    if u >= _CRIT: return "Critical"
    if u >= _HIGH: return "High"
    if u >= _MOD:  return "Moderate"
    return "Safe"


def _beam_util(b: dict) -> float:
    """Max normalised utilisation ratio across all four beam checks."""
    ratios: list[float] = []
    try:
        if b.get("allow_bend_MPa"):
            ratios.append(abs(float(b["sigma_bend_MPa"])) / float(b["allow_bend_MPa"]))
        if b.get("allow_shear_MPa"):
            ratios.append(abs(float(b["tau_MPa"])) / float(b["allow_shear_MPa"]))
        if b.get("limit_LL_mm"):
            ratios.append(abs(float(b["delta_LL_mm"])) / float(b["limit_LL_mm"]))
        if b.get("limit_TL_mm"):
            ratios.append(abs(float(b["delta_total_mm"])) / float(b["limit_TL_mm"]))
    except (KeyError, TypeError, ZeroDivisionError, ValueError):
        pass
    return max(ratios, default=0.0)


def _col_util(c: dict) -> float:
    """Max normalised utilisation ratio across stress and buckling checks."""
    ratios: list[float] = []
    try:
        if c.get("allow_comp_MPa"):
            ratios.append(abs(float(c["sigma_comp_MPa"])) / float(c["allow_comp_MPa"]))
        sf = c.get("SF_buckling")
        if sf and float(sf) > 0:
            ratios.append(3.0 / float(sf))
    except (KeyError, TypeError, ZeroDivisionError, ValueError):
        pass
    return max(ratios, default=0.0)


def _beam_role(b: dict, all_beams: list[dict]) -> str:
    """Primary Girder if span ≥ median, else Secondary Beam."""
    spans = [float(bm.get("span_m") or 0) for bm in all_beams if bm.get("span_m")]
    if not spans:
        return "Beam"
    median = sorted(spans)[len(spans) // 2]
    return "Primary Girder" if float(b.get("span_m") or 0) >= median else "Secondary Beam"


def _trib_area(beam_id: str, span_m: float, layout: dict) -> float:
    """Estimate tributary area by finding the nearest parallel beam in the layout."""
    structure = layout.get("structure", [])
    beam_geo = next(
        (el["geometry"] for el in structure
         if el["id"] == beam_id and len(el.get("geometry", [])) == 2),
        None,
    )
    if not beam_geo:
        return round(span_m * 2.5, 1)

    p1, p2 = beam_geo[0], beam_geo[1]
    is_h = abs(float(p1[1]) - float(p2[1])) < 0.1
    my_coord = float(p1[1]) if is_h else float(p1[0])

    parallel_coords = [
        float(el["geometry"][0][1]) if is_h else float(el["geometry"][0][0])
        for el in structure
        if len(el.get("geometry", [])) == 2
        and el["id"] != beam_id
        and (abs(float(el["geometry"][0][1]) - float(el["geometry"][1][1])) < 0.1) == is_h
    ]
    distances = sorted(abs(c - my_coord) for c in parallel_coords if abs(c - my_coord) > 0.05)
    trib_w = min(distances[0], 6.0) if distances else 2.5
    return round(span_m * trib_w, 1)


def _find_anchor_columns(beam_entries: list[dict], layout: dict) -> list[str]:
    """Columns that are endpoints of the top-span beams — they carry the most load."""
    structure = layout.get("structure", [])
    beam_geoms = {
        el["id"]: el["geometry"]
        for el in structure
        if len(el.get("geometry", [])) == 2
    }
    col_geoms = {
        el["id"]: el["geometry"][0]
        for el in structure
        if len(el.get("geometry", [])) == 1
    }
    top_beams = sorted(beam_entries,
                       key=lambda b: float(b.get("span_m") or 0), reverse=True)[:3]
    anchors: set[str] = set()
    for bm in top_beams:
        geo = beam_geoms.get(bm["id"], [])
        if len(geo) < 2:
            continue
        for cid, cpt in col_geoms.items():
            try:
                if math.dist(geo[0], cpt) < 0.15 or math.dist(geo[1], cpt) < 0.15:
                    anchors.add(cid)
            except Exception:
                pass
    return sorted(anchors)


# ── Node builder ──────────────────────────────────────────────────────────────

def build_load_path_node():
    """Return a LangGraph-compatible node function."""

    def load_path_node(state: dict) -> dict:
        print(f"\n{'='*50}")
        print(f"  NODE: LOAD PATH VISUALIZER")
        print(f"{'='*50}")

        eval_json = state.get("evaluation_result")
        if not eval_json:
            print("  [load_path] No evaluation result — skipping.")
            return state

        try:
            ev = json.loads(eval_json)
        except (json.JSONDecodeError, TypeError):
            print("  [load_path] Cannot parse evaluation result.")
            return state

        try:
            layout = json.loads(state.get("layout_json_string") or "{}")
        except Exception:
            layout = {}

        beams_ev = ev.get("beams",   [])
        cols_ev  = ev.get("columns", [])
        elements: list[dict]        = []
        element_colors: dict[str, str] = {}

        # ── Beams ─────────────────────────────────────────────────────────────
        for b in beams_ev:
            util  = _beam_util(b)
            lbl   = _util_label(util)
            color = _COLORS[lbl]
            role  = _beam_role(b, beams_ev)
            span  = float(b.get("span_m") or 0)
            trib  = _trib_area(b["id"], span, layout)

            fails: list[str] = []
            if not b.get("bend_PASS",    True):
                fails.append(
                    f"bending {b.get('sigma_bend_MPa','?')} > {b.get('allow_bend_MPa','?')} MPa")
            if not b.get("shear_PASS",   True):
                fails.append(f"shear {b.get('tau_MPa','?')} MPa")
            if not b.get("defl_LL_PASS", True):
                fails.append(
                    f"LL deflection {b.get('delta_LL_mm','?')} > {b.get('limit_LL_mm','?')} mm")
            if not b.get("defl_TL_PASS", True):
                fails.append(
                    f"TL deflection {b.get('delta_total_mm','?')} > {b.get('limit_TL_mm','?')} mm")
            details = "; ".join(fails) if fails else "All checks pass"

            entry = {
                "id":                  b["id"],
                "role":                role,
                "element_type":        "beam",
                "utilization":         round(util, 3),
                "load_responsibility": lbl,
                "status":              "FAIL" if fails else "PASS",
                "color":               color,
                "tributary_area_m2":   trib,
                "span_m":              span,
                "section":             b.get("section_mm", ""),
                "details":             details,
            }
            elements.append(entry)
            element_colors[b["id"]] = color

        # ── Columns ───────────────────────────────────────────────────────────
        for c in cols_ev:
            util  = _col_util(c)
            lbl   = _util_label(util)
            color = _COLORS[lbl]

            fails = []
            if not c.get("stress_PASS",   True):
                fails.append(
                    f"stress {c.get('sigma_comp_MPa','?')} > {c.get('allow_comp_MPa','?')} MPa")
            if not c.get("buckling_PASS", True):
                fails.append(f"buckling SF={c.get('SF_buckling','?')} < 3.0")
            details = "; ".join(fails) if fails else "All checks pass"

            entry = {
                "id":                  c["id"],
                "role":                "Column",
                "element_type":        "column",
                "utilization":         round(util, 3),
                "load_responsibility": lbl,
                "status":              "FAIL" if fails else "PASS",
                "color":               color,
                "P_kN":                c.get("P_total_kN"),
                "height_m":            c.get("height_m"),
                "section":             c.get("section_mm", ""),
                "details":             details,
            }
            elements.append(entry)
            element_colors[c["id"]] = color

        # Sort by utilisation descending — heaviest hitters first
        elements.sort(key=lambda e: e["utilization"], reverse=True)

        # Identify anchor columns
        beam_entries = [e for e in elements if e["element_type"] == "beam"]
        anchor_ids   = _find_anchor_columns(beam_entries, layout)
        for e in elements:
            if e["id"] in anchor_ids:
                e["role"] = "Anchor Column"

        # Critical path = highest-utilised elements
        critical_path = [
            e["id"] for e in elements
            if e["load_responsibility"] in ("Critical", "High")
        ][:8]

        # ── Narrative ─────────────────────────────────────────────────────────
        n_crit = sum(1 for e in elements if e["load_responsibility"] == "Critical")
        n_high = sum(1 for e in elements if e["load_responsibility"] == "High")
        n_mod  = sum(1 for e in elements if e["load_responsibility"] == "Moderate")
        top    = elements[0] if elements else None

        parts: list[str] = []
        if top:
            parts.append(
                f"{top['id']} ({top['role']}) carries the highest load at "
                f"{top['utilization']*100:.0f}% of allowable capacity ({top['details']})."
            )
        if anchor_ids:
            col_entries = [e for e in elements if e["element_type"] == "column"]
            info = []
            for cid in anchor_ids:
                ce = next((e for e in col_entries if e["id"] == cid), None)
                if ce:
                    info.append(f"{cid} ({ce.get('P_kN','?')} kN)")
            parts.append(
                f"Load anchor point{'s' if len(anchor_ids) > 1 else ''}: "
                f"{', '.join(info or anchor_ids)} — "
                f"{'these columns funnel' if len(anchor_ids) > 1 else 'this column funnels'} "
                f"load from the longest-span beams."
            )
        counts: list[str] = []
        if n_crit: counts.append(f"{n_crit} critical (>90%)")
        if n_high: counts.append(f"{n_high} high (70–90%)")
        if n_mod:  counts.append(f"{n_mod} moderate (45–70%)")
        parts.append(
            f"Stress hierarchy: {', '.join(counts)}." if counts
            else "All elements are comfortably within safe limits."
        )

        narrative = " ".join(parts)

        result: dict = {
            "elements":       elements,
            "critical_path":  critical_path,
            "anchor_columns": anchor_ids,
            "element_colors": element_colors,
            "narrative":      narrative,
        }

        state["load_path_result"] = result
        print(f"  [{len(elements)} elements | {n_crit} critical | "
              f"{n_high} high | {len(anchor_ids)} anchor col(s)]")
        return state

    return load_path_node
