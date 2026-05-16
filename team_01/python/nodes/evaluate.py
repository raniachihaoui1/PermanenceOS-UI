from __future__ import annotations
import json
import math
import re

# ── Material library (working stress, IS 456 / IS 800 / IS 883) ───────────────
MATERIALS: dict[str, dict] = {
    "RCC": {
        "E_MPa":        25_000,   # M25 concrete
        "density_kNm3": 25.0,
        "allow_bend_MPa":  8.5,   # IS 456 Table 21, σ_cbc M25
        "allow_comp_MPa":  6.0,   # IS 456 Table 21, σ_cc  M25
        "allow_shear_MPa": 2.8,   # IS 456 Table 23, max τ_v
    },
    "STEEL": {
        "E_MPa":        200_000,
        "density_kNm3": 78.5,
        "allow_bend_MPa":  165.0,  # IS 800, Fe250
        "allow_comp_MPa":  150.0,
        "allow_shear_MPa": 100.0,
    },
    "TIMBER": {
        "E_MPa":        12_500,
        "density_kNm3": 8.0,
        "allow_bend_MPa":  12.0,  # IS 883, Group B
        "allow_comp_MPa":   8.0,
        "allow_shear_MPa":  1.5,
    },
}

# ── Load assumptions ──────────────────────────────────────────────────────────
SDL_KNM2  = 3.5   # superimposed dead load: 125 mm slab + finishes + partitions
LL_KNM2   = 2.0   # live load, residential (IS 875 Part 2)
BEAM_WIDTH_MM = 300.0  # assumed beam width when not in attributes

# ── Deflection limits ─────────────────────────────────────────────────────────
DEFL_LIMIT_LL  = 360   # L/360  live load
DEFL_LIMIT_TL  = 250   # L/250  total load
BUCKLING_SF    = 3.0   # minimum Euler buckling safety factor

# ── Default section sizes per material ────────────────────────────────────────
DEFAULT_SECTIONS: dict[str, dict] = {
    "RCC":    {"beam_depth_mm": 600, "beam_width_mm": 300, "col_dims": "300x600"},
    "STEEL":  {"beam_depth_mm": 400, "beam_width_mm": 200, "col_dims": "200x200"},
    "TIMBER": {"beam_depth_mm": 400, "beam_width_mm": 150, "col_dims": "150x150"},
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _material(name: str) -> dict:
    key = name.upper().replace("-", "").replace("_", "").replace(" ", "")
    for k, v in MATERIALS.items():
        if k in key:
            return v
    return MATERIALS["RCC"]


def _parse_dim_mm(s: str) -> tuple[float, float]:
    """'300x600' → (0.300, 0.600) metres."""
    parts = str(s).lower().split("x")
    if len(parts) == 2:
        return float(parts[0]) / 1000.0, float(parts[1]) / 1000.0
    v = float(parts[0]) / 1000.0
    return v, v


def _rect_props(b: float, d: float) -> tuple[float, float, float]:
    """Area (m²), I (m⁴), r (m) for b×d rectangle, d is depth (strong axis)."""
    A = b * d
    I = b * d ** 3 / 12.0
    r = math.sqrt(I / A)
    return A, I, r


# ── Tributary geometry ────────────────────────────────────────────────────────

def _beam_trib_widths(beams: list[dict]) -> dict[str, float]:
    """Half-spacing to nearest parallel beam in the perpendicular direction."""
    h_beams, v_beams = [], []
    for bm in beams:
        g = bm["geometry"]
        if len(g) < 2:
            continue
        if abs(g[1][0] - g[0][0]) >= abs(g[1][1] - g[0][1]):
            h_beams.append(bm)
        else:
            v_beams.append(bm)

    trib: dict[str, float] = {}

    def _spacing(beams_1d: list[dict], mid_fn) -> None:
        coords = sorted({round(mid_fn(bm), 4) for bm in beams_1d})
        for bm in beams_1d:
            c = mid_fn(bm)
            idx = min(range(len(coords)), key=lambda i: abs(coords[i] - c))
            gaps = []
            if idx > 0:
                gaps.append((coords[idx] - coords[idx - 1]) / 2)
            if idx < len(coords) - 1:
                gaps.append((coords[idx + 1] - coords[idx]) / 2)
            w = sum(gaps) / len(gaps) if gaps else 2.5
            trib[bm["id"]] = max(1.0, min(4.0, w))

    _spacing(h_beams, lambda bm: (bm["geometry"][0][1] + bm["geometry"][1][1]) / 2)
    _spacing(v_beams, lambda bm: (bm["geometry"][0][0] + bm["geometry"][1][0]) / 2)
    return trib


def _column_trib_areas(columns: list[dict]) -> dict[str, float]:
    """Voronoi tributary area per column from the column grid."""
    pts = [(c["id"], float(c["geometry"][0][0]), float(c["geometry"][0][1])) for c in columns]
    xs = sorted({x for _, x, _ in pts})
    ys = sorted({y for _, _, y in pts})

    trib: dict[str, float] = {}
    for cid, x, y in pts:
        ix = xs.index(x)
        iy = ys.index(y)
        dx_l = (x - xs[ix - 1]) / 2 if ix > 0             else 0.0
        dx_r = (xs[ix + 1] - x) / 2 if ix < len(xs) - 1  else 0.0
        dy_b = (y - ys[iy - 1]) / 2 if iy > 0             else 0.0
        dy_t = (ys[iy + 1] - y) / 2 if iy < len(ys) - 1  else 0.0
        w = dx_l + dx_r
        h = dy_b + dy_t
        trib[cid] = max(1.0, w * h) if (w > 0 and h > 0) else max(1.0, max(w, h) * 2.5)
    return trib


# ── Beam checks ───────────────────────────────────────────────────────────────

def _check_beams(beams: list[dict], trib: dict[str, float]) -> list[dict]:
    results = []
    for bm in beams:
        g = bm["geometry"]
        attrs = bm.get("attributes", {})
        mat = _material(attrs.get("material", "RCC"))

        L = math.dist(g[0], g[1])          # span, metres
        if L < 0.05:
            continue

        d = float(attrs.get("depth", 600)) / 1000.0   # metres
        b = float(attrs.get("width", BEAM_WIDTH_MM)) / 1000.0  # metres

        A, I, _ = _rect_props(b, d)
        E = mat["E_MPa"] * 1e6             # Pa

        tw = trib.get(bm["id"], 2.5)       # tributary width, m

        # Loads (kN/m)
        w_sw  = mat["density_kNm3"] * b * d
        w_dl  = SDL_KNM2 * tw
        w_ll  = LL_KNM2  * tw
        w_tot = w_sw + w_dl + w_ll

        # Simply supported UDL — bending moment (kN·m)
        M = w_tot * L ** 2 / 8.0

        # Bending stress σ = M·y / I (MPa)
        sigma_b = M * 1e3 * (d / 2) / I / 1e6

        # Average shear stress τ = V / (b·d) (MPa)
        V   = w_tot * L / 2.0
        tau = V * 1e3 / (b * d) / 1e6

        # Deflection: δ = 5wL⁴ / (384EI), mm
        def _defl(w_kNm: float) -> float:
            return 5 * (w_kNm * 1e3) * L ** 4 / (384 * E * I) * 1e3

        d_tot = _defl(w_tot)
        d_ll  = _defl(w_ll)

        lim_tl = L * 1e3 / DEFL_LIMIT_TL
        lim_ll = L * 1e3 / DEFL_LIMIT_LL

        results.append({
            "id":               bm["id"],
            "span_m":           round(L, 3),
            "section_mm":       f"{int(b*1000)}×{int(d*1000)}",
            "material":         attrs.get("material", "RCC"),
            "trib_width_m":     round(tw, 2),
            "w_total_kNm":      round(w_tot, 3),
            "M_max_kNm":        round(M, 3),
            "sigma_bend_MPa":   round(sigma_b, 3),
            "allow_bend_MPa":   mat["allow_bend_MPa"],
            "bend_PASS":        sigma_b <= mat["allow_bend_MPa"],
            "tau_MPa":          round(tau, 4),
            "allow_shear_MPa":  mat["allow_shear_MPa"],
            "shear_PASS":       tau <= mat["allow_shear_MPa"],
            "delta_total_mm":   round(d_tot, 3),
            "delta_LL_mm":      round(d_ll, 3),
            "limit_TL_mm":      round(lim_tl, 3),
            "limit_LL_mm":      round(lim_ll, 3),
            "defl_TL_PASS":     d_tot <= lim_tl,
            "defl_LL_PASS":     d_ll  <= lim_ll,
        })
    return results


# ── Column checks ─────────────────────────────────────────────────────────────

def _check_columns(columns: list[dict], trib: dict[str, float]) -> list[dict]:
    results = []
    for col in columns:
        attrs = col.get("attributes", {})
        mat = _material(attrs.get("material", "RCC"))

        H  = float(attrs.get("height", 3.5))          # m
        b, d = _parse_dim_mm(attrs.get("dimensions", "300x300"))

        A, I_strong, _ = _rect_props(b, d)
        _, I_weak,   _ = _rect_props(d, b)             # weak-axis I
        I_min = min(I_strong, I_weak)
        r_min = math.sqrt(I_min / A)

        E = mat["E_MPa"] * 1e6                         # Pa

        ta = trib.get(col["id"], 9.0)                  # tributary area, m²

        # Axial load (single storey, one floor above)
        P_floor = (SDL_KNM2 + LL_KNM2) * ta            # kN
        P_self  = mat["density_kNm3"] * A * H           # kN
        P_total = P_floor + P_self

        # Direct compressive stress (MPa)
        sigma_c = P_total * 1e3 / A / 1e6

        # Effective length: Le = 0.65H (fixed–pinned, typical RCC frame)
        Le = 0.65 * H
        lam = Le / r_min                                # slenderness ratio

        # Euler critical load (kN) and safety factor
        P_cr = math.pi ** 2 * E * I_min / Le ** 2 / 1e3
        SF   = P_cr / P_total if P_total > 0 else float("inf")

        results.append({
            "id":               col["id"],
            "height_m":         H,
            "section_mm":       f"{int(b*1000)}×{int(d*1000)}",
            "material":         attrs.get("material", "RCC"),
            "trib_area_m2":     round(ta, 2),
            "P_total_kN":       round(P_total, 2),
            "sigma_comp_MPa":   round(sigma_c, 4),
            "allow_comp_MPa":   mat["allow_comp_MPa"],
            "stress_PASS":      sigma_c <= mat["allow_comp_MPa"],
            "slenderness":      round(lam, 1),
            "P_cr_kN":          round(P_cr, 2),
            "SF_buckling":      round(SF, 2),
            "buckling_PASS":    SF >= BUCKLING_SF,
        })
    return results


# ── What-if removal simulation ────────────────────────────────────────────────

def _extract_removal_ids(messages: list[dict]) -> list[str]:
    """Return element IDs from the user's original request only (not tool results)."""
    if not messages:
        return []
    # Extract only the "User request:" portion of the first message
    content = messages[0].get("content", "")
    if "User request:" in content:
        start = content.index("User request:") + len("User request:")
        end   = content.find("\n\n", start)
        text  = content[start:end].strip() if end > start else content[start:].strip()
    else:
        text = content
    if not any(kw in text.lower() for kw in ("remov", "delet", "what if", "without")):
        return []
    return list(dict.fromkeys(
        m.upper() for m in re.findall(r'\b([A-Za-z]\w*_\d+)\b', text)
    ))


def _build_beam_index(beams: list[dict]) -> dict[tuple, list[dict]]:
    idx: dict[tuple, list[dict]] = {}
    for bm in beams:
        for pt in bm["geometry"]:
            idx.setdefault(tuple(pt), []).append(bm)
    return idx


def _trace_span(
    floating_pos: tuple,
    beam_idx: dict[tuple, list[dict]],
    removed_positions: set[tuple],
    remaining_positions: set[tuple],
    visited: set[str],
    initial_dist: float,
) -> float:
    """Walk beam chain from floating_pos through removed columns; return total span."""
    total = initial_dist
    current = floating_pos
    for _ in range(20):
        if current in remaining_positions:
            break
        moved = False
        for bm in beam_idx.get(current, []):
            if bm["id"] in visited:
                continue
            visited.add(bm["id"])
            p1, p2 = tuple(bm["geometry"][0]), tuple(bm["geometry"][1])
            total += math.dist(p1, p2)
            current = p2 if p1 == current else p1
            moved = True
            break
        if not moved:
            break
    return total


def simulate_what_if_removal(
    layout_json_string: str,
    remove_ids: list[str],
    base_trib: dict[str, float],
) -> dict:
    """Re-evaluate beams whose endpoint columns are removed, extending their spans."""
    layout    = json.loads(layout_json_string)
    structure = layout.get("structure", [])

    # Filter to IDs that are actual columns in this layout
    valid_cols = {el["id"] for el in structure if len(el.get("geometry", [])) == 1}
    remove_ids = [i for i in remove_ids if i in valid_cols]
    if not remove_ids:
        return {"error": f"No valid column IDs found in remove list"}

    remove_set = set(remove_ids)

    removed_positions: set[tuple] = {
        tuple(el["geometry"][0])
        for el in structure
        if el["id"] in remove_set and len(el.get("geometry", [])) == 1
    }
    if not removed_positions:
        return {"error": f"No columns found for IDs: {remove_ids}"}

    remaining_positions: set[tuple] = {
        tuple(el["geometry"][0])
        for el in structure
        if el["id"] not in remove_set and len(el.get("geometry", [])) == 1
    }

    all_beams = [el for el in structure if len(el.get("geometry", [])) == 2]
    beam_idx  = _build_beam_index(all_beams)

    results: list[dict] = []
    visited: set[str] = set()

    for bm in all_beams:
        p1, p2 = tuple(bm["geometry"][0]), tuple(bm["geometry"][1])
        p1_removed = p1 in removed_positions
        p2_removed = p2 in removed_positions
        if not p1_removed and not p2_removed:
            continue
        if bm["id"] in visited:
            continue
        visited.add(bm["id"])

        attrs = bm.get("attributes", {})
        mat   = _material(attrs.get("material", "RCC"))
        d     = float(attrs.get("depth", 600)) / 1000.0
        b     = BEAM_WIDTH_MM / 1000.0
        _, I, _ = _rect_props(b, d)
        E = mat["E_MPa"] * 1e6
        tw = base_trib.get(bm["id"], 2.5)

        orig_span = math.dist(p1, p2)

        if p1_removed and p2_removed:
            results.append({
                "id": bm["id"], "original_span_m": round(orig_span, 3),
                "effective_span_m": None, "note": "Both endpoints removed — unsupported",
                "bend_PASS": False, "shear_PASS": False,
                "defl_TL_PASS": False, "defl_LL_PASS": False,
            })
            continue

        floating = p1 if p1_removed else p2
        eff_span = _trace_span(floating, beam_idx, removed_positions,
                               remaining_positions, visited, orig_span)

        w_sw  = mat["density_kNm3"] * b * d
        w_dl  = SDL_KNM2 * tw
        w_ll  = LL_KNM2  * tw
        w_tot = w_sw + w_dl + w_ll

        M       = w_tot * eff_span ** 2 / 8.0
        sigma_b = M * 1e3 * (d / 2) / I / 1e6
        tau     = (w_tot * eff_span / 2) * 1e3 / (b * d) / 1e6

        def _d(w: float) -> float:
            return 5 * (w * 1e3) * eff_span ** 4 / (384 * E * I) * 1e3

        d_tot = _d(w_tot);  d_ll = _d(w_ll)
        lim_tl = eff_span * 1e3 / DEFL_LIMIT_TL
        lim_ll = eff_span * 1e3 / DEFL_LIMIT_LL

        results.append({
            "id":               bm["id"],
            "original_span_m":  round(orig_span, 3),
            "effective_span_m": round(eff_span, 3),
            "section_mm":       f"{int(b*1000)}×{int(d*1000)}",
            "M_max_kNm":        round(M, 3),
            "sigma_bend_MPa":   round(sigma_b, 3),
            "allow_bend_MPa":   mat["allow_bend_MPa"],
            "bend_PASS":        sigma_b <= mat["allow_bend_MPa"],
            "tau_MPa":          round(tau, 4),
            "shear_PASS":       tau <= mat["allow_shear_MPa"],
            "delta_total_mm":   round(d_tot, 3),
            "delta_LL_mm":      round(d_ll, 3),
            "limit_TL_mm":      round(lim_tl, 3),
            "limit_LL_mm":      round(lim_ll, 3),
            "defl_TL_PASS":     d_tot <= lim_tl,
            "defl_LL_PASS":     d_ll  <= lim_ll,
            "note": f"span {orig_span:.1f}m → {eff_span:.1f}m after removing {', '.join(remove_ids)}",
        })

    failures = [r for r in results if not all(
        r.get(k, False) for k in ("bend_PASS", "shear_PASS", "defl_TL_PASS", "defl_LL_PASS")
    )]
    return {
        "simulation":    "what_if_removal",
        "removed_ids":   remove_ids,
        "affected_beams": results,
        "summary": {
            "affected": len(results),
            "failures": len(failures),
            "failed_ids": [r["id"] for r in failures],
            "overall_PASS": not failures,
        },
    }


# ── Public API ────────────────────────────────────────────────────────────────

def evaluate_structure(layout_json_string: str) -> dict:
    layout    = json.loads(layout_json_string)
    structure = layout.get("structure", [])

    beams   = [s for s in structure if len(s.get("geometry", [])) == 2]
    columns = [s for s in structure if len(s.get("geometry", [])) == 1]

    b_trib = _beam_trib_widths(beams)
    c_trib = _column_trib_areas(columns)

    beam_results = _check_beams(beams, b_trib)
    col_results  = _check_columns(columns, c_trib)

    b_fail = [r for r in beam_results if not (r["bend_PASS"] and r["shear_PASS"] and r["defl_TL_PASS"] and r["defl_LL_PASS"])]
    c_fail = [r for r in col_results  if not (r["stress_PASS"] and r["buckling_PASS"])]

    return {
        "beams":   beam_results,
        "columns": col_results,
        "summary": {
            "total_beams":       len(beam_results),
            "beam_failures":     len(b_fail),
            "failed_beam_ids":   [r["id"] for r in b_fail],
            "total_columns":     len(col_results),
            "column_failures":   len(c_fail),
            "failed_column_ids": [r["id"] for r in c_fail],
            "overall_PASS":      not b_fail and not c_fail,
        },
    }


def _apply_material_override(layout_json_string: str, material: str) -> str:
    """Patch all structure elements with the given material and its default sections."""
    layout = json.loads(layout_json_string)
    sec = DEFAULT_SECTIONS.get(material, DEFAULT_SECTIONS["RCC"])
    for el in layout.get("structure", []):
        attrs = el.setdefault("attributes", {})
        attrs["material"] = material
        if len(el.get("geometry", [])) == 2:   # beam
            attrs["depth"] = str(sec["beam_depth_mm"])
            attrs["width"] = str(sec["beam_width_mm"])
        else:                                   # column
            attrs["dimensions"] = sec["col_dims"]
    return json.dumps(layout)


def build_evaluate_node(_):
    """Structural first-principles check node — unused arg kept for graph API compatibility."""

    def evaluate_node(state: dict) -> dict:
        # Human-in-the-loop: ask material on first evaluate pass only
        if state.get("evaluation_result") is None:
            current = state.get("material_override") or "RCC"
            print(f"\nMaterial (current: {current}):")
            for i, (mat, sec) in enumerate(DEFAULT_SECTIONS.items(), 1):
                marker = " <-- active" if mat == current else ""
                print(f"  {i}. {mat:6s} — beam {sec['beam_width_mm']}x{sec['beam_depth_mm']}mm | col {sec['col_dims']}mm{marker}")
            print("  [Enter] — keep current")
            raw = input("Choice [1/2/3 or RCC/STEEL/TIMBER]: ").strip().upper()
            lookup = {"1": "RCC", "2": "STEEL", "3": "TIMBER"}
            selected = lookup.get(raw) or (raw if raw in DEFAULT_SECTIONS else None)
            if selected:
                state["material_override"] = selected

        material_override = state.get("material_override")

        if material_override:
            print(f"\nEvaluating structural integrity (first principles) — material: {material_override}...")
            layout_str = _apply_material_override(state["layout_json_string"], material_override)
        else:
            print("\nEvaluating structural integrity (first principles)...")
            layout_str = state["layout_json_string"]

        # Run standard evaluation
        result  = evaluate_structure(layout_str)
        summary = result["summary"]

        lines = [
            f"Structural check: {'PASS' if summary['overall_PASS'] else 'FAIL'}",
            f"Beams  : {summary['total_beams']} checked, {summary['beam_failures']} failed",
            f"Columns: {summary['total_columns']} checked, {summary['column_failures']} failed",
        ]

        # What-if simulation: detect removal intent in messages
        remove_ids = _extract_removal_ids(state.get("messages", []))
        if remove_ids:
            layout    = json.loads(layout_str)
            structure = layout.get("structure", [])
            beams     = [s for s in structure if len(s.get("geometry", [])) == 2]
            b_trib    = _beam_trib_widths(beams)
            whatif    = simulate_what_if_removal(
                layout_str, remove_ids, b_trib
            )
            result["what_if"] = whatif
            ws = whatif.get("summary", {})
            lines.append("")
            lines.append(f"WHAT-IF: remove {', '.join(remove_ids)}")
            lines.append(f"  Affected beams : {ws.get('affected', 0)}")
            lines.append(f"  Failures       : {ws.get('failures', 0)}")
            if ws.get("failed_ids"):
                lines.append(f"  Failed         : {', '.join(ws['failed_ids'])}")
            for r in whatif.get("affected_beams", []):
                flag = ""
                if not r.get("bend_PASS", True):
                    flag += f"  BEND FAIL σ={r.get('sigma_bend_MPa','?')}>{r.get('allow_bend_MPa','?')}MPa"
                if not r.get("defl_LL_PASS", True):
                    flag += f"  DEFL_LL FAIL {r.get('delta_LL_mm','?')}>{r.get('limit_LL_mm','?')}mm"
                if not r.get("defl_TL_PASS", True):
                    flag += f"  DEFL_TL FAIL {r.get('delta_total_mm','?')}>{r.get('limit_TL_mm','?')}mm"
                span_info = (
                    f"{r['original_span_m']}m→{r['effective_span_m']}m"
                    if r.get("effective_span_m") else "unsupported"
                )
                lines.append(
                    f"  {r['id']:8s} {span_info:14s}"
                    f"  M={r.get('M_max_kNm','?')}kNm"
                    f"  σ={r.get('sigma_bend_MPa','?')}MPa"
                    + (flag if flag else ("  unsupported" if not r.get("effective_span_m") else "  ok"))
                )
            print("\n".join(lines[lines.index("") + 1:]))

            # Feed failures back to reason so it can propose alternatives
            if not ws.get("overall_PASS") and ws.get("failed_ids"):
                fail_lines = []
                for r in whatif.get("affected_beams", []):
                    if not r.get("bend_PASS", True):
                        fail_lines.append(
                            f"{r['id']}: bending σ={r.get('sigma_bend_MPa','?')} > "
                            f"{r.get('allow_bend_MPa','?')} MPa "
                            f"(span {r.get('original_span_m','?')}m→{r.get('effective_span_m','?')}m)"
                        )
                    if not r.get("defl_LL_PASS", True):
                        fail_lines.append(
                            f"{r['id']}: LL deflection {r.get('delta_LL_mm','?')} > "
                            f"{r.get('limit_LL_mm','?')} mm"
                        )
                    if not r.get("defl_TL_PASS", True):
                        fail_lines.append(
                            f"{r['id']}: TL deflection {r.get('delta_total_mm','?')} > "
                            f"{r.get('limit_TL_mm','?')} mm"
                        )
                state["messages"].append({
                    "role": "user",
                    "content": (
                        f"STRUCTURAL FAIL after removing {', '.join(remove_ids)}:\n"
                        + "\n".join(fail_lines)
                        + "\nPropose 2-3 specific alternatives to resolve this failure."
                    ),
                })

        for r in result["beams"]:
            if not r["bend_PASS"]:
                lines.append(
                    f"  BEAM {r['id']} bending FAIL: "
                    f"σ={r['sigma_bend_MPa']} MPa > {r['allow_bend_MPa']} MPa "
                    f"(span {r['span_m']} m, M={r['M_max_kNm']} kN·m)"
                )
            if not r["defl_LL_PASS"]:
                lines.append(
                    f"  BEAM {r['id']} LL deflection FAIL: "
                    f"δ={r['delta_LL_mm']} mm > L/{DEFL_LIMIT_LL}={r['limit_LL_mm']} mm"
                )
            if not r["defl_TL_PASS"]:
                lines.append(
                    f"  BEAM {r['id']} TL deflection FAIL: "
                    f"δ={r['delta_total_mm']} mm > L/{DEFL_LIMIT_TL}={r['limit_TL_mm']} mm"
                )
            if not r["shear_PASS"]:
                lines.append(
                    f"  BEAM {r['id']} shear FAIL: "
                    f"τ={r['tau_MPa']} MPa > {r['allow_shear_MPa']} MPa"
                )

        for r in result["columns"]:
            if not r["stress_PASS"]:
                lines.append(
                    f"  COL {r['id']} stress FAIL: "
                    f"σ={r['sigma_comp_MPa']} MPa > {r['allow_comp_MPa']} MPa "
                    f"(P={r['P_total_kN']} kN)"
                )
            if not r["buckling_PASS"]:
                lines.append(
                    f"  COL {r['id']} buckling FAIL: "
                    f"SF={r['SF_buckling']:.1f} < {BUCKLING_SF} "
                    f"(λ={r['slenderness']}, P_cr={r['P_cr_kN']} kN)"
                )

        eval_text = "\n".join(lines)
        print(eval_text)

        state["evaluation_result"] = json.dumps(result)
        state["messages"].append({
            "role":    "user",
            "content": f"Structural evaluation (first principles):\n{eval_text}",
        })
        return state

    return evaluate_node
