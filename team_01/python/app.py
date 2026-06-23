from __future__ import annotations

import base64
import json
import re
import sys
import urllib.request
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
import plotly.graph_objects as go

# ── Paths ──────────────────────────────────────────────────────────────────────
REPO_ROOT           = Path(__file__).resolve().parents[2]
DEFAULT_LAYOUT_PATH = REPO_ROOT / "layout_input" / "layout_schema.json"
EDITED_LAYOUT_PATH  = REPO_ROOT / "team_01_edited_layout.json"
BEFORE_LAYOUT_PATH  = REPO_ROOT / "team_01_edited_layout_before.json"
VIEWER_BASE_URL     = "http://127.0.0.1:8000/layout_viewer.html"
PLAN_VIEWER_URL     = "http://127.0.0.1:8000/plan_viewer.html"
PYTHON_DIR           = Path(__file__).resolve().parent
LOGO_PATH_LIGHT      = PYTHON_DIR / "Assets" / "Logo.png"
LOGO_PATH_DARK       = PYTHON_DIR / "Assets" / "Logo_dark.png"

def _load_logo(path: Path) -> str:
    try:
        return base64.b64encode(path.read_bytes()).decode() if path.exists() else ""
    except Exception:
        return ""

_logo_b64_light = _load_logo(LOGO_PATH_LIGHT)
_logo_b64_dark  = _load_logo(LOGO_PATH_DARK)

st.set_page_config(
    page_title="PermanenceOS",
    layout="wide",
    initial_sidebar_state="expanded",
)

if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from nodes._layout import (
    find_element_in_layout,
    get_all_rooms,
    get_level_count,
    get_level_keys,
    get_outline,
    get_rooms,
    get_structure,
    is_multilevel,
    iter_all_structure,
)
from viz import (
    _render_floor_plan_plotly, _render_3d_viewport, _count_elements, _present_legend_items,
    _materials_present, _material_legend_html, _structural_summary_text,
    _sheet_pdf_bytes, _beam_diagram_png, _normalize_layout, _strip_structure,
    _flexibility_rows, _flex_advice,
)

# No default layout — app starts empty until the user uploads a file.


# ── JSON helpers ───────────────────────────────────────────────────────────────

def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _push_version(new_layout: dict) -> None:
    """Commit a structural change:
    - push currentLayout onto versionHistory
    - make new_layout the new currentLayout
    - persist to disk (for 3D viewer HTTP access)
    - write a numbered version file
    - clear selected_opt_bar_idx so 2D plan always reads currentLayout
    """
    prev = st.session_state.get("currentLayout") or {}
    if prev:
        hist = st.session_state.get("versionHistory", [])
        hist.append(prev)
        st.session_state.versionHistory = hist

    v = st.session_state.get("currentVersion", 0) + 1
    st.session_state.currentVersion = v
    st.session_state.currentLayout  = new_layout
    st.session_state["selected_opt_bar_idx"] = -1

    _write_json(EDITED_LAYOUT_PATH, new_layout)
    _write_json(REPO_ROOT / f"layout_v{v}.json", new_layout)
    _sync_viewers()


def _sync_viewers() -> None:
    """Signal both viewers to re-read currentLayout on the next rerun."""
    st.session_state.viewer_nonce = st.session_state.get("viewer_nonce", 0) + 1








def _load_working_layout() -> dict:
    """Load the persisted working layout from disk. Returns {} if no file exists."""
    if EDITED_LAYOUT_PATH.exists():
        return _normalize_layout(_read_json(EDITED_LAYOUT_PATH))
    return {}


@st.cache_data(ttl=5)




















def _grid_option_kpis(layout_dict: dict) -> dict:
    """Compute KPIs for a generated grid option to show in the option card."""
    import math as _m
    structure = get_structure(layout_dict)
    cols  = [el for el in structure if len(el.get("geometry", [])) == 1]
    beams = [el for el in structure if len(el.get("geometry", [])) == 2]
    spans = []
    for bm in beams:
        g = bm.get("geometry", [])
        if len(g) == 2:
            spans.append(round(_m.dist(g[0], g[1]), 2))
    perimeter_cols = sum(1 for c in cols if (c.get("attributes") or {}).get("type") == "perimeter")
    internal_cols  = len(cols) - perimeter_cols
    max_span       = max(spans) if spans else 0.0
    avg_span       = round(sum(spans) / len(spans), 2) if spans else 0.0
    mat_set = {(el.get("attributes") or {}).get("material") for el in structure}
    mat_set.discard(None)
    mat_str = ", ".join(sorted(mat_set)) if mat_set else "—"
    return {
        "n_cols": len(cols), "n_beams": len(beams),
        "perimeter_cols": perimeter_cols, "internal_cols": internal_cols,
        "max_span": max_span, "avg_span": avg_span,
        "n_spans": len(spans), "material": mat_str,
    }


def _grid_option_description(idx: int, kpis: dict) -> str:
    """Return a 1-sentence description of a structural grid option based on its KPIs."""
    if kpis["n_cols"] == 0:
        return "No structural elements placed."
    ratio = kpis["n_beams"] / max(kpis["n_cols"], 1)
    if kpis["max_span"] > 6.0:
        style = "long-span open grid"
    elif kpis["internal_cols"] == 0:
        style = "perimeter-only frame"
    elif ratio > 3:
        style = "dense beam network"
    else:
        style = "regular structural grid"
    return (
        f"Option {idx+1}: {style} — {kpis['n_cols']} col / {kpis['n_beams']} beam, "
        f"max span {kpis['max_span']}m (avg {kpis['avg_span']}m)."
    )







# ── Material colour mapping (shared by 2D, 3D and the legend) ───────────────────
# Mid-tones chosen to read on both the light (#f0f8f8) and dark (#0c2020) canvases.


















def _el_detail_html(el_obj: dict, eval_result: dict | None) -> str:
    """SENSI-style element detail card with utilization bars."""
    import math as _math
    eid     = el_obj.get("id", "")
    attrs   = el_obj.get("attributes", {})
    is_beam = len(el_obj.get("geometry", [])) == 2
    el_type = "BEAM" if is_beam else "COL"
    mat     = attrs.get("material", "RCC")
    sec     = (attrs.get("section") or attrs.get("dimensions", "")
               or (f"{attrs.get('width','')}x{attrs.get('depth','')}" if is_beam else ""))
    span_txt = ""
    geo = el_obj.get("geometry", [])
    if is_beam and len(geo) == 2:
        span_txt = f" · {_math.dist(geo[0], geo[1]):.1f} m"

    def _bar(val, allow, passed, label, unit="MPa"):
        ratio = min(val / max(allow, 0.001), 1.0)
        pct   = f"{ratio * 100:.0f}%"
        fc    = "#40d090" if passed else "#ff5050"
        tick  = "✓" if passed else "✗"
        return (
            f'<div style="display:flex;align-items:center;gap:5px;margin-bottom:5px">'
            f'<span style="color:#6ab8b8;width:72px;flex-shrink:0;font-size:.65rem;'
            f'letter-spacing:.5px;text-transform:uppercase">{label}</span>'
            f'<div style="flex:1;height:3px;background:#0d3030;border-radius:2px;overflow:hidden">'
            f'<div style="width:{pct};height:100%;background:{fc};border-radius:2px"></div></div>'
            f'<span style="color:#8ab8b8;width:52px;text-align:right;font-size:.69rem">'
            f'{val:.2f}{unit}</span>'
            f'<span style="color:{fc};font-size:.72rem;font-weight:700;width:12px;text-align:right">{tick}</span>'
            f'</div>'
        )

    overall_pass = None
    checks_html  = ""
    extra_info   = ""

    if is_beam and eval_result:
        for b in eval_result.get("beams", []):
            if b.get("id") != eid:
                continue
            overall_pass = (b.get("bend_PASS") and b.get("shear_PASS")
                            and b.get("defl_TL_PASS") and b.get("defl_LL_PASS"))
            checks_html = (
                _bar(b.get("sigma_bend_MPa", 0), b.get("allow_bend_MPa", 1),
                     b.get("bend_PASS", False), "Bending")
                + _bar(b.get("tau_MPa", 0), b.get("allow_shear_MPa", 1),
                       b.get("shear_PASS", False), "Shear")
                + _bar(b.get("delta_total_mm", 0), b.get("limit_TL_mm", 1),
                       b.get("defl_TL_PASS", False), "Defl TL", "mm")
                + _bar(b.get("delta_LL_mm", 0), b.get("limit_LL_mm", 1),
                       b.get("defl_LL_PASS", False), "Defl LL", "mm")
            )
            extra_info = (f'<div style="font-size:.67rem;color:#5a9090;margin-top:4px">'
                          f'M={b.get("M_max_kNm",0):.1f} kNm · w={b.get("w_total_kNm",0):.2f} kN/m</div>')
            break

    elif not is_beam and eval_result:
        for c in eval_result.get("columns", []):
            if c.get("id") != eid:
                continue
            overall_pass = c.get("stress_PASS") and c.get("buckling_PASS")
            sf       = max(c.get("SF_buckling", 3.0), 0.01)
            sf_limit = 3.0
            checks_html = (
                _bar(c.get("sigma_comp_MPa", 0), c.get("allow_comp_MPa", 1),
                     c.get("stress_PASS", False), "Stress")
                + _bar(sf_limit / sf, 1.0, c.get("buckling_PASS", False), "Buckling", "×SF")
            )
            extra_info = (f'<div style="font-size:.67rem;color:#5a9090;margin-top:4px">'
                          f'P={c.get("P_total_kN",0):.1f} kN · trib={c.get("trib_area_m2",0):.1f} m²</div>')
            break

    status_color = "#40d090" if overall_pass else ("#ff5050" if overall_pass is False else "#5a9090")
    status_text  = "PASS" if overall_pass else ("FAIL" if overall_pass is False else "—")

    return (
        f'<div style="background:#0d2828;border:1px solid #1a5555;border-radius:8px;padding:12px 14px;margin-bottom:8px">'
        f'<div style="display:flex;justify-content:space-between;align-items:flex-start;'
        f'margin-bottom:10px;padding-bottom:8px;border-bottom:1px solid #1a4040">'
        f'<div>'
        f'<div style="font-size:.62rem;color:#5a9090;letter-spacing:1px;text-transform:uppercase">{el_type}</div>'
        f'<div style="font-size:.9rem;font-weight:700;color:#c8eeed;letter-spacing:.3px;margin-top:1px">{eid}</div>'
        f'<div style="font-size:.7rem;color:#5a9090;margin-top:2px">{mat}{(" · " + sec) if sec else ""}{span_txt}</div>'
        f'</div>'
        f'<div style="font-size:1.3rem;font-weight:800;color:{status_color};padding-top:4px;text-align:right">'
        f'{status_text}</div>'
        f'</div>'
        f'{checks_html or "<div style=\'color:#5a9090;font-size:.74rem;padding:4px 0\'>Run evaluation to see checks</div>"}'
        f'{extra_info}'
        f'</div>'
    )


# ── Structural helpers ─────────────────────────────────────────────────────────

def _run_evaluate(layout_json_str: str, sdl: float = 3.5, ll: float = 2.0) -> dict | None:
    try:
        from nodes.evaluate import evaluate_structure
        return evaluate_structure(layout_json_str, ll_kNm2=ll, sdl_kNm2=sdl)
    except Exception as e:
        st.warning(f"Evaluation error: {e}")
        return None


def _run_grid_options(layout: dict, material: str) -> list[dict]:
    import traceback as _tb

    _rooms = get_all_rooms(layout)
    _level_keys = get_level_keys(layout)
    _outline = get_outline(layout, _level_keys[0] if _level_keys else None)

    if not _rooms:
        st.error("Generate Grid failed: layout has no **rooms** key.")
        return []
    if not _outline:
        st.error("Generate Grid failed: layout has no **outline** key.")
        return []

    try:
        from nodes.tag_and_audit import generate_structure
        raw = generate_structure(layout)

        # generate_structure returns a list of full layout dicts on success,
        # or the original unchanged dict when it cannot build a grid.
        if not isinstance(raw, list) or len(raw) == 0:
            st.warning(
                "Generate Grid: no structural options were produced. "
                f"generate_structure returned {type(raw).__name__} "
                f"(rooms={len(_rooms)}, "
                f"outline pts={len(_outline)})."
            )
            return []

        # Wrap each layout dict into the UI's expected format and stamp material.
        opts = []
        for lay in raw:
            lay_copy = dict(lay)
            if "meta" not in lay_copy or not isinstance(lay_copy.get("meta"), dict):
                lay_copy["meta"] = {}
            lay_copy["meta"]["material"] = material
            opts.append({"layout": lay_copy, "evaluation": None})

        return opts

    except Exception as e:
        st.error(f"Generate Grid error: **{e}**")
        st.code(_tb.format_exc(), language="python")
        return []




def _get_failure_alternatives(eval_result: dict, material: str) -> list[str]:
    try:
        from nodes.evaluate import _build_failure_alternatives
        return _build_failure_alternatives(eval_result, [], material)
    except Exception:
        return []





def _apply_alternative(alt: str, layout_str: str, material: str,
                        sdl: float, ll: float) -> tuple[str, dict | None]:
    from nodes.modify import (
        upgrade_element_section, add_midspan_column,
        apply_material_override, BEAM_SECTION_UPGRADE, BEAM_DIM_UPGRADE,
        COL_SECTION_UPGRADE, COL_DIM_UPGRADE, BASE_MATERIALS,
    )
    from nodes.evaluate import evaluate_structure

    if re.match(r"(Increase the|Auto-upgrade) \d+ failing beam", alt, re.IGNORECASE):
        ev = st.session_state.eval_result or {}
        _orig_sec = {b["id"]: b.get("section_mm", "") for b in ev.get("beams", [])}
        _gov0 = {}  # id -> governing failing check (for transparency)
        for b in ev.get("beams", []):
            if not (b["bend_PASS"] and b["shear_PASS"] and b["defl_TL_PASS"] and b["defl_LL_PASS"]):
                _gov0[b["id"]] = ("bending" if not b["bend_PASS"] else "shear" if not b["shear_PASS"]
                                  else "deflection")
        for _ in range(8):
            fails = [b for b in ev.get("beams", [])
                     if not (b["bend_PASS"] and b["shear_PASS"]
                             and b["defl_TL_PASS"] and b["defl_LL_PASS"])]
            if not fails:
                break
            for b in fails:
                cur = b.get("section_mm", "")
                if cur in BEAM_SECTION_UPGRADE:
                    nxt, _, _ = BEAM_SECTION_UPGRADE[cur]
                    layout_str = upgrade_element_section(layout_str, b["id"], nxt)
                elif cur in BEAM_DIM_UPGRADE:
                    nxt, _, _ = BEAM_DIM_UPGRADE[cur]
                    layout_str = upgrade_element_section(layout_str, b["id"], nxt)
            ev = evaluate_structure(layout_str, ll_kNm2=ll, sdl_kNm2=sdl)
        _final = {b["id"]: b.get("section_mm", "") for b in (ev or {}).get("beams", [])}
        st.session_state["_last_fix_log"] = [
            {"id": i, "kind": "beam", "from": _orig_sec.get(i, "?"),
             "to": _final.get(i, "?"), "gov": _gov0.get(i, "—")}
            for i in _gov0 if _orig_sec.get(i) != _final.get(i)
        ]
        return layout_str, ev

    if re.match(r"(Increase the|Auto-upgrade) \d+ failing col", alt, re.IGNORECASE):
        ev = st.session_state.eval_result or {}
        for _ in range(8):
            fails = [c for c in ev.get("columns", [])
                     if not (c["stress_PASS"] and c["buckling_PASS"])]
            if not fails:
                break
            for c in fails:
                cur = c.get("section_mm", "")
                if cur in COL_SECTION_UPGRADE:
                    nxt, _ = COL_SECTION_UPGRADE[cur]
                    layout_str = upgrade_element_section(layout_str, c["id"], nxt)
                elif cur in COL_DIM_UPGRADE:
                    nxt = COL_DIM_UPGRADE[cur]
                    layout_str = upgrade_element_section(layout_str, c["id"], nxt)
            ev = evaluate_structure(layout_str, ll_kNm2=ll, sdl_kNm2=sdl)
        return layout_str, ev

    m = re.match(r"Upgrade (\S+) from \S+ to (\S+)", alt, re.IGNORECASE)
    if m:
        elem_id, new_sec = m.group(1), m.group(2)
        layout_str = upgrade_element_section(layout_str, elem_id, new_sec)
        ev = evaluate_structure(layout_str, ll_kNm2=ll, sdl_kNm2=sdl)
        return layout_str, ev

    m2 = re.match(r"Add midspan column under (?:beam )?(\S+)", alt, re.IGNORECASE)
    if m2:
        beam_id = m2.group(1).rstrip("(")
        layout_str = add_midspan_column(layout_str, beam_id, material)
        ev = evaluate_structure(layout_str, ll_kNm2=ll, sdl_kNm2=sdl)
        return layout_str, ev

    m3 = re.match(r"Switch all framing to (\w+)", alt, re.IGNORECASE)
    if m3:
        new_mat = m3.group(1).upper()
        if new_mat in BASE_MATERIALS:
            layout_str = apply_material_override(layout_str, new_mat)
            ev = evaluate_structure(layout_str, ll_kNm2=ll, sdl_kNm2=sdl)
            return layout_str, ev

    m4 = re.match(r"Upgrade all to (\S+)", alt, re.IGNORECASE)
    if m4:
        tier = m4.group(1)
        layout_str = apply_material_override(layout_str, tier)
        ev = evaluate_structure(layout_str, ll_kNm2=ll, sdl_kNm2=sdl)
        return layout_str, ev

    return layout_str, None


# ── Alt-metrics helpers ────────────────────────────────────────────────────────

_MAT_DENSITY_KNM3  = {"RCC": 25.0,   "STEEL": 78.5,   "TIMBER": 5.0}
_MAT_COST_PER_M3   = {"RCC": 200,    "STEEL": 8_000,  "TIMBER": 1_000}


def _section_area_m2(section_mm: str, material: str) -> float:
    from nodes.modify import STEEL_BEAM_PROPS, STEEL_COL_PROPS
    if "STEEL" in material.upper():
        sp = STEEL_BEAM_PROPS.get(section_mm) or STEEL_COL_PROPS.get(section_mm)
        if sp:
            return sp["A_mm2"] / 1e6
    if "x" in section_mm:
        parts = section_mm.split("x")
        if len(parts) == 2:
            try:
                return float(parts[0]) / 1000.0 * float(parts[1]) / 1000.0
            except ValueError:
                pass
    return 0.01


def _eval_weight_cost(ev: dict) -> tuple[float, float]:
    w = c = 0.0
    for b in ev.get("beams", []):
        mk = next((k for k in _MAT_DENSITY_KNM3 if k in b.get("material", "").upper()), "RCC")
        A  = _section_area_m2(b.get("section_mm", ""), b.get("material", ""))
        v  = A * b.get("span_m", 0.0)
        w += _MAT_DENSITY_KNM3[mk] * v
        c += _MAT_COST_PER_M3[mk]  * v
    for col in ev.get("columns", []):
        mk = next((k for k in _MAT_DENSITY_KNM3 if k in col.get("material", "").upper()), "RCC")
        A  = _section_area_m2(col.get("section_mm", ""), col.get("material", ""))
        v  = A * col.get("height_m", 3.0)
        w += _MAT_DENSITY_KNM3[mk] * v
        c += _MAT_COST_PER_M3[mk]  * v
    return w, c


def _compute_alt_metrics(alt: str, layout_obj: dict, ev0: dict,
                          mat: str, sdl: float, ll: float) -> dict:
    try:
        w0, c0 = _eval_weight_cost(ev0)
        d0 = max((b.get("delta_total_mm", 0) for b in ev0.get("beams", [])), default=0.0)
        _, ev1 = _apply_alternative(alt, json.dumps(layout_obj), mat, sdl, ll)
        if not ev1:
            return {}
        w1, c1 = _eval_weight_cost(ev1)
        d1 = max((b.get("delta_total_mm", 0) for b in ev1.get("beams", [])), default=0.0)
        def _pct(a, b): return (a - b) / max(abs(b), 0.001) * 100
        return {
            "weight_pct": _pct(w1, w0),
            "cost_pct":   _pct(c1, c0),
            "defl_pct":   _pct(d1, d0),
        }
    except Exception:
        return {}


# ── Agent chat ─────────────────────────────────────────────────────────────────

def _llm_is_reachable(timeout: float = 3.0) -> bool:
    try:
        from _runtime.config import load_settings
        _s = load_settings()
        # Anthropic (Claude): reachable as long as an API key is configured.
        if _s.provider == "anthropic":
            return bool(_s.api_key)
        # Local OpenAI-compatible endpoint (e.g. LM Studio): probe /v1/models.
        import urllib.request as _ur
        _url = _s.base_url.rstrip("/").replace("/v1", "") + "/v1/models"
        with _ur.urlopen(_url, timeout=timeout):
            return True
    except Exception:
        return False


def _run_agent_chat(prompt: str, layout: dict, eval_result: dict | None = None) -> str:
    import math as _math
    import re as _re
    try:
        if not _llm_is_reachable():
            from _runtime.config import load_settings as _ls
            if _ls().provider == "anthropic":
                return (
                    "No Anthropic API key configured. "
                    "Add ANTHROPIC_API_KEY to the project .env file, then try again."
                )
            return (
                "LM Studio is not running. "
                "Start LM Studio, load a model, then try again."
            )

        from _runtime.bootstrap import bootstrap
        from _runtime.llm import call_llm
        from nodes.tools import get_action_tools
        SYSTEM_PROMPT = _APP_AGENT_PROMPT
        from graph import _format_tool_catalog

        ctx          = bootstrap()
        tool_catalog = _format_tool_catalog(get_action_tools())
        structure    = get_structure(layout)
        beams        = [el for el in structure if len(el.get("geometry", [])) == 2]
        cols         = [el for el in structure if len(el.get("geometry", [])) == 1]
        sdl          = st.session_state.get("sdl_kNm2", 3.5)
        ll           = st.session_state.get("live_load_kNm2", 2.0)

        # Build comprehensive structure summary (element IDs + sections + spans)
        beam_lines, col_lines = [], []
        for el in structure:
            attrs = el.get("attributes", {})
            geo   = el.get("geometry", [])
            mat   = attrs.get("material", "RCC")
            sec   = (attrs.get("section") or attrs.get("dimensions")
                     or (f"{attrs.get('width','?')}x{attrs.get('depth','?')}"
                         if attrs.get("depth") and attrs.get("width") else "?"))
            if len(geo) == 2:
                span = round(_math.dist(geo[0], geo[1]), 2)
                beam_lines.append(f"{el['id']} {mat} {sec} {span}m")
            elif len(geo) == 1:
                col_lines.append(f"{el['id']} {mat} {sec}")

        eval_lines = ""
        if eval_result:
            s = eval_result.get("summary", {})
            eval_lines = (
                f"\nEvaluation: {'PASS' if s.get('overall_PASS') else 'FAIL'}, "
                f"{s.get('beam_failures', 0)} beam failures, "
                f"{s.get('column_failures', 0)} column failures."
            )
            for b in eval_result.get("beams", []):
                if not (b.get("bend_PASS") and b.get("shear_PASS")
                        and b.get("defl_TL_PASS") and b.get("defl_LL_PASS")):
                    eval_lines += (
                        f"\n  BEAM {b['id']} FAIL "
                        f"(S={b['sigma_bend_MPa']}MPa, span={b['span_m']}m, "
                        f"section={b.get('section_mm','?')})"
                    )
            for c in eval_result.get("columns", []):
                if not (c.get("stress_PASS") and c.get("buckling_PASS")):
                    eval_lines += (
                        f"\n  COL {c['id']} FAIL "
                        f"(S={c['sigma_comp_MPa']}MPa, SF={c['SF_buckling']})"
                    )

        col_summary  = ", ".join(col_lines[:30])  if col_lines  else "none generated yet"
        beam_summary = ", ".join(beam_lines[:20]) if beam_lines else "none generated yet"
        context_msg = {
            "role": "user",
            "content": (
                f"Context: Layout '{layout.get('layoutId', '?')}' has "
                f"{len(cols)} columns and {len(beams)} beams.{eval_lines}\n"
                f"Columns: {col_summary}\n"
                f"Beams: {beam_summary}\n\n"
                f"User request:\n{prompt}"
            ),
        }

        result = call_llm(ctx.llm, SYSTEM_PROMPT, [context_msg], tool_catalog)

        if result.get("action") == "tool":
            calls = result.get("tool_calls", [])
            # Advisory text from the agent (explanation + alternatives)
            _advisory = (result.get("final_response") or "").strip()
            _force = "force" in prompt.lower()
            for _c in calls:
                _cname  = _c.get("name", "")
                _cinput = _c.get("input", _c.get("arguments", {})) or {}

                if _cname == "tag_and_audit":
                    return "GENERATE_GRID" + (f"\n{_advisory}" if _advisory else "")
                if _cname == "evaluate_structure":
                    return "EVALUATE"
                if _cname == "set_material":
                    _mt = str(_cinput.get("material") or _cinput.get("value") or "").upper()
                    if _mt:
                        _lvl = str(_cinput.get("level") or "").strip()
                        _et = str(_cinput.get("element_type") or "").strip()
                        return f"APPLY_MATERIAL:{_mt}|{_lvl}|{_et}"
                if _cname == "modify_structure":
                    _ms_action = _cinput.get("action", "")
                    _ms_eid    = _cinput.get("element_id", "")
                    _ms_attr   = str(_cinput.get("attribute") or "").lower()
                    _ms_val    = _cinput.get("value", "")
                    if _ms_action == "remove" and _ms_eid:
                        return ("APPLY_TOOL:" + json.dumps(
                            {"name": "remove_element",
                             "input": {"element_id": _ms_eid, "force": _force},
                             "advisory": _advisory}))
                    # material set via set_attribute → real material switch
                    if _ms_action == "set_attribute" and _ms_attr == "material" and _ms_val:
                        return f"APPLY_MATERIAL:{str(_ms_val).upper()}"
                    if _ms_action == "set_attribute" and _ms_eid and _ms_val:
                        return ("APPLY_TOOL:" + json.dumps(
                            {"name": "upgrade_element_section",
                             "input": {"element_id": _ms_eid, "new_section": _ms_val},
                             "advisory": _advisory}))
                if _cname == "remove_element" and _cinput.get("element_id"):
                    _cinput["force"] = _force
                    return "APPLY_TOOL:" + json.dumps(
                        {"name": "remove_element", "input": _cinput, "advisory": _advisory})
                if _cname == "add_midspan_column" and (_cinput.get("beam_id") or _cinput.get("element_id")):
                    return "APPLY_TOOL:" + json.dumps(
                        {"name": "add_midspan_column", "input": _cinput, "advisory": _advisory})
                if _cname == "upgrade_element_section" and _cinput.get("element_id"):
                    return "APPLY_TOOL:" + json.dumps(
                        {"name": "upgrade_element_section", "input": _cinput, "advisory": _advisory})

            # The model asked for an action but the parameters were malformed
            # (e.g. empty element_id) — be honest instead of faking success.
            if calls:
                _avail = ", ".join(el["id"] for el in structure[:18])
                return ((_advisory + "\n\n") if _advisory else "") + (
                    "I understood you want an action, but I couldn't read which element to act on. "
                    f"Please name it — available IDs: {_avail}{'…' if len(structure) > 18 else ''}.")

        resp = result.get("final_response", "")
        if not resp:
            # LLM deferred to the in-app pipeline — handle based on intent.
            _lower = prompt.lower()
            # "what if" = simulation only; bare "remove/delete" = execute immediately
            _is_explicit_whatif = any(kw in _lower for kw in
                                      ("what if", "if i remove", "if we remove",
                                       "if you remove", "without"))
            _is_removal = any(kw in _lower for kw in ("remove", "delete"))

            if not structure:
                return (
                    "No structural grid found. "
                    "Click **Generate Grid**, then select an option."
                )

            # Shared ID resolver for both paths
            _sm  = {el["id"].upper(): el["id"] for el in structure}
            _snm = {el["id"].upper().replace("_", ""): el["id"] for el in structure}
            def _rid(m: str):
                k = m.upper()
                return _sm.get(k) or _snm.get(k.replace("_", ""))
            _pat = _re.findall(r'\b([A-Za-z]+_?\d+)\b', prompt, _re.IGNORECASE)
            _ids_in_prompt = list(dict.fromkeys(
                m for m in _pat if _rid(m) and len(m) <= 14
            ))

            # ── ADD a midspan column (split a beam) ───────────────────────────
            if (any(k in _lower for k in ("add column", "add a column", "midspan",
                                          "mid-span", "mid col", "intermediate column",
                                          "split beam")) and _ids_in_prompt):
                return ("APPLY_TOOL:" + json.dumps(
                    {"name": "add_midspan_column",
                     "input": {"beam_id": _rid(_ids_in_prompt[0])}}))

            # ── MATERIAL switch (all elements) ────────────────────────────────
            _mat_kw = ("STEEL" if "steel" in _lower
                       else "TIMBER" if ("timber" in _lower or "wood" in _lower)
                       else "RCC" if ("rcc" in _lower or "concrete" in _lower)
                       else "")
            if _mat_kw and any(k in _lower for k in
                               ("switch", "change", "make it", "convert", "use ", "to ")):
                return f"APPLY_MATERIAL:{_mat_kw}"

            # ── FIX failing elements ─────────────────────────────────────────
            if any(k in _lower for k in ("fix", "repair", "make it pass",
                                          "make them pass", "resolve")):
                return "FIX_FAILING"

            # ── Imperative removal — execute immediately ──────────────────────
            if _is_removal and not _is_explicit_whatif:
                if _ids_in_prompt:
                    _eid_exec = _rid(_ids_in_prompt[0])
                    return f"APPLY_TOOL:{json.dumps({'name': 'remove_element', 'input': {'element_id': _eid_exec}})}"
                _id_list = ", ".join(el["id"] for el in structure[:15])
                return (
                    f"Could not find that element ID. "
                    f"Enable **Labels** to see exact IDs. "
                    f"Available: {_id_list}{'…' if len(structure) > 15 else ''}."
                )

            # ── What-if simulation ─────────────────────────────────────────────
            if _is_explicit_whatif or _is_removal:
                _remove_ids = [_rid(m) for m in _ids_in_prompt]
                if _remove_ids:
                    from nodes.evaluate import simulate_what_if_removal, _beam_trib_widths
                    _b_trib = _beam_trib_widths(beams)
                    _wi = simulate_what_if_removal(
                        json.dumps(layout), _remove_ids, _b_trib,
                        ll_kNm2=ll, sdl_kNm2=sdl,
                    )
                    _aff  = _wi.get("affected_beams", [])
                    _wism = _wi.get("summary", {})
                    if not _aff:
                        return (
                            f"Removing **{', '.join(_remove_ids)}** does not directly "
                            "affect any beam spans — the remaining structure can carry the load."
                        )
                    _lines = [
                        f"**What-if: Remove {', '.join(_remove_ids)}**",
                        f"Result: **{'FAIL' if not _wism.get('overall_PASS') else 'PASS'}** — "
                        f"{_wism.get('failures', 0)} affected beam(s) would fail",
                    ]
                    for _r in _aff[:6]:
                        _orig = _r.get("original_span_m", "?")
                        _eff  = _r.get("effective_span_m")
                        _stxt = (f"{_orig}m → {_eff}m" if _eff else "unsupported")
                        _fails = [k for k, f in [
                            ("bending",    not _r.get("bend_PASS",    True)),
                            ("shear",      not _r.get("shear_PASS",   True)),
                            ("deflection", not (_r.get("defl_TL_PASS", True)
                                                 and _r.get("defl_LL_PASS", True))),
                        ] if f]
                        _st = f"  FAIL ({', '.join(_fails)})" if _fails else "  ok"
                        _lines.append(f"• Beam **{_r['id']}**: span {_stxt}{_st}")
                    if not _wism.get("overall_PASS"):
                        _lines.append(
                            "\nOptions: (1) Add intermediate column to halve the span, "
                            "(2) Upgrade the beam section, "
                            "(3) Add a transfer beam to redirect the load path."
                        )
                    return "\n".join(_lines)
                _id_list = ", ".join(el["id"] for el in structure[:15])
                return (
                    f"Could not find that element ID. "
                    f"Enable **Labels** to see exact IDs. "
                    f"Available: {_id_list}{'…' if len(structure) > 15 else ''}."
                )

            return "EVALUATE"
        return resp
    except Exception as e:
        msg = str(e)
        if any(kw in msg.lower() for kw in
               ("empty response", "unavailable", "rate-limited", "rate limited")):
            return "The AI model is not responding right now — please try again in a moment."
        return f"Agent error: {msg}"


# ── Session state ──────────────────────────────────────────────────────────────

def _ensure_session() -> None:
    defaults: dict = {
        # ── Version / layout state ─────────────────────────────────────────
        "currentLayout":    None,   # dict | None — the live working copy
        "versionHistory":   [],     # list[dict] — every committed past layout
        "currentVersion":   0,      # int — increments on every _push_version
        "setupDone":        False,  # bool — True after upload + OK pressed
        "_last_upload_fp":  None,   # (name, size) of last processed upload
        # ── UI state ───────────────────────────────────────────────────────
        "viewer_nonce":    0,
        "history":         [],
        "agent_log":       [],
        "eval_result":     None,
        "eval_alts":       [],
        "state_history":   [],
        "cost_flexibility": None,
        "last_comparison": None,
        "material":        "RCC",
        "sdl_kNm2":        3.5,
        "live_load_kNm2":  2.0,
        "grid_options":    [],
        "selected_grid":   None,
        "diff_baseline":   None,   # the applied grid/option — Diff toggle compares vs this
        "output_log":      [],
        "selected_el":     "",
        "active_level":    "level_01",
        "active_element_level": "",
        "_last_sel_applied": "\x00",
        "_last_lvl_applied": "\x00",
        "cmp_sel_indices": [],      # indices into snapshots list for compare tab
        "last_click_debug": {},
        "compare_mode":    False,
        "labels_on":       False,
        "auto_eval":       True,
        "snapshots":       [],
        "theme":           "dark",
        "view_mode":       "2D",
        "compare_view_mode": "2D",
        "inputs_expanded": True,
        "selected_opt_bar_idx": -1,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


_ensure_session()

# ─── query params ─────────────────────────────────────────────────────────────
_pending_sel = st.query_params.get("_sel", "")
if _pending_sel != st.session_state.get("_last_sel_applied", "\x00"):
    st.session_state.selected_el = _pending_sel
    st.session_state["_last_sel_applied"] = _pending_sel
_pending_lvl = st.query_params.get("_lvl", "")
if _pending_lvl != st.session_state.get("_last_lvl_applied", "\x00"):
    st.session_state.active_element_level = _pending_lvl
    if _pending_lvl:
        st.session_state.active_level = _pending_lvl
    st.session_state["_last_lvl_applied"] = _pending_lvl

# Toolbar state via query params (set by JS bridge when overlay buttons are clicked)
_tb_vm = st.query_params.get("_tb_vm", "")
if _tb_vm in ("2D", "3D"):
    st.session_state["view_mode"] = _tb_vm
_tb_labels = st.query_params.get("_tb_labels", "")
if _tb_labels in ("0", "1"):
    _new_lab = _tb_labels == "1"
    if _new_lab != st.session_state.labels_on:
        st.session_state.labels_on = _new_lab
        st.session_state.viewer_nonce += 1
_tb_diff = st.query_params.get("_tb_diff", "")
if _tb_diff in ("0", "1"):
    st.session_state.compare_mode = _tb_diff == "1"
_tb_auto = st.query_params.get("_tb_auto", "")
if _tb_auto in ("0", "1"):
    st.session_state["auto_eval"] = _tb_auto == "1"
_aq_raw = st.query_params.get("_aq", "")

# ── UI agent system prompt (direct-LLM path only, does not affect reason.py / LangGraph CLI) ──
_APP_AGENT_PROMPT = """You are a structural design assistant embedded in the PermanenceOS UI.
You help architects modify, evaluate, and understand structural layouts.

ADVISORY-FIRST RULE — for every action that modifies the structure, you MUST:
1. In final_response: briefly explain what this change will do (1-2 sentences), name 1-2 alternatives, then confirm you are executing.
2. Set action="tool" with the correct tool call.
Both final_response and tool_calls MUST be filled simultaneously when executing.

Example format for a remove action:
{{
  "action": "tool",
  "final_response": "Removing column C4. This will merge the beams on either side into a longer span — check that the resulting beam span is within limits. Alternative: you could add a midspan support instead, or simply leave it in place if span limits are already tight. Executing now.",
  "tool_calls": [{{"name": "remove_element", "arguments": {{"element_id": "C4"}}}}]
}}

PERIMETER / NOT-ALLOWED ELEMENTS:
If the element type is "perimeter" or it defines the building envelope, do NOT call a tool.
Set action="final" and explain: why it can't be removed, what the structural risk is, and offer 2 concrete alternatives the architect can actually do (e.g. upgrade sections, add internal support, redesign the span).

ACTIONS:
- REMOVE any element: set action="tool", call remove_element with the exact element_id. Include advisory in final_response.
- ADD midspan column: set action="tool", call add_midspan_column with the beam_id. Include advisory in final_response.
- UPGRADE a section: set action="tool", call upgrade_element_section with element_id (and new_section if known). Include advisory in final_response.
- CHANGE MATERIAL (e.g. "switch to timber", "change material to concrete/RCC", "make it steel"): set action="tool", call set_material with {{"material": "RCC"|"STEEL"|"TIMBER"}}. To scope it, add "level" (e.g. "level_02") and/or "element_type" ("column" or "beam") — e.g. "change all columns and beams of level 2 to timber" → {{"material":"TIMBER","level":"level_02"}}. Do NOT use upgrade_element_section for material changes.
- GENERATE structural grid: set action="tool", call tag_and_audit. Include advisory in final_response.

ALWAYS include the real element_id from the layout context in tool_calls. Never emit a tool call with an empty or placeholder element_id — if you don't know the id, ask for it in final_response with action="final".

EVALUATION (user asks to evaluate, check structure, run analysis, run loads):
Set action="final", final_response="" (empty string). The evaluation runs automatically.

QUESTIONS (explain results, describe layout, interpret failures):
Set action="final" and write a clear, concise answer in final_response.
Use element IDs and values from the layout context. Never invent IDs.

Toolbox:
{tool_catalog}

Return strictly valid JSON:
{{"action": "final" | "tool", "final_response": "...", "tool_calls": [{{"name": "<tool>", "arguments": {{...}}}}]}}
Rules: JSON only, no markdown. If action is final: tool_calls must be []. If action is tool: BOTH final_response AND tool_calls must be filled.
"""

_is_light = st.session_state.get("theme", "dark") == "light"

if _is_light:
    _BG="#f0f7f7"; _SB="#e2eeee"; _CARD="#ffffff"; _ACC="#088a87"; _ACC2="#40a090"
    _BORD="#c0d8d8"; _TEXT="#1a2a30"; _MUT="#5a7070"; _DIM="#8aacac"
    _FAIL="#c02020"; _PASS_C="#097040"; _PASS_BG="#d0f4e8"; _FAIL_BG="#fce8e8"
    _CHAT_Q="#ddeef0"; _CHAT_A="#f0f9f9"; _NUM1_BG=_ACC; _NUM1_C="#fff"
    _NUM2_BG="#c07020"; _NUM3_BG="#3070a0"
    _HIGH_BG="#d4f0d4"; _HIGH_C="#1a7020"
    _MED_BG="#f4e4b0";  _MED_C="#806010"
    _LOW_BG="#c8ddf0";  _LOW_C="#2060a0"
    _LOAD_BG="#eef6f6"; _SNAP_BG="#e0eef0"
else:
    _BG="#071a1a"; _SB="#091f1f"; _CARD="#0d2828"; _ACC="#2ac0c0"; _ACC2="#222D28"
    _BORD="#1a4040"; _TEXT="#c8eeed"; _MUT="#5a9090"; _DIM="#3a6060"
    _FAIL="#ff5050"; _PASS_C="#40d090"; _PASS_BG="#0a3020"; _FAIL_BG="#300a0a"
    _CHAT_Q="#0a3030"; _CHAT_A="#071a1a"; _NUM1_BG=_ACC; _NUM1_C="#071a1a"
    _NUM2_BG="#c07020"; _NUM3_BG="#3070a0"
    _HIGH_BG="#0d2e0d"; _HIGH_C="#60d060"
    _MED_BG="#2e2400";  _MED_C="#d0a020"
    _LOW_BG="#0a1e30";  _LOW_C="#40a0c8"
    _LOAD_BG="#0d2020"; _SNAP_BG="#0d2020"

_F = "'Suisse Intl','Suisse Int\\'l','Inter','Segoe UI',system-ui,sans-serif"

_CSS = f"""
@import url('https://fonts.cdnfonts.com/css/suisse-intl');
/* ── Universal font: all text elements except icon spans ────────────────── */
html,body,p,h1,h2,h3,h4,h5,h6,
div,section,article,aside,header,main,footer,nav,
label,a,li,td,th,caption,
input,textarea,select,option,
button,
[data-testid]:not([data-testid="stIconMaterial"]){{
  font-family:{_F}!important;
  -webkit-font-smoothing:antialiased!important;
  -moz-osx-font-smoothing:grayscale!important;
}}
/* ── Restore Material Symbols for Streamlit icon spans ───────────────────── */
[data-testid="stIconMaterial"],
[class*="material-symbols"],
[class*="material-icons"]{{
  font-family:'Material Symbols Rounded','Material Symbols Sharp','Material Icons Rounded','Material Icons'!important;
  font-feature-settings:'liga'!important;
  -webkit-font-feature-settings:'liga'!important;
}}
/* ── Buttons: always fit text, no overflow ───────────────────────────────── */
button{{overflow:hidden!important}}
button>div,button p,button span:not([data-testid="stIconMaterial"]){{
  overflow:hidden!important;text-overflow:ellipsis!important;white-space:nowrap!important;
}}
/* ── Type scale (5 steps) ──────────────────────────────────────────────── */
/* xs=0.63rem  sm=0.70rem  md=0.78rem  lg=0.88rem  xl=1.0rem             */
html,body,[data-testid="stApp"],[data-testid="stAppViewContainer"],[data-testid="stMain"]{{
  background:{_BG}!important;font-family:{_F}!important;font-size:13px!important;
  letter-spacing:.01em!important}}
[data-testid="block-container"]{{padding:.3rem 1rem .2rem!important;max-width:100%!important}}
section[data-testid="stSidebar"]{{
  background:{_SB}!important;border-right:1px solid {_BORD}!important;
  width:clamp(280px,24vw,380px)!important;min-width:280px!important;
  flex:0 1 clamp(280px,24vw,380px)!important}}
section[data-testid="stSidebar"]>div:first-child{{padding:14px 14px 10px!important}}
/* ── Responsive: never clip text; reflow on smaller / zoomed screens ───────── */
.page-hdr,.plan-legend{{flex-wrap:wrap!important}}
.stat-chip,.hdr-lid{{white-space:normal!important;overflow:visible!important}}
/* buttons & download buttons wrap their labels rather than truncating */
.stButton>button,[data-testid="stDownloadButton"]>button,[data-testid="stPopover"]>button{{
  white-space:normal!important;height:auto!important;line-height:1.25!important;min-height:0!important}}
@media (max-width:1500px){{
  html,body,[data-testid="stAppViewContainer"]{{font-size:12px!important}}
  section[data-testid="stSidebar"]{{width:clamp(260px,22vw,340px)!important;min-width:260px!important;
    flex:0 1 clamp(260px,22vw,340px)!important;max-width:340px!important}}
}}
@media (max-width:1200px){{
  html,body,[data-testid="stAppViewContainer"]{{font-size:11px!important}}
  [data-testid="block-container"]{{padding:.3rem .5rem!important}}
  section[data-testid="stSidebar"]{{width:clamp(240px,30vw,300px)!important;min-width:240px!important;
    flex:0 1 clamp(240px,30vw,300px)!important;max-width:300px!important}}
}}
.react-resizable-handle{{display:none!important;pointer-events:none!important}}
[data-testid="stSidebarHeader"]{{display:none!important;height:0!important;padding:0!important;margin:0!important}}
section[data-testid="stSidebar"] p,section[data-testid="stSidebar"] label{{color:{_TEXT}!important;font-family:{_F}!important}}
section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p{{color:{_MUT}!important;font-size:.70rem!important}}
[data-testid="stHeader"],
[data-testid="stStatusWidget"],
[data-testid="stDecoration"],
[data-testid="stToolbar"]{{display:none!important;height:0!important;overflow:hidden!important;padding:0!important;margin:0!important}}
/* ── Tabs ──────────────────────────────────────────────────────────────── */
[data-testid="stTabs"] [data-baseweb="tab-list"]{{background:transparent!important;border-bottom:1px solid {_BORD}!important;gap:0!important;padding:0!important;display:flex!important}}
[data-testid="stTabs"] [data-baseweb="tab"]{{flex:1!important;text-align:center!important;justify-content:center!important;color:{_MUT}!important;font-size:.63rem!important;font-weight:700!important;letter-spacing:1.4px!important;text-transform:uppercase!important;padding:6px 8px!important;border-bottom:2px solid transparent!important;background:transparent!important;font-family:{_F}!important}}
[data-testid="stTabs"] [aria-selected="true"]{{color:{_ACC}!important;border-bottom:2px solid {_ACC}!important}}
[data-testid="stTabs"] [data-baseweb="tab-border"]{{display:none!important}}
[data-testid="stTabPanel"]{{padding-top:6px!important}}
/* ── Form elements ─────────────────────────────────────────────────────── */
[data-testid="stForm"]{{background:{_CARD}!important;border:1px solid {_BORD}!important;border-radius:8px!important;padding:8px!important}}
[data-testid="stTextArea"] textarea{{background:{_CARD}!important;color:{_TEXT}!important;border-color:{_BORD}!important;font-size:.70rem!important;font-family:{_F}!important}}
[data-testid="stTextInput"] input{{background:{_CARD}!important;color:{_TEXT}!important;border-color:{_BORD}!important;font-family:{_F}!important}}
[data-baseweb="select"]>div{{background:{_CARD}!important;border-color:{_BORD}!important;color:{_TEXT}!important;font-family:{_F}!important}}
[data-baseweb="popover"] [role="listbox"]{{background:{_CARD}!important}}
[data-baseweb="popover"] [role="option"]{{color:{_TEXT}!important;font-family:{_F}!important}}
[data-testid="stExpander"] details{{background:{_CARD}!important;border:1px solid {_BORD}!important;border-radius:6px!important}}
[data-testid="stExpander"] summary{{color:{_ACC}!important;font-size:.70rem!important;font-weight:600!important;font-family:{_F}!important}}
/* ── INPUTS dropdown button ────────────────────────────────────────────── */
section[data-testid="stSidebar"] [data-testid="stExpander"]:first-of-type details{{
  background:{_ACC}!important;border:none!important;border-radius:8px!important}}
section[data-testid="stSidebar"] [data-testid="stExpander"]:first-of-type summary{{
  color:#ffffff!important;font-size:.78rem!important;
  font-weight:800!important;letter-spacing:1.2px!important;text-transform:uppercase!important;
  padding:10px 14px!important;font-family:{_F}!important}}
section[data-testid="stSidebar"] [data-testid="stExpander"]:first-of-type details[open]{{
  background:{_CARD}!important;border:1px solid {_ACC}!important}}
section[data-testid="stSidebar"] [data-testid="stExpander"]:first-of-type details[open] summary{{
  color:{_ACC}!important;border-bottom:1px solid {_BORD}!important;margin-bottom:4px!important}}
.inp-sub-hdr{{font-size:.63rem;font-weight:700;color:{_ACC};letter-spacing:1.1px;font-family:{_F};
  text-transform:uppercase;margin:4px 0 6px;padding-bottom:3px;border-bottom:1px solid {_BORD}}}
[data-testid="stFileUploader"] section{{background:{_CARD}!important;border-color:{_BORD}!important}}
[data-testid="stFileUploaderDropzoneInstructions"]{{display:none!important}}
[data-testid="stFileUploaderDropzone"]{{min-height:auto!important;padding:5px 10px!important;background:{_CARD}!important;border-color:{_BORD}!important}}
[data-testid="stRadio"] label p{{color:{_TEXT}!important;font-size:.70rem!important;font-family:{_F}!important}}
[data-testid="stCheckbox"] label p{{color:{_TEXT}!important;font-size:.70rem!important;font-family:{_F}!important}}
[data-testid="stSlider"] [data-baseweb="slider"] [role="slider"]{{background:{_ACC}!important}}
p,label{{color:{_TEXT};font-family:{_F}}}
[data-testid="stMarkdown"] p{{color:{_TEXT};font-family:{_F}}}
small,[data-testid="stCaption"] p{{color:{_MUT}!important;font-size:.63rem!important;font-family:{_F}!important}}
[data-testid="stMetricValue"]{{color:{_TEXT}!important;font-size:.88rem!important;font-family:{_F}!important}}
[data-testid="stMetricLabel"] p{{color:{_MUT}!important;font-size:.63rem!important;font-family:{_F}!important}}
hr{{border-color:{_BORD}!important;margin:8px 0!important}}
button[kind="primary"]{{background:{_ACC}!important;color:#ffffff!important;border:none!important;font-weight:700!important;font-size:.70rem!important;border-radius:6px!important;font-family:{_F}!important;letter-spacing:.3px!important}}
button[kind="secondary"]{{background:transparent!important;color:{_TEXT}!important;border:1px solid {_BORD}!important;font-size:.70rem!important;border-radius:6px!important;font-family:{_F}!important}}
[data-testid="stFormSubmitButton"] button{{color:#ffffff!important}}
/* ── INPUTS expander label ────────────────────────────────────────────── */
section[data-testid="stSidebar"] [data-testid="stExpander"]:first-of-type summary{{
  color:#ffffff!important}}
/* ── Sidebar components ────────────────────────────────────────────────── */
.sb-brand{{font-size:.88rem;font-weight:800;color:{_ACC};letter-spacing:.8px;line-height:1.1;font-family:{_F}}}
.sb-sub{{font-size:.63rem;color:{_MUT};margin-bottom:10px;font-family:{_F}}}
.sb-section{{font-size:.63rem;font-weight:700;color:{_ACC};letter-spacing:1.5px;text-transform:uppercase;margin:12px 0 5px;display:flex;align-items:center;gap:6px;font-family:{_F}}}
.sb-section::after{{content:'';flex:1;height:1px;background:{_BORD}}}
.sb-filename{{font-size:.70rem;font-weight:600;color:{_TEXT};margin:3px 0 1px;font-family:{_F}}}
.sb-success{{font-size:.63rem;color:{_ACC2};font-weight:600;font-family:{_F}}}
.beta{{background:{"#d4f0ee" if _is_light else "#0a3030"};color:{_ACC};font-size:.60rem;font-weight:700;padding:1px 5px;border-radius:3px;vertical-align:middle;margin-left:4px;text-transform:uppercase;letter-spacing:.5px;border:1px solid {_BORD};font-family:{_F}}}
.load-row{{display:flex;justify-content:space-between;font-size:.70rem;padding:3px 0;border-bottom:1px solid {_BORD};color:{_MUT};font-family:{_F}}}
.load-row b{{color:{_TEXT};font-weight:600}}
.load-block{{background:{_LOAD_BG};border:1px solid {_BORD};border-radius:6px;padding:8px 10px}}
/* ── Page header ───────────────────────────────────────────────────────── */
.page-hdr{{display:flex;align-items:center;gap:4px;padding:4px 0 3px;font-family:{_F}}}
.hdr-lid{{font-size:.70rem;color:{_MUT};margin-right:6px;font-family:{_F}}}
.stat-chip{{display:inline-block;background:{"#e8f4f4" if _is_light else "#0d3030"};border:1px solid {_BORD};border-radius:4px;padding:2px 7px;margin-left:3px;font-size:.63rem;color:{_MUT};font-family:{_F}}}
.stat-chip b{{color:{_ACC}}}
.needs-review{{background:{"#fff0e8" if _is_light else "#3a1a08"}!important;color:{"#c04010" if _is_light else "#ff9860"}!important;border-color:{"#d08060" if _is_light else "#7a4020"}!important}}
/* ── Step bar ──────────────────────────────────────────────────────────── */
.step-bar{{display:flex;align-items:center;gap:0;overflow:hidden;padding:2px 0;font-family:{_F}}}
.stp{{display:flex;align-items:center;gap:4px;padding:3px 5px;white-space:nowrap;min-width:0}}
.stp-n{{display:inline-flex;width:20px;height:20px;border-radius:50%;font-size:.60rem;font-weight:800;align-items:center;justify-content:center;flex-shrink:0;font-family:{_F}}}
.stp-done .stp-n{{background:{_ACC};color:{"#fff" if _is_light else "#071a1a"}}}
.stp-active .stp-n{{background:{"#fff" if _is_light else "#0d2828"};color:{_ACC};border:2px solid {_ACC}}}
.stp-todo .stp-n{{background:{"#dde8e8" if _is_light else "#1a3030"};color:{_MUT}}}
.stp-lbl{{font-size:.63rem;font-weight:600;font-family:{_F}}}
.stp-done .stp-lbl{{color:{_TEXT}}}
.stp-active .stp-lbl{{color:{_ACC};font-weight:700}}
.stp-todo .stp-lbl{{color:{_MUT}}}
.stp-sub{{font-size:.60rem;color:{_MUT};font-family:{_F}}}
.stp-arr{{color:{_BORD};font-size:.63rem;margin:0 0px;flex-shrink:0}}
/* ── Plan legend ───────────────────────────────────────────────────────── */
.plan-legend{{display:flex;gap:12px;padding:5px 4px 3px;flex-wrap:wrap;font-family:{_F}}}
.leg-item{{display:flex;align-items:center;gap:4px;font-size:.63rem;color:{_MUT}}}
.leg-col{{width:9px;height:9px;border-radius:50%;background:{_ACC};flex-shrink:0}}
.leg-beam{{width:14px;height:3px;background:{_ACC2};flex-shrink:0;border-radius:1px}}
.leg-wall{{width:14px;height:3px;background:{"#889898" if _is_light else "#445858"};flex-shrink:0}}
.leg-dash{{width:14px;height:0;border-top:2px dashed {_MUT};flex-shrink:0}}
.stat-bar{{background:{_CARD};border:1px solid {_BORD};border-radius:6px;padding:6px 12px;display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-top:4px;font-family:{_F}}}
.sb-i{{font-size:.63rem;color:{_MUT};white-space:nowrap;font-family:{_F}}}
.sb-i b{{color:{_TEXT};font-weight:600}}
.sb-pass{{background:{_PASS_BG};color:{_PASS_C};font-size:.63rem;font-weight:700;padding:2px 8px;border-radius:10px;white-space:nowrap;font-family:{_F}}}
.sb-fail{{background:{_FAIL_BG};color:{_FAIL};font-size:.63rem;font-weight:700;padding:2px 8px;border-radius:10px;white-space:nowrap;font-family:{_F}}}
.sb-pend{{color:{_MUT};font-size:.63rem;font-family:{_F}}}
/* ── Panel header ──────────────────────────────────────────────────────── */
.panel-hdr{{font-size:.60rem;font-weight:700;color:{_ACC};letter-spacing:1.4px;text-transform:uppercase;margin:4px 0 7px;display:flex;align-items:center;gap:6px;font-family:{_F}}}
.panel-hdr::after{{content:'';flex:1;height:1px;background:{_BORD}}}
/* ── Recommendation cards ──────────────────────────────────────────────── */
.rec-card{{background:{_CARD};border:1px solid {_BORD};border-radius:8px;padding:12px;margin-bottom:9px;font-family:{_F}}}
.rec-top{{display:flex;align-items:center;gap:6px;margin-bottom:4px}}
.rec-n{{display:inline-flex;width:22px;height:22px;border-radius:50%;font-size:.63rem;font-weight:800;align-items:center;justify-content:center;flex-shrink:0;color:#fff;font-family:{_F}}}
.rec-title{{font-size:.78rem;font-weight:700;color:{_TEXT};flex:1;min-width:0;font-family:{_F}}}
.imp-high{{background:{_HIGH_BG};color:{_HIGH_C};font-size:.60rem;font-weight:700;padding:2px 6px;border-radius:8px;text-transform:uppercase;letter-spacing:.3px;white-space:nowrap;font-family:{_F}}}
.imp-med{{background:{_MED_BG};color:{_MED_C};font-size:.60rem;font-weight:700;padding:2px 6px;border-radius:8px;text-transform:uppercase;letter-spacing:.3px;white-space:nowrap;font-family:{_F}}}
.imp-low{{background:{_LOW_BG};color:{_LOW_C};font-size:.60rem;font-weight:700;padding:2px 6px;border-radius:8px;text-transform:uppercase;letter-spacing:.3px;white-space:nowrap;font-family:{_F}}}
.rec-desc{{font-size:.70rem;color:{_MUT};line-height:1.4;margin-bottom:8px;font-family:{_F}}}
.rec-metrics{{display:flex;gap:0;border-top:1px solid {_BORD};padding-top:8px;margin-bottom:8px}}
.rec-met{{flex:1;text-align:center}}
.rec-met-lbl{{font-size:.60rem;color:{_MUT};text-transform:uppercase;letter-spacing:.3px;margin-bottom:1px;font-family:{_F}}}
.rec-met-pos{{font-size:.70rem;font-weight:700;color:{_PASS_C};font-family:{_F}}}
.rec-met-neg{{font-size:.70rem;font-weight:700;color:{_FAIL};font-family:{_F}}}
/* ── Chat & agent ──────────────────────────────────────────────────────── */
.chat-q{{background:{_CHAT_Q};border-left:3px solid {_ACC};border-radius:4px;padding:7px 10px;margin-bottom:5px;font-size:.92rem;color:{_TEXT};line-height:1.6;font-family:{_F}}}
.chat-a{{background:{_CHAT_A};border-left:3px solid {_ACC2};border-radius:4px;padding:7px 10px;margin-bottom:5px;font-size:.92rem;color:{_TEXT};line-height:1.6;font-family:{_F}}}
/* Larger, clearer agent input in the sidebar */
section[data-testid="stSidebar"] textarea{{font-size:.92rem!important;line-height:1.55!important}}
section[data-testid="stSidebar"] .stForm [data-testid="stFormSubmitButton"] button{{font-size:.84rem!important;font-weight:700!important}}
.agent-resp{{background:{_CHAT_Q};border-left:3px solid {_ACC};padding:8px 10px;border-radius:3px;font-size:.80rem;color:{_TEXT};line-height:1.6;margin-top:5px;font-family:{_F}}}
/* ── Element & analysis ────────────────────────────────────────────────── */
.crit-item{{background:{"#fff4f4" if _is_light else "#200808"};border-left:3px solid {"#cc2020" if _is_light else "#aa2020"};padding:4px 7px;margin-bottom:3px;border-radius:2px;font-size:.70rem;color:{_TEXT};cursor:pointer;font-family:{_F}}}
.pass-badge{{background:{_PASS_BG};color:{_PASS_C};padding:2px 8px;border-radius:4px;font-weight:700;font-size:.70rem;display:inline-block;margin:3px 0;font-family:{_F}}}
.hist-item{{display:flex;gap:8px;margin-bottom:6px;padding-bottom:6px;border-bottom:1px solid {_BORD};font-family:{_F}}}
.hist-dot{{width:7px;height:7px;border-radius:50%;background:{_ACC};margin-top:4px;flex-shrink:0}}
.hist-label{{font-size:.70rem;color:{_TEXT};font-weight:600;font-family:{_F}}}
.hist-sub{{font-size:.63rem;color:{_MUT};font-family:{_F}}}
.log-entry{{background:{_CARD};border-left:3px solid {_ACC};padding:4px 7px;margin-bottom:3px;border-radius:3px;font-size:.70rem;color:{_TEXT};font-family:{_F}}}
/* ── Grid option cards ─────────────────────────────────────────────────── */
.grid-card{{border:1px solid {_BORD};border-radius:6px;padding:6px 9px;margin-bottom:4px;background:{_CARD};font-family:{_F}}}
.grid-card-active{{border-color:{_ACC};background:{"#ddf4f4" if _is_light else "#0d3030"}}}
.grid-label{{font-size:.78rem;font-weight:700;color:{_TEXT};font-family:{_F}}}
.grid-spacing{{font-size:.63rem;color:{_MUT};font-family:{_F}}}
.fail-ct{{color:{_FAIL};font-weight:700}}.pass-ct{{color:{_PASS_C};font-weight:700}}
.snap-pill{{display:inline-block;background:{_SNAP_BG};border:1px solid {_BORD};color:{_MUT};padding:2px 8px;border-radius:10px;margin:2px;font-size:.63rem;font-family:{_F}}}
.snap-pill-active{{border-color:{_ACC};color:{_ACC};font-weight:700}}
/* ── Compare cards ─────────────────────────────────────────────────────── */
.cmp-card-hdr{{background:{"#eef7f7" if _is_light else "#0d2828"};border-bottom:1px solid {_BORD};padding:6px 11px;display:flex;justify-content:space-between;align-items:center;font-family:{_F}}}
.cmp-title{{font-size:.70rem;font-weight:700;color:{_TEXT};font-family:{_F}}}
.badge-curr{{background:{"#d0ecec" if _is_light else "#0d3030"};color:{_ACC};font-size:.60rem;padding:2px 7px;border-radius:8px;font-family:{_F}}}
.badge-opt{{background:{_HIGH_BG};color:{_HIGH_C};font-size:.60rem;padding:2px 7px;border-radius:8px;font-family:{_F}}}
.insight-card{{background:{_CARD};border:1px solid {_BORD};border-radius:8px;padding:10px 12px;margin-bottom:6px;display:flex;align-items:flex-start;gap:10px;font-family:{_F}}}
.insight-ico{{font-size:1.0rem;margin-top:1px}}
.insight-lbl{{font-size:.60rem;color:{_MUT};text-transform:uppercase;letter-spacing:.3px;font-family:{_F}}}
.insight-opt{{font-size:.78rem;font-weight:700;color:{_TEXT};font-family:{_F}}}
.insight-det{{font-size:.63rem;color:{_MUT};font-family:{_F}}}
.rec-box{{background:{_HIGH_BG};border:1px solid {"#90c8a0" if _is_light else "#1a5020"};border-radius:8px;padding:11px;margin-top:7px;font-family:{_F}}}
.rec-box-lbl{{font-size:.60rem;color:{_HIGH_C};text-transform:uppercase;letter-spacing:1px;font-weight:700;margin-bottom:4px;font-family:{_F}}}
.rec-box-txt{{font-size:.70rem;color:{_TEXT};line-height:1.5;font-family:{_F}}}
/* ── Compare table ─────────────────────────────────────────────────────── */
.cmp-tbl{{width:100%;border-collapse:collapse;border:1px solid {_BORD};border-radius:8px;overflow:hidden;font-family:{_F}}}
.cmp-tbl th{{padding:6px 10px;background:{_CARD};border-bottom:1px solid {_BORD};font-size:.63rem;color:{_MUT};text-transform:uppercase;letter-spacing:.6px;text-align:center;font-family:{_F}}}
.cmp-tbl th:first-child{{text-align:left}}
.cmp-tbl td{{padding:6px 10px;font-size:.70rem;text-align:center;border-bottom:1px solid {_BORD};font-family:{_F}}}
.cmp-tbl td:first-child{{text-align:left;color:{_MUT};font-size:.63rem;font-weight:600}}
.cmp-best{{color:{_PASS_C};font-weight:700}}
.cmp-norm{{color:{_TEXT};font-weight:600}}
/* ── Layout ────────────────────────────────────────────────────────────── */
[data-testid="stAppViewContainer"]{{overflow-x:hidden!important}}
[data-testid="stMainBlockContainer"]{{padding:.4rem .8rem .4rem!important;max-width:100%!important}}
[data-testid="block-container"]{{padding:.4rem .8rem .4rem!important;max-width:100%!important}}
/* ── Static sidebar ────────────────────────────────────────────────────── */
[data-testid="collapsedControl"],
[data-testid="stSidebarCollapseButton"],
[data-testid="stSidebarCollapsedControl"],
button[aria-label="Close sidebar"],
button[aria-label="Open sidebar"],
button[aria-label="collapse"],
button[aria-label="expand"]{{display:none!important;pointer-events:none!important}}
section[data-testid="stSidebar"]{{
  width:clamp(280px,24vw,380px)!important;min-width:280px!important;max-width:380px!important;
  transform:translateX(0)!important;transition:none!important;visibility:visible!important}}
section[data-testid="stSidebar"]>div:first-child{{
  width:100%!important;padding:12px 16px 10px!important;overflow-y:auto!important}}
.inp-toggle button{{
  padding:1px 6px!important;min-height:unset!important;font-size:.70rem!important;
  background:transparent!important;border:1px solid {_BORD}!important;
  color:{_MUT}!important;border-radius:4px!important;line-height:1.4!important;font-family:{_F}!important}}
/* ── Compare tab: slightly narrower sidebar to give more room ─────── */
body:has([role="tablist"] [role="tab"]:nth-child(2)[aria-selected="true"])
  [data-testid="stMainBlockContainer"]{{padding-left:.4rem!important;max-width:100%!important}}
"""

st.markdown(f"<style>{_CSS}</style>", unsafe_allow_html=True)

# ─── JS bridge ────────────────────────────────────────────────────────────────
st.html("""
<script>
(function(){
  if(window._selBridgeReady)return;window._selBridgeReady=true;
  function _rerun(url){
    window.parent.history.replaceState(null,'',url.toString());
    window.parent.dispatchEvent(new PopStateEvent('popstate',{state:null}));
    setTimeout(function(){window.parent.dispatchEvent(new PopStateEvent('popstate',{state:null}));},40);
  }
  window.parent.addEventListener('message',function(ev){
    if(!ev.data||!ev.data.type)return;
    var url=new URL(window.parent.location.href);
    if(ev.data.type==='selectElement'){
      var eid=ev.data.elementId||'';
            var lvl=ev.data.level||'';
      var prev=url.searchParams.get('_sel')||'';
            var prevLvl=url.searchParams.get('_lvl')||'';
            if(eid===prev && lvl===prevLvl)return;
      if(eid){url.searchParams.set('_sel',eid);}else{url.searchParams.delete('_sel');}
            if(lvl){url.searchParams.set('_lvl',lvl);}else{url.searchParams.delete('_lvl');}
      _rerun(url);
    } else if(ev.data.type==='toolbar'){
      url.searchParams.set('_tb_'+ev.data.key, ev.data.val);
      _rerun(url);
    } else if(ev.data.type==='agentQuery'){
      url.searchParams.set('_aq', ev.data.text.slice(0,600));
      _rerun(url);
    }
  });
})();
</script>""", unsafe_allow_javascript=True, width="content")


# ─── layout data ──────────────────────────────────────────────────────────────
# currentLayout in session state is the authoritative source.
# On first load after a browser refresh we recover from disk (if the user had
# previously uploaded) so they don't lose work on an accidental refresh.
if st.session_state.currentLayout is None and EDITED_LAYOUT_PATH.exists():
    _recovered = _load_working_layout()
    if _recovered:
        st.session_state.currentLayout = _recovered
        st.session_state.setupDone = True   # disk file = previously committed

layout_obj      = st.session_state.currentLayout or {}
# NOTE: diff_baseline is set ONLY when a grid is generated or an option/recommendation
# is applied (see Generate Grid / Apply Option / agent handlers). We deliberately do
# NOT capture it from the raw uploaded layout — otherwise Diff would draw phantom
# "removed/added" ghosts before any grid exists.
_level_keys_now = get_level_keys(layout_obj) if layout_obj else ["level_01"]
if st.session_state.get("active_level") not in (_level_keys_now + ["__ALL__"]):
    st.session_state.active_level = _level_keys_now[0] if _level_keys_now else "level_01"
n_cols, n_beams = _count_elements(layout_obj)
er              = st.session_state.eval_result
_sm             = (er or {}).get("summary", {})
_has_fail       = _sm.get("beam_failures", 0) > 0 or _sm.get("column_failures", 0) > 0
_mat_now        = st.session_state.material
_sdl_now        = st.session_state.sdl_kNm2
_ll_now         = st.session_state.live_load_kNm2

# ─── agent drawer: process query + inject global slide-out panel ───────────────
if _aq_raw.strip():
    st.query_params["_aq"] = ""
    _aq_resp = _run_agent_chat(_aq_raw, layout_obj, er)
    if _aq_resp.startswith("APPLY_TOOL:"):
        try:
            _aq_td = json.loads(_aq_resp[len("APPLY_TOOL:"):])
            _aq_tn, _aq_ti = _aq_td.get("name", ""), _aq_td.get("input", {})
            if _aq_tn == "remove_element":
                from nodes.modify import remove_element as _aq_rem
                _aq_eid = _aq_ti.get("element_id", "")
                if _aq_eid:
                    _aq_nl = json.loads(_aq_rem(json.dumps(layout_obj), _aq_eid, bool(_aq_ti.get("force"))))
                    if find_element_in_layout(_aq_nl, _aq_eid)[1] is not None:
                        _aq_resp = f"**{_aq_eid}** is a perimeter element (locked). Say 'force remove {_aq_eid}' to override."
                    else:
                        _push_version(_aq_nl)
                        _aq_resp = f"Removed **{_aq_eid}** from the layout."
            elif _aq_tn == "add_midspan_column":
                from nodes.modify import add_midspan_column as _aq_amc
                _aq_bid = _aq_ti.get("beam_id", "") or _aq_ti.get("element_id", "")
                if _aq_bid:
                    _push_version(json.loads(_aq_amc(json.dumps(layout_obj), _aq_bid, _mat_now)))
                    _aq_resp = f"Added midspan column to **{_aq_bid}**."
            elif _aq_tn == "upgrade_element_section":
                from nodes.modify import upgrade_element_section as _aq_ups
                _aq_uid = _aq_ti.get("element_id", "")
                if _aq_uid:
                    _push_version(json.loads(_aq_ups(json.dumps(layout_obj), _aq_uid,
                                                     _aq_ti.get("new_section", "") or _aq_ti.get("value", ""))))
                    _aq_resp = f"Upgraded section of **{_aq_uid}**."
        except Exception as _aq_tex:
            _aq_resp = f"Tool execution failed: {_aq_tex}"
    elif _aq_resp.startswith("APPLY_MATERIAL:"):
        try:
            from nodes.modify import apply_material_override
            _aqp = _aq_resp[len("APPLY_MATERIAL:"):].split("|")
            _aq_mt = (_aqp[0].strip() or _mat_now).upper()
            _aq_lvl = _aqp[1].strip() if len(_aqp) > 1 else ""
            _aq_et  = _aqp[2].strip() if len(_aqp) > 2 else ""
            _push_version(json.loads(apply_material_override(
                json.dumps(layout_obj), _aq_mt, level=_aq_lvl or None, element_type=_aq_et or None)))
            _aq_resp = f"Switched **{_aq_mt}**" + (f" ({_aq_et or 'all'} of {_aq_lvl})" if _aq_lvl else "") + ". Run analysis to check it."
        except Exception as _aqme:
            _aq_resp = f"Material switch failed: {_aqme}"
    elif _aq_resp in ("GENERATE_GRID", "EVALUATE", "FIX_FAILING") or _aq_resp.startswith("GENERATE_GRID"):
        _aq_resp = "Use the sidebar **AI Agent** chat to run that action."
    st.session_state.history.append({"prompt": _aq_raw, "response": _aq_resp})

_drawer_bg    = "#ffffff" if _is_light else "#0d2828"
_drawer_bord  = "#c0d8d8" if _is_light else "#1a4040"
_drawer_text  = "#1a2a30" if _is_light else "#c8eeed"
_drawer_acc   = "#088a87" if _is_light else "#2ac0c0"
_drawer_mut   = "#5a7070" if _is_light else "#5a9090"
_drawer_btn_c = "#ffffff" if _is_light else "#071a1a"

_drawer_history_html = ""
for _dh in st.session_state.get("history", [])[-3:]:
    _dq = str(_dh.get("prompt", "")).replace("<", "&lt;").replace(">", "&gt;")
    _da = str(_dh.get("response", "")).replace("<", "&lt;").replace(">", "&gt;")
    _drawer_history_html += f'<div class="dq">You: {_dq}</div><div>{_da}</div>'
_hist_js = json.dumps(_drawer_history_html)

st.html(f"""<script>
(function(){{
  var par = window.parent.document;
  var win = window.parent;
  var _hh = {_hist_js};

  // Always re-inject or update styles so they survive Streamlit hot-reloads
  var _sid = 'agent-drawer-styles';
  var _oldStyle = par.getElementById(_sid);
  if(_oldStyle) _oldStyle.remove();
  var style = par.createElement('style');
  style.id = _sid;
  style.textContent =
    '#agent-drawer{{position:fixed;top:50%;right:0;transform:translateY(-50%) translateX(100%);transition:transform 0.28s cubic-bezier(.4,0,.2,1);width:290px;z-index:99999;background:{_drawer_bg};border:1px solid {_drawer_bord};border-right:none;border-radius:12px 0 0 12px;box-shadow:-6px 0 24px rgba(0,0,0,0.4);font-family:\'Suisse Intl\',\'Inter\',sans-serif;}}'
    +'#agent-drawer.open{{transform:translateY(-50%) translateX(0);}}'
    +'#agent-drawer-tab{{position:absolute;left:-30px;top:50%;transform:translateY(-50%);width:30px;height:52px;background:{_drawer_bg};border:1px solid {_drawer_bord};border-right:none;border-radius:10px 0 0 10px;display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:14px;color:{_drawer_acc};user-select:none;}}'
    +'#agent-drawer-body{{padding:14px 14px 12px;}}'
    +'#agent-drawer-title{{font-size:11px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:{_drawer_acc};margin-bottom:10px;}}'
    +'#agent-drawer-history{{max-height:180px;overflow-y:auto;font-size:11px;color:{_drawer_mut};margin-bottom:10px;line-height:1.5;}}'
    +'#agent-drawer-history .dq{{color:{_drawer_text};font-weight:600;}}'
    +'#agent-drawer-input{{width:100%;box-sizing:border-box;background:rgba(128,128,128,0.08);border:1px solid {_drawer_bord};border-radius:6px;color:{_drawer_text};font-size:12px;padding:8px 10px;resize:none;font-family:inherit;margin-bottom:8px;}}'
    +'#agent-drawer button{{width:100%;background:{_drawer_acc};color:{_drawer_btn_c};border:none;border-radius:6px;font-size:12px;font-weight:700;padding:7px;cursor:pointer;font-family:inherit;}}';
  par.head.appendChild(style);

  // Update history if panel already exists
  var existing = par.getElementById('agent-drawer');
  if(existing){{
    var he = par.getElementById('agent-drawer-history');
    if(he) he.innerHTML = _hh;
    return;
  }}

  // Build panel — note: onclick runs in parent page context so call functions directly
  var panel = par.createElement('div');
  panel.id = 'agent-drawer';
  panel.innerHTML =
    '<div id="agent-drawer-tab" onclick="toggleDrawer()">&#9664;</div>'
    +'<div id="agent-drawer-body">'
    +'<div id="agent-drawer-title">Ask Agent</div>'
    +'<div id="agent-drawer-history"></div>'
    +'<textarea id="agent-drawer-input" placeholder="Ask about this design…" rows="3"></textarea>'
    +'<button onclick="submitDrawerQuery()">Send ›</button>'
    +'</div>';
  par.body.appendChild(panel);
  par.getElementById('agent-drawer-history').innerHTML = _hh;

  // Define functions on parent window (global scope of the Streamlit page)
  win._drawerOpen = false;
  win.toggleDrawer = function(){{
    win._drawerOpen = !win._drawerOpen;
    par.getElementById('agent-drawer').classList.toggle('open', win._drawerOpen);
    par.getElementById('agent-drawer-tab').innerHTML = win._drawerOpen ? '&#9654;' : '&#9664;';
  }};
  win.submitDrawerQuery = function(){{
    var txt = par.getElementById('agent-drawer-input').value.trim();
    if(!txt) return;
    par.getElementById('agent-drawer-input').value = '';
    var h = par.getElementById('agent-drawer-history');
    h.innerHTML += '<div class="dq">You: '+txt.replace(/</g,'&lt;').replace(/>/g,'&gt;')+'</div><div>Processing…</div>';
    h.scrollTop = h.scrollHeight;
    win.postMessage({{type:'agentQuery',text:txt}}, '*');
  }};
}})();
</script>""", unsafe_allow_javascript=True, width="content")

# ─── SIDEBAR ──────────────────────────────────────────────────────────────────
prompt_input = ""
submitted    = False

with st.sidebar:
    _active_logo = _logo_b64_light if _is_light else _logo_b64_dark
    if _active_logo:
        st.markdown(
            f'<img src="data:image/png;base64,{_active_logo}"'
            f' style="width:100%;max-height:120px;object-fit:contain;'
            f'object-position:left center;display:block;margin-bottom:6px">',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="sb-brand">PermanenceOS</div>'
            '<div class="sb-sub">AI-Powered Structural Design</div>',
            unsafe_allow_html=True,
        )

    # ── INPUTS dropdown ───────────────────────────────────────────────────────
    _lid = layout_obj.get("layoutId", "")   # always defined for page header use

    with st.expander("INPUTS", expanded=True):

        # ── Upload ────────────────────────────────────────────────────────────
        st.markdown(
            f'<div class="inp-sub-hdr">Upload</div>',
            unsafe_allow_html=True,
        )
        _upload = st.file_uploader(
            "layout", type=["json"], label_visibility="collapsed", key="sb_uploader"
        )
        # Only process the file when it is genuinely new (name+size changed).
        # Without this guard the handler runs on EVERY rerun while the file
        # sits in the uploader, calling st.rerun() each time and preventing
        # any other button (OK, agent, etc.) from executing.
        if _upload is not None:
            _upload_fp = (_upload.name, _upload.size)
            if _upload_fp != st.session_state.get("_last_upload_fp"):
                try:
                    _loaded = _normalize_layout(json.loads(_upload.getvalue().decode("utf-8")))
                    # Strip any pre-built structure from the JSON so the user always
                    # starts with a blank design and must press "Generate Grid" explicitly.
                    _loaded = _strip_structure(_loaded)
                    # Reset all derived state — new file, clean slate
                    for _k in ("eval_result", "eval_alts", "agent_log", "grid_options",
                               "selected_grid", "cost_flexibility", "last_comparison",
                               "history", "state_history", "output_log", "snapshots"):
                        st.session_state[_k] = (
                            [] if isinstance(st.session_state.get(_k), list) else None)
                    st.session_state.currentLayout   = _loaded
                    st.session_state.versionHistory  = []
                    st.session_state.currentVersion  = 1
                    st.session_state.setupDone       = False
                    st.session_state.selected_el     = ""
                    st.session_state.active_level    = "level_01"
                    st.session_state.active_element_level = ""
                    st.session_state["_last_upload_fp"]      = _upload_fp
                    st.session_state["_last_sel_applied"]    = "\x00"
                    st.session_state["_last_lvl_applied"]    = "\x00"
                    st.session_state["selected_opt_bar_idx"] = -1
                    _write_json(EDITED_LAYOUT_PATH, _loaded)
                    st.rerun()
                except Exception as _exc:
                    st.error(f"Invalid JSON: {_exc}")
        if _lid:
            st.markdown(
                f'<div class="sb-filename">{_lid}</div>'
                f'<div class="sb-success">✓ Model loaded — press OK ▶ Apply & Render</div>',
                unsafe_allow_html=True,
            )
            if st.button("↺  Clear & Reset", width="stretch",
                         key="btn_reset_layout"):
                # Wipe everything — user must re-upload
                for _rk, _rv in {
                    "currentLayout": None, "versionHistory": [], "currentVersion": 0,
                    "setupDone": False, "_last_upload_fp": None,
                    "eval_result": None, "eval_alts": [], "agent_log": [],
                    "grid_options": [], "selected_grid": None,
                    "cost_flexibility": None, "last_comparison": None,
                    "history": [], "state_history": [], "output_log": [],
                    "snapshots": [], "selected_el": "",
                    "active_level": "level_01", "active_element_level": "",
                    "_last_sel_applied": "\x00", "selected_opt_bar_idx": -1,
                    "_last_lvl_applied": "\x00",
                }.items():
                    st.session_state[_rk] = _rv
                if EDITED_LAYOUT_PATH.exists():
                    EDITED_LAYOUT_PATH.unlink()
                st.rerun()

        st.divider()

        # ── Define Loads ──────────────────────────────────────────────────────
        st.markdown(
            f'<div class="inp-sub-hdr">Define Loads</div>',
            unsafe_allow_html=True,
        )
        with st.expander("What do these mean?", expanded=False):
            st.markdown(
                "- **SDL — Superimposed Dead Load**: permanent weight *on top of* the "
                "structure's own self-weight — floor finishes, screed, partitions, ceilings, "
                "services. Typical **2.5–3.5 kN/m²**.\n"
                "- **LL — Live Load**: movable/occupancy load (people, furniture). Code values: "
                "**residential ≈2.0**, **office ≈3.0**, **assembly/retail ≈5.0 kN/m²**.\n"
                "- Higher loads → larger sections / closer columns. Pick the use that matches "
                "your building before generating a grid."
            )
        _sdl_opts = {1.5: "1.5", 2.5: "2.5", 3.5: "3.5", 5.0: "5.0"}
        _sdl_v = st.select_slider(
            "Dead Load SDL (kN/m²)", list(_sdl_opts.keys()),
            value=_sdl_now, format_func=lambda v: f"{v} kN/m²",
            help="Permanent load on top of self-weight: finishes, screed, partitions, "
                 "services. Typical 2.5–3.5 kN/m².",
        )
        if _sdl_v != _sdl_now:
            st.session_state.sdl_kNm2 = _sdl_v

        _ll_opts = {2.0: "2.0", 3.0: "3.0", 5.0: "5.0"}
        _ll_v = st.select_slider(
            "Live Load LL (kN/m²)", list(_ll_opts.keys()),
            value=_ll_now, format_func=lambda v: f"{v} kN/m²",
            help="Occupancy load (people, furniture): residential ≈2.0, office ≈3.0, "
                 "assembly/retail ≈5.0 kN/m².",
        )
        if _ll_v != _ll_now:
            st.session_state.live_load_kNm2 = _ll_v

        st.divider()

        # ── Define Materials ──────────────────────────────────────────────────
        st.markdown(
            f'<div class="inp-sub-hdr">Define Materials</div>',
            unsafe_allow_html=True,
        )
        _MAT_LABELS = {"RCC": "Concrete", "STEEL": "Steel", "TIMBER": "Timber"}
        mat_choice = st.radio(
            "Material", list(_MAT_LABELS.keys()),
            format_func=lambda k: _MAT_LABELS[k],
            index=list(_MAT_LABELS.keys()).index(_mat_now),
            horizontal=True, label_visibility="collapsed",
            help="Concrete (RCC): heavy, cheap, fire-resistant, moderate spans. "
                 "Steel: light, strong, long spans, higher cost. "
                 "Timber: lightest & low-carbon but needs larger sections / shorter spans.",
        )
        if mat_choice != _mat_now:
            st.session_state.material     = mat_choice
            st.session_state.grid_options = []
            st.session_state.setupDone    = False   # require OK again after material change

        # ── OK button — commits loads/material into layout metadata and enables viewers
        _ok_disabled = st.session_state.currentLayout is None
        if st.button(
            "OK  ▶  Apply & Render",
            width="stretch", type="primary",
            key="btn_ok_apply", disabled=_ok_disabled,
        ):
            if st.session_state.currentLayout is not None:
                _cl = st.session_state.currentLayout
                if "meta" not in _cl or not isinstance(_cl.get("meta"), dict):
                    _cl["meta"] = {}
                _cl["meta"]["material"] = mat_choice
                _cl["meta"]["SDL"]      = st.session_state.sdl_kNm2
                _cl["meta"]["LL"]       = st.session_state.live_load_kNm2
                st.session_state.currentLayout = _cl
                _write_json(EDITED_LAYOUT_PATH, _cl)
                st.session_state.setupDone  = True
                st.session_state.material   = mat_choice
                _sync_viewers()
                st.rerun()

    # ── Generate Grid + Options ───────────────────────────────────────────────
    st.markdown(
        f'<div style="margin:8px 0 6px;border-top:1px solid {_BORD}"></div>',
        unsafe_allow_html=True,
    )
    _gopts_sb  = st.session_state.grid_options
    _gate_off  = not st.session_state.get("setupDone", False)
    if st.button("⊕  Generate Grid", width="stretch",
                 type="primary", key="btn_gen_main", disabled=_gate_off):
        with st.spinner("Computing grid options…"):
            st.session_state.grid_options = _run_grid_options(layout_obj, _mat_now)
        for _gi, _gopt_g in enumerate(st.session_state.grid_options, 1):
            (REPO_ROOT / f"team_01_option_{_gi}.json").write_text(
                json.dumps(_gopt_g["layout"], indent=2, ensure_ascii=False),
                encoding="utf-8")
        # Auto-apply option 1 so structure is immediately available
        if st.session_state.grid_options:
            _auto_opt = st.session_state.grid_options[0].get("layout", {})
            if _auto_opt:
                _push_version(_auto_opt)
                st.session_state.diff_baseline = json.loads(json.dumps(_auto_opt))
        st.session_state["selected_opt_bar_idx"] = 0
        st.rerun()

    if _gopts_sb:
        for _bi, _gopt_sb in enumerate(_gopts_sb[:3]):
            _is_sel_sb = st.session_state.get("selected_opt_bar_idx", -1) == _bi
            _kpis = _grid_option_kpis(_gopt_sb.get("layout", {}))
            _desc  = _grid_option_description(_bi, _kpis)
            _bcard_bg  = f"background:{'rgba(42,192,192,0.10)' if _is_sel_sb else _CARD}"
            _bcard_brd = f"border:1px solid {_ACC if _is_sel_sb else _BORD}"
            st.markdown(
                f'<div style="{_bcard_bg};{_bcard_brd};border-radius:8px;'
                f'padding:8px 10px;margin-bottom:6px">'
                f'<div style="font-size:.63rem;font-weight:700;color:{"#2ac0c0" if _is_sel_sb else _TEXT};'
                f'margin-bottom:4px">Option {_bi+1}'
                f'{"  ✓ Active" if _is_sel_sb else ""}</div>'
                f'<div style="font-size:.60rem;color:{_MUT};line-height:1.55;margin-bottom:6px">{_desc}</div>'
                f'<div style="display:flex;gap:8px;flex-wrap:wrap">'
                f'<span style="font-size:.60rem;color:{_TEXT}">⬛ {_kpis["n_cols"]} col</span>'
                f'<span style="font-size:.60rem;color:{_TEXT}">— {_kpis["n_beams"]} beam</span>'
                f'<span style="font-size:.60rem;color:{_TEXT}">↔ max {_kpis["max_span"]}m</span>'
                f'<span style="font-size:.60rem;color:{_TEXT}">avg {_kpis["avg_span"]}m</span>'
                f'</div></div>',
                unsafe_allow_html=True,
            )
            if st.button(
                f"Apply Option {_bi+1}", key=f"sb_opt_{_bi}",
                width="stretch",
                type="primary" if _is_sel_sb else "secondary",
            ):
                _opt_layout = _gopt_sb.get("layout", {})
                _opt_ev = _gopt_sb.get("evaluation")
                if _opt_ev is None:
                    with st.spinner(f"Evaluating Option {_bi+1}…"):
                        _opt_ev = _run_evaluate(
                            json.dumps(_opt_layout),
                            sdl=_sdl_now, ll=_ll_now)
                    if _opt_ev:
                        st.session_state.grid_options[_bi]["evaluation"] = _opt_ev
                if _opt_layout:
                    _push_version(_opt_layout)
                    st.session_state.diff_baseline = json.loads(json.dumps(_opt_layout))
                st.session_state["selected_opt_bar_idx"] = _bi
                st.session_state.eval_result = _opt_ev
                st.session_state.eval_alts = _get_failure_alternatives(
                    _opt_ev or {}, _mat_now)
                st.rerun()

    # ── AI AGENT ──────────────────────────────────────────────────────────────
    st.markdown(
        f'<div style="border-top:1px solid {_BORD};margin:10px 0 6px"></div>'
        f'<div style="font-size:.76rem;font-weight:700;color:{_TEXT};margin-bottom:4px">'
        f'AI Agent <span class="beta">BETA</span></div>',
        unsafe_allow_html=True,
    )
    _history = st.session_state.get("history", [])
    if _history:
        _bub = ""
        for _msg in _history[-8:]:
            _q = _msg.get("prompt", "")
            _a = _msg.get("response", "")
            if _q:
                _bub += f'<div class="chat-q">{_q}</div>'
            if _a:
                _bub += f'<div class="chat-a">{_a}</div>'
        st.markdown(
            f'<div style="max-height:460px;overflow-y:auto;margin-bottom:8px">{_bub}</div>',
            unsafe_allow_html=True,
        )

    with st.form("agent_form", clear_on_submit=True):
        prompt_input = st.text_area(
            "Ask agent",
            placeholder="Ask anything about your structure…\ne.g. remove column C4 / explain beam B1 failure",
            label_visibility="collapsed",
            height=150,
        )
        submitted = st.form_submit_button("Ask Agent  ›", width="stretch")

    # ── AI Recommendations (shown in ANALYSIS tab) ────────────────────────────
    _alts_sb = st.session_state.eval_alts
    if _alts_sb:
        st.markdown(
            f'<div style="font-size:.63rem;color:{_MUT};margin-top:8px;line-height:1.6">'
            f'{len(_alts_sb)} recommendation{"s" if len(_alts_sb)>1 else ""} ready — '
            f'open the <b style="color:{_ACC}">Analysis</b> tab to preview or apply.</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div style="font-size:.63rem;color:{_MUT};margin-top:8px;line-height:1.5">'
            f'Generate a grid and run analysis to see AI recommendations.</div>',
            unsafe_allow_html=True,
        )

# ─── Agent processing ─────────────────────────────────────────────────────────
if submitted and prompt_input.strip():
    with st.spinner("Agent reasoning…"):
        _resp = _run_agent_chat(prompt_input.strip(), layout_obj, er)

    if _resp == "GENERATE_GRID" or _resp.startswith("GENERATE_GRID\n"):
        _gen_advisory = _resp[len("GENERATE_GRID"):].strip()
        with st.spinner("Generating structural grid options…"):
            st.session_state.grid_options = _run_grid_options(layout_obj, _mat_now)
        for _gi, _gopt in enumerate(st.session_state.grid_options, 1):
            (REPO_ROOT / f"team_01_option_{_gi}.json").write_text(
                json.dumps(_gopt["layout"], indent=2, ensure_ascii=False), encoding="utf-8")
        # Auto-apply option 1 to the working layout
        if st.session_state.grid_options:
            _ag_opt = st.session_state.grid_options[0].get("layout", {})
            if _ag_opt:
                _push_version(_ag_opt)
                st.session_state.diff_baseline = json.loads(json.dumps(_ag_opt))
                st.session_state["selected_opt_bar_idx"] = 0
        _resp = (f"{_gen_advisory}\n\n" if _gen_advisory else "") + f"Generated {len(st.session_state.grid_options)} grid option(s). Option 1 applied."
    elif _resp.startswith("APPLY_TOOL:"):
        try:
            _td = json.loads(_resp[len("APPLY_TOOL:"):])
            _tn, _ti = _td.get("name", ""), _td.get("input", {})
            _advisory_txt = _td.get("advisory", "")
            if _tn == "remove_element":
                from nodes.modify import remove_element as _rem_el
                _eid = _ti.get("element_id", "")
                _frc = bool(_ti.get("force"))
                if _eid:
                    _new_l = json.loads(_rem_el(json.dumps(layout_obj), _eid, _frc))
                    if find_element_in_layout(_new_l, _eid)[1] is not None:
                        # removal was blocked (perimeter / envelope lock)
                        _resp = (f"{_advisory_txt}\n\n" if _advisory_txt else "") + (
                            f"**{_eid}** is a perimeter element that defines the building "
                            f"envelope, so I left it in place — removing it risks the structure. "
                            f"Say **force remove {_eid}** if you want me to delete it anyway.")
                    else:
                        _push_version(_new_l)
                        _resp = (f"{_advisory_txt}\n\n" if _advisory_txt else "") + f"Removed **{_eid}** from the layout."
            elif _tn == "add_midspan_column":
                from nodes.modify import add_midspan_column as _amc
                _bid = _ti.get("beam_id", "") or _ti.get("element_id", "")
                if _bid:
                    _push_version(json.loads(_amc(json.dumps(layout_obj), _bid, _mat_now)))
                    _resp = (f"{_advisory_txt}\n\n" if _advisory_txt else "") + f"Added midspan column to **{_bid}**."
            elif _tn == "upgrade_element_section":
                from nodes.modify import upgrade_element_section as _ups
                _uid = _ti.get("element_id", "")
                _usec = _ti.get("new_section", "") or _ti.get("value", "")
                if _uid:
                    _push_version(json.loads(_ups(json.dumps(layout_obj), _uid, _usec)))
                    _resp = (f"{_advisory_txt}\n\n" if _advisory_txt else "") + f"Upgraded section of **{_uid}**."
        except Exception as _tex:
            _resp = f"Tool execution failed: {_tex}"
            st.session_state["_last_error"] = f"APPLY_TOOL: {_tex}"
    elif _resp.startswith("APPLY_MATERIAL:"):
        _mparts = _resp[len("APPLY_MATERIAL:"):].split("|")
        _new_mat = (_mparts[0].strip() or _mat_now).upper()
        _m_lvl = _mparts[1].strip() if len(_mparts) > 1 else ""
        _m_et  = _mparts[2].strip() if len(_mparts) > 2 else ""
        try:
            from nodes.modify import apply_material_override
            _ls_m = apply_material_override(json.dumps(layout_obj), _new_mat,
                                            level=_m_lvl or None, element_type=_m_et or None)
            _push_version(json.loads(_ls_m))
            with st.spinner(f"Applying {_new_mat} and evaluating…"):
                _ev_m = _run_evaluate(_ls_m, sdl=_sdl_now, ll=_ll_now)
            if _ev_m:
                st.session_state.eval_result = _ev_m
                st.session_state.eval_alts   = _get_failure_alternatives(_ev_m, _new_mat)
            _sm_m = (_ev_m or {}).get("summary", {})
            _scope = (f" ({_m_et or 'all'} elements"
                      + (f" of {_m_lvl}" if _m_lvl else "") + ")") if (_m_lvl or _m_et) else " (whole structure)"
            _resp = (f"Switched **{_new_mat}**{_scope}. "
                     f"Result: {'PASS' if _sm_m.get('overall_PASS') else 'FAIL'} — "
                     f"{_sm_m.get('beam_failures', 0)} beam / {_sm_m.get('column_failures', 0)} column failures. "
                     f"Ask me to *fix the failing beams* if you'd like options.")
        except Exception as _mex:
            _resp = f"Material switch failed: {_mex}"
            st.session_state["_last_error"] = f"APPLY_MATERIAL: {_mex}"
    elif _resp == "FIX_FAILING":
        try:
            _ev_fix = st.session_state.eval_result or _run_evaluate(
                json.dumps(layout_obj), sdl=_sdl_now, ll=_ll_now)
            _alts_fix = _get_failure_alternatives(_ev_fix or {}, _mat_now)
            _auto_alt = next((a for a in _alts_fix
                              if "increase the" in a.lower() or "upgrade" in a.lower()),
                             (_alts_fix[0] if _alts_fix else None))
            if _auto_alt:
                _nl, _nev = _apply_alternative(_auto_alt, json.dumps(layout_obj),
                                               _mat_now, _sdl_now, _ll_now)
                if _nev:
                    _push_version(json.loads(_nl))
                    st.session_state.eval_result = _nev
                    st.session_state.eval_alts = _get_failure_alternatives(_nev, _mat_now)
                    _ns = _nev.get("summary", {})
                    _resp = (f"Applied an automatic fix. Now "
                             f"{'PASS' if _ns.get('overall_PASS') else 'FAIL'} — "
                             f"{_ns.get('beam_failures', 0)} beam / {_ns.get('column_failures', 0)} column failures.")
                else:
                    _resp = "Tried to auto-fix but evaluation did not return — try upgrading sections manually."
            else:
                _resp = "Nothing to fix — run analysis first, or there are no failing elements."
        except Exception as _fex:
            _resp = f"Auto-fix failed: {_fex}"
            st.session_state["_last_error"] = f"FIX_FAILING: {_fex}"
    elif _resp == "EVALUATE":
        # Evaluate as-is; only seed the global material when nothing is assigned yet
        # (never revert an applied timber/steel change).
        _any_mat_ag = any((e.get("attributes") or {}).get("material")
                          for _l, e in iter_all_structure(layout_obj))
        if _any_mat_ag:
            _ls_ag = json.dumps(layout_obj)
        else:
            from nodes.modify import apply_material_override
            _ls_ag = apply_material_override(json.dumps(layout_obj), _mat_now)
            _push_version(json.loads(_ls_ag))
        with st.spinner("Evaluating structure…"):
            _ev_ag = _run_evaluate(_ls_ag, sdl=_sdl_now, ll=_ll_now)
        if _ev_ag:
            st.session_state.eval_result = _ev_ag
            st.session_state.eval_alts   = _get_failure_alternatives(_ev_ag, _mat_now)
        _sag  = (_ev_ag or {}).get("summary", {})
        _resp = (
            f"Evaluation: {'PASS' if _sag.get('overall_PASS') else 'FAIL'} — "
            f"{_sag.get('beam_failures',0)} beam failure(s), "
            f"{_sag.get('column_failures',0)} column failure(s)."
        )

    st.session_state.output_log.append(_resp)
    st.session_state.history.append({"prompt": prompt_input, "response": _resp})
    st.session_state.state_history.append({
        "label":       prompt_input[:28] + ("…" if len(prompt_input) > 28 else ""),
        "layout_json": layout_obj,
        "eval_result": st.session_state.eval_result,
    })
    st.rerun()

# ─── Page header ──────────────────────────────────────────────────────────────
_cf_h  = st.session_state.get("cost_flexibility")
_hcols = st.columns([4.2, 0.9, 1.0, 1.15, 0.35], gap="small")

with _hcols[0]:
    _rev_chip  = ('<span class="stat-chip needs-review">⚠ Review</span>'
                  if _has_fail else "")
    _cost_chip = (f'<span class="stat-chip">net <b>${_cf_h["net_cost_usd"]:+,.0f}</b></span>'
                  if _cf_h else "")
    st.markdown(
        f'<div class="page-hdr">'
        f'<span class="hdr-lid">{_lid}</span>'
        f'<span class="stat-chip"><b>{n_cols}</b> col</span>'
        f'<span class="stat-chip"><b>{n_beams}</b> beam</span>'
        f'<span class="stat-chip"><b>{_mat_now}</b></span>'
        f'{_cost_chip}{_rev_chip}</div>',
        unsafe_allow_html=True,
    )
with _hcols[1]:
    if st.button("Light" if not _is_light else "Dark",
                 width="stretch", key="btn_theme"):
        st.session_state.theme        = "light" if not _is_light else "dark"
        st.session_state.viewer_nonce += 1
        st.rerun()
with _hcols[2]:
    st.download_button(
        "Export JSON",
        data=json.dumps(layout_obj, indent=2, ensure_ascii=False),
        file_name="layout_export.json",
        mime="application/json",
        width="stretch",
    )
with _hcols[3]:
    _revs = tuple(
        (h.get("prompt") or h.get("label") or "")
        for h in st.session_state.get("history", [])[-7:]
    )
    # Single export entry point — pick which design + whether to show labels.
    _export_choices: dict[str, tuple[str, str]] = {
        "Current design": (json.dumps(layout_obj), json.dumps(er) if er else "")
    }
    for _gi_x, _go_x in enumerate(st.session_state.get("grid_options", []), 1):
        _ev_x = _go_x.get("evaluation")
        _export_choices[f"Grid Option {_gi_x}"] = (
            json.dumps(_go_x.get("layout", {})), json.dumps(_ev_x) if _ev_x else "")
    for _sn_x in st.session_state.get("snapshots", []):
        _ev_x = _sn_x.get("eval_result")
        _export_choices[_sn_x["label"]] = (
            _sn_x["layout_json"], json.dumps(_ev_x) if _ev_x else "")

    with st.popover("⤓ Export", width="stretch"):
        _exp_sel = st.selectbox("Design to export", list(_export_choices.keys()),
                                key="exp_design_sel")
        _exp_lbl = st.checkbox("Show element labels", value=True, key="exp_show_labels")
        _exp_lj, _exp_ej = _export_choices.get(_exp_sel, (json.dumps(layout_obj), ""))
        try:
            _exp_data = _sheet_pdf_bytes(_exp_lj, _exp_ej, str(_lid), str(_mat_now),
                                         _revs, _exp_lbl, "")
            st.download_button(
                "⤓ Download sheet (PDF)", data=_exp_data,
                file_name=f"{_lid}_{_exp_sel.replace(' ', '_')}.pdf",
                mime="application/pdf", width="stretch", key="exp_dl_btn",
            )
        except Exception as _ee:
            st.caption(f"Export failed: {_ee}")
with _hcols[4]:
    with st.popover("⋮", width="stretch"):
        st.markdown(
            f'<div style="font-size:.72rem;font-weight:700;color:#c8eeed;'
            f'margin-bottom:6px">PermanenceOS</div>'
            f'<div style="font-size:.65rem;color:#5a9090">AI Structural Design</div>',
            unsafe_allow_html=True,
        )
        st.divider()
        if st.button("Rerun", key="btn_menu_rerun", width="stretch"):
            st.rerun()
        _theme_lbl = "Switch to Light" if not _is_light else "Switch to Dark"
        if st.button(_theme_lbl, key="btn_menu_theme", width="stretch"):
            st.session_state.theme        = "light" if not _is_light else "dark"
            st.session_state.viewer_nonce += 1
            st.rerun()
        st.toggle("🐞 Debug mode", key="debug_mode",
                  help="Show diagnostics and full error tracebacks for fast problem-finding.")
        with st.expander("Diagnostics", expanded=bool(st.session_state.get("debug_mode"))):
            _diag_cols, _diag_beams = _count_elements(layout_obj)
            _diag_mats = ", ".join(l for _c, l in _materials_present(layout_obj)) or "none"
            _diag_sm = (er or {}).get("summary", {})
            _diag_err = st.session_state.get("_last_error", "")
            st.markdown(
                f"<div style='font-size:.66rem;line-height:1.7;font-family:monospace'>"
                f"version: <b>{st.session_state.get('currentVersion', 0)}</b><br>"
                f"multilevel: <b>{is_multilevel(layout_obj)}</b> · levels: <b>{get_level_count(layout_obj)}</b><br>"
                f"columns: <b>{_diag_cols}</b> · beams: <b>{_diag_beams}</b><br>"
                f"materials: <b>{_diag_mats}</b><br>"
                f"eval: <b>{'PASS' if _diag_sm.get('overall_PASS') else ('FAIL' if er else '—')}</b> "
                f"({_diag_sm.get('beam_failures', 0)}B / {_diag_sm.get('column_failures', 0)}C fail)<br>"
                f"selected: <b>{st.session_state.get('selected_el') or '—'}</b><br>"
                f"diff baseline set: <b>{st.session_state.get('diff_baseline') is not None}</b><br>"
                f"LLM reachable: <b>{_llm_is_reachable()}</b>"
                f"</div>",
                unsafe_allow_html=True,
            )
            if _diag_err:
                st.error(_diag_err)
            if st.button("Clear last error", key="btn_clear_err", width="stretch"):
                st.session_state["_last_error"] = ""
                st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# EMPTY STATE GATE — nothing renders until upload + OK
# ══════════════════════════════════════════════════════════════════════════════
if not st.session_state.get("setupDone", False):
    st.markdown(
        f'<div style="display:flex;flex-direction:column;align-items:center;'
        f'justify-content:center;min-height:60vh;gap:16px;text-align:center">'
        f'<div style="font-size:2.5rem;opacity:.25">⬡</div>'
        f'<div style="font-size:1.1rem;font-weight:700;color:{_TEXT}">'
        f'No model loaded</div>'
        f'<div style="font-size:.82rem;color:{_MUT};max-width:320px;line-height:1.6">'
        f'Upload a JSON layout file in the sidebar, configure your loads and material, '
        f'then press <b>OK ▶ Apply & Render</b> to begin.</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.stop()

# ══════════════════════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════════════════════
tab_mod, tab_cmp = st.tabs(["  MODIFY WORK PLACE  ", "  COMPARE WORK PLACE  "])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — MODIFY
# ══════════════════════════════════════════════════════════════════════════════
with tab_mod:

    _er_done = er is not None
    _alts_ok = bool(st.session_state.eval_alts)
    _snap_ok = bool(st.session_state.snapshots)

    _steps = [
        ("1", "Upload",          "Model & Data",      True),
        ("2", "Define Loads",    "Set load cases",    True),
        ("3", "Evaluate",        "Run analysis",      _er_done),
        ("4", "Recommendations", "AI suggestions",    _alts_ok),
        ("5", "Apply Changes",   "Modify design",     _snap_ok),
        ("6", "Compare",         "Evaluate options",  False),
    ]
    _sbar_html = '<div class="step-bar">'
    for _si, (_sn, _sl, _ss, _sdone) in enumerate(_steps):
        _cls = "stp-done" if _sdone else (
            "stp-active" if (_si == 2 and not _er_done) else "stp-todo")
        _sbar_html += (
            f'<div class="stp {_cls}">'
            f'<span class="stp-n">{_sn}</span>'
            f'<div><div class="stp-lbl">{_sl}</div>'
            f'<div class="stp-sub">{_ss}</div></div></div>'
        )
        if _si < len(_steps) - 1:
            _sbar_html += '<span class="stp-arr">›</span>'
    _sbar_html += '</div>'

    # Step bar in main area; Run Analysis + Save Snapshot aligned to right panel.
    # Proportions match the main/right column split below (2.1 : 0.55).
    _sb_col, _btn_area = st.columns([2.1, 0.55], gap="small")
    with _sb_col:
        st.markdown(_sbar_html, unsafe_allow_html=True)
    with _btn_area:
        _run_col, _snap_col = st.columns([1, 1], gap="small")
        with _run_col:
            _run_clicked = st.button(
                "▶  Run Analysis",
                type="primary", width="stretch", key="btn_run_analysis",
                disabled=not st.session_state.get("setupDone", False),
            )
        with _snap_col:
            _sn_n = len(st.session_state.snapshots) + 1
            _snap_clicked = st.button(
                f"Snapshot #{_sn_n}", key="btn_snap", width="stretch",
            )

    if _snap_clicked:
        st.session_state.snapshots.append({
            "label":            f"Option {_sn_n}",
            "layout_json":      json.dumps(layout_obj),
            "eval_result":      er,
            "cost_flexibility": st.session_state.cost_flexibility,
            "before_json":      json.dumps(
                                    st.session_state.versionHistory[-1]
                                    if st.session_state.get("versionHistory")
                                    else layout_obj
                                ),
        })
        st.rerun()

    if _run_clicked:
        _struct_els = get_structure(layout_obj)
        if not _struct_els:
            st.warning(
                "No structural elements found. "
                "Generate a structural grid first using the Agent or the Generate Grid button.",
                icon="⚠️",
            )
        else:
            # Remember which option is active BEFORE any _push_version (which resets it),
            # so Run Analysis keeps the user's chosen option active (e.g. Option 3).
            _oi_keep = st.session_state.get("selected_opt_bar_idx", -1)
            # Only seed the global material when NO element has a material yet
            # (fresh grid). If timber/steel/etc. was already applied, evaluate the
            # layout AS-IS so Run Analysis never reverts an applied material change.
            _any_mat = any((e.get("attributes") or {}).get("material")
                           for _l, e in iter_all_structure(layout_obj))
            if _any_mat:
                _ls2 = json.dumps(layout_obj)
            else:
                from nodes.modify import apply_material_override
                _ls2 = apply_material_override(json.dumps(layout_obj), _mat_now)
                _push_version(json.loads(_ls2))
            with st.spinner("Evaluating structure…"):
                _ev2 = _run_evaluate(_ls2, sdl=_sdl_now, ll=_ll_now)
            if _ev2:
                st.session_state.eval_result = _ev2
                st.session_state.eval_alts   = _get_failure_alternatives(_ev2, _mat_now)
                # Attach the evaluation to the option that was active before analysis,
                # and keep that option active (don't snap back to Option 1).
                _gopts_run = st.session_state.grid_options
                if 0 <= _oi_keep < len(_gopts_run):
                    st.session_state.grid_options[_oi_keep]["evaluation"] = _ev2
                    st.session_state["selected_opt_bar_idx"] = _oi_keep
                elif _gopts_run:
                    st.session_state.grid_options[0]["evaluation"] = _ev2
                    st.session_state["selected_opt_bar_idx"] = 0
                _ev2_sm = _ev2.get("summary", {})
                _ev2_pass = _ev2_sm.get("overall_PASS")
                _ev2_bf   = _ev2_sm.get("beam_failures", 0)
                _ev2_cf   = _ev2_sm.get("column_failures", 0)
                _ev2_sc   = _ev2_sm.get("score")
                _ev2_icon = "✅" if _ev2_pass else "❌"
                _ev2_lbl  = "PASS" if _ev2_pass else "FAIL"
                st.markdown(
                    f'<div style="background:{"rgba(40,180,100,0.12)" if _ev2_pass else "rgba(200,40,40,0.12)"};'
                    f'border:1px solid {"#40d090" if _ev2_pass else "#ff5050"};'
                    f'border-radius:8px;padding:10px 14px;margin:6px 0;font-family:{_F}">'
                    f'<span style="font-size:1.1rem;font-weight:800;color:{"#40d090" if _ev2_pass else "#ff5050"}">'
                    f'{_ev2_icon} {_ev2_lbl}</span>'
                    f'<span style="font-size:.75rem;color:{_MUT};margin-left:10px">'
                    f'{_ev2_bf} beam fail · {_ev2_cf} col fail'
                    f'{f" · score {_ev2_sc:.0f}/100" if _ev2_sc is not None else ""}'
                    f'</span></div>',
                    unsafe_allow_html=True,
                )
            st.rerun()

    # ── Toolbar + viewer ─────────────────────────────────────────────────────
    _vm = st.session_state.get("view_mode", "2D")

    _snaps = st.session_state.snapshots
    if _snaps:
        _pills = "".join(
            f'<span class="snap-pill{" snap-pill-active" if i==len(_snaps)-1 else ""}">'
            f'{s["label"]}</span>'
            for i, s in enumerate(_snaps)
        )
        st.markdown(_pills, unsafe_allow_html=True)

    # currentLayout is always authoritative — _push_version keeps it in sync
    # with EDITED_LAYOUT_PATH, so both viewers always read the same data.
    _plan_layout = layout_obj

    # ── Preview (non-committal) — render a recommendation's result without saving ─
    _preview_active = False
    _preview_alt = st.session_state.get("preview_alt")
    if _preview_alt:
        try:
            _pv_ls, _pv_ev = _apply_alternative(
                _preview_alt, json.dumps(layout_obj), _mat_now, _sdl_now, _ll_now,
            )
            _plan_layout = json.loads(_pv_ls)
            if _pv_ev:
                er = _pv_ev
            _preview_active = True
        except Exception:
            st.session_state["preview_alt"] = None

    # ── Main: floor plan | right panel ───────────────────────────────────────
    _main_col, _right_col = st.columns([2.1, 0.55], gap="small")

    with _main_col:
        if _preview_active:
            _pvb1, _pvb2, _pvb3 = st.columns([3, 1, 1], gap="small")
            with _pvb1:
                st.markdown(
                    f'<div style="background:{_MED_BG};color:{_MED_C};border:1px solid {_MED_C};'
                    f'border-radius:6px;padding:6px 10px;font-size:.68rem;font-weight:700">'
                    f'👁 Previewing a recommendation — not applied yet.</div>',
                    unsafe_allow_html=True,
                )
            with _pvb2:
                if st.button("✓ Apply", key="preview_apply", type="primary", width="stretch"):
                    _push_version(_plan_layout)
                    st.session_state.eval_result = er
                    st.session_state.eval_alts = _get_failure_alternatives(er or {}, _mat_now)
                    st.session_state["preview_alt"] = None
                    st.rerun()
            with _pvb3:
                if st.button("✕ Cancel", key="preview_cancel", width="stretch"):
                    st.session_state["preview_alt"] = None
                    st.rerun()
        # Native toolbar (replaces the in-iframe JS bridge toolbar)
        _is_ml = is_multilevel(_plan_layout)
        _tb_cols = [0.55, 1.1, 0.7, 0.6, 4.0] if _is_ml else [0.55, 0.7, 0.6, 4.6]
        _tb = st.columns(_tb_cols, gap="small")
        _tb1 = _tb[0]
        _tb_lvl = _tb[1] if _is_ml else None
        _tb2 = _tb[2] if _is_ml else _tb[1]
        _tb3 = _tb[3] if _is_ml else _tb[2]
        with _tb1:
            if st.button("3D" if _vm == "2D" else "2D",
                         key="tb_vm_btn", width="stretch"):
                st.session_state["view_mode"] = "3D" if _vm == "2D" else "2D"
                st.rerun()
        if _is_ml and _tb_lvl is not None:
            with _tb_lvl:
                _lvl_keys = get_level_keys(_plan_layout)
                _lvl_opts = _lvl_keys + ["All levels"]
                _cur_lvl = ("All levels" if st.session_state.active_level == "__ALL__"
                            else st.session_state.active_level)
                _lvl_idx = _lvl_opts.index(_cur_lvl) if _cur_lvl in _lvl_opts else 0
                _new_level = st.selectbox(
                    "Level",
                    _lvl_opts,
                    index=_lvl_idx,
                    format_func=lambda x: ("Show all levels" if x == "All levels" else x),
                    label_visibility="collapsed",
                    key="tb_active_level",
                )
                _new_level = "__ALL__" if _new_level == "All levels" else _new_level
                if _new_level != st.session_state.active_level:
                    st.session_state.active_level = _new_level
        with _tb2:
            _new_lab = st.toggle("Labels", value=st.session_state.labels_on,
                                 key="tb_lab_tog")
            if _new_lab != st.session_state.labels_on:
                st.session_state.labels_on = _new_lab
        with _tb3:
            _new_diff = st.toggle("Diff", value=st.session_state.compare_mode,
                                  key="tb_diff_tog")
            if _new_diff != st.session_state.compare_mode:
                st.session_state.compare_mode = _new_diff

        # If the active level has no structure yet, say so (explains "switching level
        # shows nothing" before a grid is generated on that level).
        _al_now = st.session_state.active_level
        if _al_now != "__ALL__" and not get_structure(_plan_layout, _al_now):
            st.markdown(
                f'<div style="font-size:.62rem;color:{_MUT};margin:2px 0 4px">'
                f'<b>{_al_now}</b> has no structural elements yet — generate a grid to populate it.</div>',
                unsafe_allow_html=True,
            )

        # Diff compares the live layout against the baseline (the applied grid/option),
        # so it shows everything you've changed since — not just the last edit.
        _before_lay = (st.session_state.get("diff_baseline")
                       if st.session_state.compare_mode else None)
        if st.session_state.compare_mode:
            if _before_lay:
                _da, _dr, _dm = (("#1a8050", "#cc2020", "#7c4dff") if _is_light
                                 else ("#40d090", "#ff5050", "#9b7cff"))
                st.markdown(
                    f'<div style="display:flex;gap:14px;align-items:center;margin:2px 0 6px;'
                    f'font-size:.60rem;color:{_MUT}">'
                    f'<span style="font-weight:700;text-transform:uppercase;letter-spacing:.5px">vs Baseline grid</span>'
                    f'<span style="display:flex;align-items:center;gap:4px"><span style="width:10px;height:10px;border-radius:2px;background:{_da};display:inline-block"></span>Added</span>'
                    f'<span style="display:flex;align-items:center;gap:4px"><span style="width:10px;height:10px;border-radius:2px;background:{_dr};display:inline-block"></span>Removed</span>'
                    f'<span style="display:flex;align-items:center;gap:4px"><span style="width:10px;height:10px;border-radius:2px;background:{_dm};display:inline-block"></span>Changed</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div style="font-size:.60rem;color:{_MUT};margin:2px 0 6px">'
                    f'Diff on — generate or apply a grid first to set the baseline.</div>',
                    unsafe_allow_html=True,
                )
        if _vm == "2D":
            _fig2d = _render_floor_plan_plotly(
                _plan_layout, eval_result=er,
                highlight=st.session_state.selected_el,
                level_key=st.session_state.active_level,
                labels=st.session_state.labels_on,
                height_px=510, is_light=_is_light,
                diff_on=st.session_state.compare_mode,
                before_layout=_before_lay,
                revision=st.session_state.get("currentVersion", 0),
            )
            _sel_ev = st.plotly_chart(
                _fig2d, on_select="rerun",
                width="stretch",
                selection_mode=("points",),
                config=dict(
                    scrollZoom=True, displaylogo=False,
                    modeBarButtonsToRemove=["lasso2d", "select2d",
                                            "zoomIn2d", "zoomOut2d",
                                            "autoScale2d"],
                ),
                key="floor_plan_plotly",
            )
            # Handle element selection from click.
            # Streamlit's on_select returns dict-like point objects.
            if _sel_ev and _sel_ev.selection and _sel_ev.selection.points:
                try:
                    _new_sel = ""
                    _lvl_changed = False
                    _cand_dbg = []
                    for _pt in _sel_ev.selection.points:
                        # Support both attribute-style and dict-style access.
                        _cd = (
                            _pt.get("customdata") if isinstance(_pt, dict)
                            else getattr(_pt, "customdata", None)
                        )
                        if not _cd:
                            continue
                        if isinstance(_cd, (list, tuple)):
                            _cand = str(_cd[0]) if _cd else ""
                            _kind = str(_cd[1]).lower() if len(_cd) > 1 else ""
                            _lvl = str(_cd[2]) if len(_cd) > 2 else ""
                            _cand_dbg.append(
                                f"id={_cand or '-'} kind={_kind or '-'} lvl={_lvl or '-'}"
                            )
                            if _cand and (_kind in ("beam", "column") or not _kind):
                                _new_sel = _cand
                                if _lvl and _lvl != st.session_state.get("active_element_level", ""):
                                    _lvl_changed = True
                                if _lvl:
                                    st.session_state.active_element_level = _lvl
                                    st.session_state.active_level = _lvl
                                    st.session_state["_last_lvl_applied"] = _lvl
                                break
                        else:
                            _cand_dbg.append(f"id={str(_cd)} kind=-")
                            _new_sel = str(_cd)
                            break
                    st.session_state["last_click_debug"] = {
                        "selected_id": _new_sel,
                        "points_count": len(_sel_ev.selection.points),
                        "candidates": _cand_dbg,
                        "raw_first_point": (
                            _sel_ev.selection.points[0]
                            if _sel_ev.selection.points else None
                        ),
                    }
                    if _new_sel and (
                        _new_sel != st.session_state.selected_el
                        or _lvl_changed
                    ):
                        st.session_state.selected_el = _new_sel
                        st.session_state["_last_sel_applied"] = _new_sel
                        st.rerun()
                except Exception:
                    pass
        else:
            components.html(
                _render_3d_viewport(
                    _plan_layout,
                    eval_result=er,
                    selected_el=st.session_state.selected_el,
                    active_level=st.session_state.active_level,
                    is_light=_is_light,
                    height=512,
                    before_layout=_before_lay,
                    labels=st.session_state.labels_on,
                ),
                height=520,
                scrolling=False,
            )

        st.markdown(
            '<div class="plan-legend">'
            '<span class="leg-item"><span class="leg-col"></span>Columns</span>'
            '<span class="leg-item"><span class="leg-beam"></span>Beams</span>'
            '<span class="leg-item"><span class="leg-wall"></span>Walls</span>'
            '<span class="leg-item"><span class="leg-dash"></span>Load Path</span>'
            '</div>',
            unsafe_allow_html=True,
        )
        _mat_leg = _material_legend_html(_plan_layout, _is_light, _MUT)
        if _mat_leg:
            st.markdown(_mat_leg, unsafe_allow_html=True)

        _mdef  = _sm.get("max_defl_mm", None)
        _tw    = _sm.get("total_weight_kN", None)
        _bf_sb = _sm.get("beam_failures", 0)
        _cf_sb = _sm.get("column_failures", 0)
        if er and _sm.get("overall_PASS"):
            _anlys = '<span class="sb-pass">✓ Analysis Complete</span>'
        elif er:
            _anlys = '<span class="sb-fail">✗ Analysis Failed</span>'
        else:
            _anlys = '<span class="sb-pend">Not analysed</span>'

        st.markdown(
            f'<div class="stat-bar">'
            f'<span class="sb-i">Nodes <b>{n_cols}</b></span>'
            f'<span class="sb-i">Beams <b>{n_beams}</b></span>'
            f'<span class="sb-i">Columns <b>{n_cols}</b></span>'
            + (f'<span class="sb-i">Weight <b>{_tw:.1f}</b> kN</span>' if _tw else "")
            + (f'<span class="sb-i">Max Defl <b>{_mdef:.1f}</b> mm</span>' if _mdef else "")
            + f'<span class="sb-i">Beam fail <b>{_bf_sb}</b></span>'
            f'<span class="sb-i">Col fail <b>{_cf_sb}</b></span>'
            f'{_anlys}</div>',
            unsafe_allow_html=True,
        )

    with _right_col:
        _rt1, _rt2 = st.tabs(["  ANALYSIS  ", "  DESIGN DETAILS  "])

        with _rt1:
            # Transparency: after an auto-upgrade fix, show exactly what was resized.
            _fix_log = st.session_state.get("_last_fix_log")
            if _fix_log:
                _fix_rows = "".join(
                    f'<div style="font-size:.62rem;color:{_TEXT};line-height:1.6">'
                    f'<b>{r["id"]}</b> ({r["kind"]}): {r["from"]} → <b>{r["to"]}</b>'
                    f' <span style="color:{_MUT}">· governed by {r["gov"]}</span></div>'
                    for r in _fix_log[:30]
                )
                st.markdown(
                    f'<div style="background:{_PASS_BG};border:1px solid {_PASS_C};border-radius:8px;'
                    f'padding:8px 10px;margin-bottom:8px">'
                    f'<div style="font-size:.64rem;font-weight:700;color:{_PASS_C};margin-bottom:4px">'
                    f'✓ Auto-upgrade applied — {len(_fix_log)} element(s) resized to the next passing section</div>'
                    f'{_fix_rows}</div>',
                    unsafe_allow_html=True,
                )
                st.session_state["_last_fix_log"] = None

            _sel_opt_i2 = st.session_state.get("selected_opt_bar_idx", -1)
            _gopts_main = st.session_state.grid_options

            if not _gopts_main:
                st.markdown(
                    f'<div style="font-size:.70rem;color:{_MUT};padding:8px 2px;line-height:1.6">'
                    f'Click <b>Generate Grid</b> in the sidebar, then select an option '
                    f'to view structural analysis.</div>',
                    unsafe_allow_html=True,
                )
            elif _sel_opt_i2 < 0:
                st.markdown(
                    f'<div style="font-size:.70rem;color:{_MUT};padding:8px 2px;line-height:1.6">'
                    f'Select <b>Option 1</b>, <b>2</b> or <b>3</b> in the sidebar '
                    f'to view its structural analysis here.</div>',
                    unsafe_allow_html=True,
                )
            else:
                _sel_gopt = _gopts_main[_sel_opt_i2]
                _sel_ev   = _sel_gopt.get("evaluation") or {}
                _sel_sm   = _sel_ev.get("summary", {})
                _sel_pass = _sel_sm.get("overall_PASS")

                if not _sel_ev:
                    st.markdown(
                        f'<div style="font-size:.70rem;color:{_MUT}">No analysis data yet.</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    _is_pass  = _sel_pass is True
                    _is_fail  = _sel_pass is False
                    _res_clr  = _PASS_C if _is_pass else (_FAIL if _is_fail else _MUT)
                    _res_lbl  = "PASS" if _is_pass else ("FAIL" if _is_fail else "—")
                    _bf       = _sel_sm.get("beam_failures",   0)
                    _cf2      = _sel_sm.get("column_failures", 0)
                    _score    = _sel_sm.get("score",           None)
                    _mspan    = _sel_sm.get("max_beam_span_m", None)

                    def _stat(val, label):
                        return (
                            f'<div style="display:flex;flex-direction:column;gap:2px">'
                            f'<span style="font-size:1.5rem;font-weight:800;color:{_TEXT};line-height:1">{val}</span>'
                            f'<span style="font-size:.58rem;font-weight:700;color:{_MUT};'
                            f'letter-spacing:1px;text-transform:uppercase">{label}</span>'
                            f'</div>'
                        )

                    _score_html = _stat(f"{_score:.1f}" if _score is not None else "—", "Score / 100")
                    _mspan_html = (
                        f'<div style="font-size:.63rem;color:{_MUT};margin-top:6px">'
                        f'Max beam span: <b style="color:{_TEXT}">{_mspan:.2f} m</b></div>'
                        if _mspan else ""
                    )
                    st.markdown(
                        f'<div style="background:{_CARD};border:1px solid {_BORD};'
                        f'border-radius:10px;padding:16px 18px;margin:4px 0">'
                        f'<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px">'
                        f'<div style="display:flex;flex-direction:column;gap:2px">'
                        f'<span style="font-size:1.7rem;font-weight:900;color:{_res_clr};line-height:1">{_res_lbl}</span>'
                        f'<span style="font-size:.58rem;font-weight:700;color:{_MUT};letter-spacing:1px;text-transform:uppercase">Overall</span>'
                        f'</div>'
                        f'{_score_html}'
                        f'</div>'
                        f'<div style="display:flex;justify-content:space-between;align-items:flex-start">'
                        f'{_stat(_bf, "Beam Failures")}'
                        f'{_stat(_cf2, "Column Failures")}'
                        f'</div>'
                        f'{_mspan_html}'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

                    # ── AI Recommendations ────────────────────────────────────────────
                    _alts_tab = st.session_state.eval_alts
                    if _alts_tab:
                        st.markdown(
                            f'<div class="panel-hdr" style="margin-top:16px;margin-bottom:6px">'
                            f'AI Recommendations</div>',
                            unsafe_allow_html=True,
                        )
                        # Cache metrics so re-runs don't re-evaluate 3x every time
                        _mck = tuple(_alts_tab[:3])
                        if st.session_state.get("_alt_mck") != _mck:
                            st.session_state["_alt_mck"] = _mck
                            st.session_state["_alt_mcache"] = [
                                _compute_alt_metrics(
                                    _a, layout_obj, er or {},
                                    _mat_now, _sdl_now, _ll_now,
                                )
                                for _a in _alts_tab[:3]
                            ]
                        _mcache = st.session_state.get("_alt_mcache", [])

                        def _metric_col(pct, label):
                            if pct is None:
                                clr, arrow, val = _MUT, "", "—"
                            else:
                                arrow = "↓" if pct < 0 else "↑"
                                clr   = _PASS_C if pct < 0 else _FAIL
                                val   = f"{abs(pct):.2f}%"
                            return (
                                f'<div style="flex:1;text-align:center">'
                                f'<div style="font-size:.58rem;color:{_MUT};'
                                f'font-weight:600;text-transform:uppercase;'
                                f'letter-spacing:.5px;margin-bottom:3px">{label}</div>'
                                f'<div style="font-size:.70rem;font-weight:700;'
                                f'color:{clr}">{arrow} {val}</div>'
                                f'</div>'
                            )

                        for _ri, _alt in enumerate(_alts_tab[:3]):
                            _nc = [_NUM1_BG, _NUM2_BG, _NUM3_BG][min(_ri, 2)]
                            _alt_lo = _alt.lower()
                            if ("recommended" in _alt_lo
                                    or _alt_lo.startswith("increase the")):
                                _icss, _ilbl = "imp-high", "HIGH IMPACT"
                            elif "upgrade all" in _alt_lo or "switch all" in _alt_lo:
                                _icss, _ilbl = "imp-high", "HIGH IMPACT"
                            elif ("add midspan" in _alt_lo or "add lateral" in _alt_lo
                                  or "add transfer" in _alt_lo
                                  or "add intermediate" in _alt_lo):
                                _icss, _ilbl = "imp-med", "MED IMPACT"
                            elif "upgrade " in _alt_lo:
                                _icss, _ilbl = "imp-med", "MED IMPACT"
                            else:
                                _icss, _ilbl = "imp-low", "LOW IMPACT"
                            if " — " in _alt:
                                _rt, _rd = _alt.split(" — ", 1)
                            elif " (" in _alt:
                                _rt = _alt.split(" (")[0]
                                _rd = "(" + _alt.split(" (", 1)[1]
                            else:
                                _rt, _rd = _alt, ""
                            _rt = _rt.strip(); _rd = _rd.strip()
                            _desc_html = (
                                f'<div style="font-size:.63rem;color:{_MUT};'
                                f'line-height:1.5;margin-top:6px">{_rd}</div>'
                                if _rd else ""
                            )
                            _m = _mcache[_ri] if _ri < len(_mcache) else {}
                            _metrics_html = (
                                f'<div style="display:flex;gap:4px;margin-top:10px;'
                                f'padding-top:8px;border-top:1px solid {_BORD}">'
                                + _metric_col(_m.get("weight_pct"), "Weight")
                                + _metric_col(_m.get("cost_pct"),   "Cost")
                                + _metric_col(_m.get("defl_pct"),   "Max Deflection")
                                + '</div>'
                            ) if _m else ""
                            st.markdown(
                                f'<div class="rec-card" style="margin-bottom:6px">'
                                f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">'
                                f'<span class="rec-n" style="background:{_nc};flex-shrink:0">{_ri+1}</span>'
                                f'<span class="rec-title">{_rt}</span>'
                                f'<span class="{_icss}">{_ilbl}</span>'
                                f'</div>'
                                f'{_desc_html}'
                                f'{_metrics_html}'
                                f'</div>',
                                unsafe_allow_html=True,
                            )
                            _bc1, _bc2 = st.columns(2)
                            with _bc1:
                                if st.button(
                                    "Preview", key=f"rec_prev_{_ri}",
                                    width="stretch",
                                ):
                                    st.session_state["preview_alt"] = _alt
                                    st.session_state.viewer_nonce += 1
                                    st.rerun()
                            with _bc2:
                                if st.button(
                                    "Apply Change", key=f"rec_apply_{_ri}",
                                    width="stretch", type="primary",
                                ):
                                    _new_ls, _new_ev = _apply_alternative(
                                        _alt, json.dumps(layout_obj),
                                        _mat_now, _sdl_now, _ll_now,
                                    )
                                    if _new_ev:
                                        _push_version(json.loads(_new_ls))
                                        st.session_state.eval_result = _new_ev
                                        st.session_state.eval_alts = _get_failure_alternatives(
                                            _new_ev, _mat_now
                                        )
                                        st.rerun()

            # ── Flexibility & alternatives (architect-facing advice) ──────────
            if er:
                _flex = _flexibility_rows(er)
                if _flex:
                    with st.expander("🧭  Flexibility & alternatives", expanded=False):
                        st.markdown(
                            f'<div style="font-size:.62rem;color:{_MUT};margin-bottom:6px">'
                            f'Demand/capacity per member — which are tight (need attention) vs '
                            f'slack (could be lighter).</div>', unsafe_allow_html=True)

                        def _flex_row(r):
                            _v = r["util"]
                            _c = (_FAIL if _v > 100 else "#c07800" if _v >= 85
                                  else _PASS_C if _v < 40 else _TEXT)
                            _verdict, _sugg = _flex_advice(_v)
                            return (
                                f'<div style="border-top:1px solid {_BORD};padding:5px 0">'
                                f'<div style="display:flex;justify-content:space-between;font-size:.66rem">'
                                f'<span style="color:{_TEXT};font-weight:700">{r["id"]}</span>'
                                f'<span style="color:{_c};font-weight:700">{_v:.0f}% · {_verdict}</span></div>'
                                f'<div style="font-size:.58rem;color:{_MUT}">{r["kind"]} · {r["sec"] or "—"} '
                                f'· governed by {r["gov"]} → {_sugg}</div></div>'
                            )

                        _tight = _flex[:5]
                        _slack = [r for r in reversed(_flex) if r["util"] < 65][:5]
                        st.markdown(
                            f'<div style="font-size:.60rem;font-weight:700;color:{_FAIL};'
                            f'text-transform:uppercase;letter-spacing:.5px">Most critical / tight</div>'
                            + "".join(_flex_row(r) for r in _tight), unsafe_allow_html=True)
                        if _slack:
                            st.markdown(
                                f'<div style="font-size:.60rem;font-weight:700;color:{_PASS_C};'
                                f'text-transform:uppercase;letter-spacing:.5px;margin-top:8px">'
                                f'Most flexible / slack</div>'
                                + "".join(_flex_row(r) for r in _slack), unsafe_allow_html=True)
                        st.caption("Ask the agent e.g. \"explain the flexibility of A3-A5\" "
                                   "or \"fix the failing beams\" for actions.")

        with _rt2:
            if st.button("⟳  Show details for selected element", key="dd_show_details",
                         width="stretch",
                         help="Click an element in the 3D/2D view, then press this to load its details here."):
                st.rerun()
            _sel     = st.session_state.selected_el
            _sel_level = st.session_state.get("active_element_level", "")
            _found_level, _found_el = find_element_in_layout(layout_obj, _sel) if _sel else (None, None)
            _sel_obj = _found_el
            if _found_level:
                _sel_level = _found_level
                st.session_state.active_element_level = _found_level
            _dbg = st.session_state.get("last_click_debug", {})

            if _sel:
                st.markdown(
                    f'<div style="font-size:.64rem;color:{_MUT};margin:2px 0 8px 0">'
                    f'Selected element ID: '
                    f'<span style="color:{_TEXT};font-weight:700">{_sel}</span>'
                    f'{f" <span style=\"color:{_MUT};font-weight:600\">({_sel_level})</span>" if _sel_level else ""}'
                    f'</div>',
                    unsafe_allow_html=True,
                )

            if _dbg:
                _dbg_id = _dbg.get("selected_id", "") or "(none)"
                _dbg_pts = _dbg.get("points_count", 0)
                _dbg_cands = _dbg.get("candidates", [])
                _dbg_cands_txt = " | ".join(_dbg_cands) if _dbg_cands else "(none)"
                st.markdown(
                    f'<div style="font-size:.62rem;color:{_MUT};line-height:1.55;'
                    f'border:1px dashed {_BORD};border-radius:8px;padding:8px;margin:0 0 8px 0">'
                    f'<b style="color:{_TEXT}">Selection Debug</b><br>'
                    f'points captured: <b style="color:{_TEXT}">{_dbg_pts}</b><br>'
                    f'candidate(s): <span style="color:{_TEXT}">{_dbg_cands_txt}</span><br>'
                    f'resolved selected_id: <b style="color:{_TEXT}">{_dbg_id}</b>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                with st.expander("Raw click payload", expanded=False):
                    st.json(_dbg.get("raw_first_point", {}))

            if _sel_obj:
                st.markdown(_el_detail_html(_sel_obj, er), unsafe_allow_html=True)

                # ── Force & moment diagram (any selected beam — passing OR failing) ──
                _sel_is_beam = len(_sel_obj.get("geometry", [])) == 2
                if _sel_is_beam:
                    _bev = next((b for b in (er or {}).get("beams", [])
                                 if b.get("id") == _sel), None)
                    with st.expander("📐  Force & moment diagram", expanded=False):
                        try:
                            if _bev:
                                _d_span = _bev.get("span_m", 0.0)
                                _d_w    = _bev.get("w_total_kNm", 0.0)
                                _d_mmax = _bev.get("M_max_kNm", 0.0)
                            else:
                                import math as _dmath
                                _dg = _sel_obj.get("geometry", [])
                                _d_span = _dmath.dist(_dg[0], _dg[1]) if len(_dg) >= 2 else 0.0
                                _d_w    = (_sdl_now + _ll_now) * 3.0   # nominal 3 m tributary
                                _d_mmax = _d_w * _d_span * _d_span / 8.0
                            st.image(
                                _beam_diagram_png(_d_span, _d_w, _d_mmax, _sel, _is_light),
                                width="stretch",
                            )
                            if not _bev:
                                st.caption("Estimated loads — run analysis for exact values.")
                        except Exception as _de:
                            st.caption(f"Diagram unavailable: {_de}")

                # ── Direct action buttons (bypass agent) ──────────────────
                _act_cols = st.columns(2, gap="small") if _sel_is_beam else st.columns([1, 1], gap="small")

                with _act_cols[0]:
                    if st.button(f"✕  Remove", key="btn_direct_remove",
                                 width="stretch"):
                        try:
                            from nodes.modify import remove_element as _direct_rem
                            _new_layout = json.loads(_direct_rem(json.dumps(layout_obj), _sel))
                            # If the element is still present, removal was blocked (perimeter lock).
                            if find_element_in_layout(_new_layout, _sel)[1] is not None:
                                st.session_state["_remove_blocked"] = _sel
                                st.rerun()
                            else:
                                _push_version(_new_layout)
                                st.session_state.selected_el = ""
                                st.session_state.active_element_level = ""
                                st.session_state["_remove_blocked"] = ""
                                st.rerun()
                        except Exception as _re:
                            st.error(f"Remove failed: {_re}")

                if _sel_is_beam:
                    with _act_cols[1]:
                        if st.button("⊕  Add Mid-col", key="btn_direct_midcol",
                                     width="stretch"):
                            try:
                                from nodes.modify import add_midspan_column as _direct_amc
                                _new_layout = json.loads(_direct_amc(json.dumps(layout_obj), _sel, _mat_now))
                                _push_version(_new_layout)
                                st.session_state.selected_el = ""
                                st.session_state.active_element_level = ""
                                st.rerun()
                            except Exception as _me:
                                st.error(f"Add midspan column failed: {_me}")

                # Perimeter elements are envelope-locked — explain, then allow a forced remove.
                if st.session_state.get("_remove_blocked") == _sel:
                    st.markdown(
                        f'<div style="background:{_FAIL_BG};color:{_FAIL};border:1px solid {_FAIL};'
                        f'border-radius:6px;padding:7px 10px;font-size:.66rem;line-height:1.5;margin-top:6px">'
                        f'<b>{_sel}</b> is a <b>perimeter</b> element — it defines the building '
                        f'envelope and is locked. Removing it may compromise the structure. '
                        f'Remove it anyway only if you are sure.</div>',
                        unsafe_allow_html=True,
                    )
                    if st.button("⚠  Force remove anyway", key="btn_force_remove",
                                 width="stretch", type="primary"):
                        try:
                            from nodes.modify import remove_element as _force_rem
                            _new_layout = json.loads(_force_rem(json.dumps(layout_obj), _sel, True))
                            _push_version(_new_layout)
                            st.session_state.selected_el = ""
                            st.session_state.active_element_level = ""
                            st.session_state["_remove_blocked"] = ""
                            st.rerun()
                        except Exception as _fre:
                            st.error(f"Force remove failed: {_fre}")

                st.markdown("<div style='margin-bottom:8px'></div>", unsafe_allow_html=True)

            else:
                st.markdown(
                    f'<div style="font-size:.70rem;color:{_MUT};padding:4px 0">'
                    f'Click an element in the plan to inspect it.</div>',
                    unsafe_allow_html=True,
                )

            if er:
                _fbeams = [b for b in er.get("beams", [])
                           if not all([b.get("bend_PASS"), b.get("shear_PASS"),
                                       b.get("defl_TL_PASS"), b.get("defl_LL_PASS")])]
                _fcols  = [c for c in er.get("columns", [])
                           if not all([c.get("stress_PASS"), c.get("buckling_PASS")])]
                if _fbeams or _fcols:
                    st.markdown(
                        '<div class="panel-hdr" style="margin-top:8px">Critical Elements</div>',
                        unsafe_allow_html=True,
                    )
                    _crit_html = ""
                    for _b in _fbeams[:4]:
                        _b_lvl, _ = find_element_in_layout(layout_obj, _b["id"])
                        _chks = [k for k, f in [
                            ("bend",  not _b.get("bend_PASS")),
                            ("shear", not _b.get("shear_PASS")),
                            ("defl",  not _b.get("defl_TL_PASS") or not _b.get("defl_LL_PASS")),
                        ] if f]
                        _crit_html += (
                            f'<div class="crit-item" '
                            f'onclick="window.parent.postMessage({{type:\'selectElement\','
                            f'elementId:\'{_b["id"]}\',level:\'{_b_lvl or ""}\'}},\'*\')">'
                            f'<b>{_b["id"]}</b> {_b.get("span_m",0):.1f}m'
                            f'<span style="float:right;color:{_FAIL}">{", ".join(_chks)}</span></div>'
                        )
                    for _c in _fcols[:2]:
                        _c_lvl, _ = find_element_in_layout(layout_obj, _c["id"])
                        _chks = [k for k, f in [
                            ("stress", not _c.get("stress_PASS")),
                            ("buck",   not _c.get("buckling_PASS")),
                        ] if f]
                        _crit_html += (
                            f'<div class="crit-item" '
                            f'onclick="window.parent.postMessage({{type:\'selectElement\','
                            f'elementId:\'{_c["id"]}\',level:\'{_c_lvl or ""}\'}},\'*\')">'
                            f'<b>{_c["id"]}</b>'
                            f'<span style="float:right;color:{_FAIL}">{", ".join(_chks)}</span></div>'
                        )
                    st.markdown(_crit_html, unsafe_allow_html=True)
                elif er:
                    st.markdown('<span class="pass-badge">✓ All elements pass</span>',
                                unsafe_allow_html=True)

            # ── Stress Hierarchy ──────────────────────────────────────────────
            if er:
                st.markdown(
                    '<div class="panel-hdr" style="margin-top:10px">Stress Hierarchy</div>',
                    unsafe_allow_html=True,
                )
                _hier_items = []
                for _hb in er.get("beams", []):
                    _hu = max(
                        _hb.get("sigma_bend_MPa", 0) / max(_hb.get("allow_bend_MPa",  1), 1e-6),
                        _hb.get("tau_MPa",         0) / max(_hb.get("allow_shear_MPa", 1), 1e-6),
                        _hb.get("delta_total_mm",  0) / max(_hb.get("limit_TL_mm",     1), 1e-6),
                    )
                    _hier_items.append({
                        "id": _hb.get("id", ""), "type": "Primary Girder",
                        "util": _hu, "dim": f'{_hb.get("span_m", 0):.1f} m',
                    })
                for _hc in er.get("columns", []):
                    _hu = max(
                        _hc.get("sigma_comp_MPa", 0) / max(_hc.get("allow_comp_MPa", 1), 1e-6),
                        (1 / max(_hc.get("SF_buckling", 3.0), 0.01)) * 3.0,
                    )
                    _hier_items.append({
                        "id": _hc.get("id", ""), "type": "Column",
                        "util": _hu, "dim": f'{_hc.get("trib_area_m2", 0):.1f} m²',
                    })
                _hier_items.sort(key=lambda x: x["util"], reverse=True)
                _hh = '<div style="display:flex;flex-direction:column;gap:3px;margin-top:5px">'
                for _hi in _hier_items[:16]:
                    _u    = min(_hi["util"], 1.0)
                    _pct  = int(_u * 100)
                    _pw   = f"{_u * 100:.0f}%"
                    _hclr = ("#e05050" if _u >= 0.70 else
                             "#e08020" if _u >= 0.50 else
                             "#d4a800" if _u >= 0.35 else "#40d090")
                    _hh += (
                        f'<div style="display:flex;align-items:center;gap:5px;padding:2px 0">'
                        f'<span style="width:7px;height:7px;border-radius:50%;'
                        f'background:{_hclr};flex-shrink:0"></span>'
                        f'<span style="font-size:.62rem;font-weight:700;color:#c8eeed;'
                        f'width:48px;flex-shrink:0;overflow:hidden;text-overflow:ellipsis;'
                        f'white-space:nowrap">{_hi["id"]}</span>'
                        f'<span style="font-size:.58rem;color:#5a8080;flex:1;min-width:0;'
                        f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'
                        f'{_hi["type"]}</span>'
                        f'<div style="width:68px;height:3px;background:#0d3030;'
                        f'border-radius:2px;overflow:hidden;flex-shrink:0">'
                        f'<div style="width:{_pw};height:100%;background:{_hclr};'
                        f'border-radius:2px"></div></div>'
                        f'<span style="font-size:.62rem;font-weight:700;color:{_hclr};'
                        f'width:26px;text-align:right;flex-shrink:0">{_pct}%</span>'
                        f'<span style="font-size:.58rem;color:#5a8080;width:36px;'
                        f'text-align:right;flex-shrink:0">{_hi["dim"]}</span>'
                        f'</div>'
                    )
                if not _hier_items:
                    _hh += f'<div style="font-size:.70rem;color:#5a9090;padding:6px 0">Run structural analysis to see hierarchy.</div>'
                _hh += '</div>'
                st.markdown(_hh, unsafe_allow_html=True)

            st.markdown(
                '<div class="panel-hdr" style="margin-top:10px">History</div>',
                unsafe_allow_html=True,
            )
            _sh = st.session_state.state_history
            if not _sh:
                st.markdown(
                    f'<div style="font-size:.70rem;color:{_MUT}">No history yet.</div>',
                    unsafe_allow_html=True,
                )
            else:
                _hist_html = ""
                for _h in reversed(_sh[-5:]):
                    _hev  = (_h.get("eval_result") or {}).get("summary", {})
                    _hbf  = _hev.get("beam_failures", 0)
                    _hcf2 = _hev.get("column_failures", 0)
                    _hp   = _hev.get("overall_PASS", None)
                    _ht   = "Pass" if _hp else ("Fail" if _hp is False else "--")
                    _hist_html += (
                        f'<div class="hist-item">'
                        f'<div class="hist-dot"></div>'
                        f'<div><div class="hist-label">{_h["label"]}</div>'
                        f'<div class="hist-sub">{_ht} · {_hbf}B {_hcf2}C</div></div></div>'
                    )
                st.markdown(_hist_html, unsafe_allow_html=True)

            if _snaps:
                with st.expander(f"Saved Snapshots ({len(_snaps)})", expanded=False):
                    for _sn in _snaps:
                        _sev   = (_sn.get("eval_result") or {}).get("summary", {})
                        _sfail = _sev.get("beam_failures",0) + _sev.get("column_failures",0)
                        _scf   = _sn.get("cost_flexibility")
                        with st.expander(
                            f"{_sn['label']} · {'OK' if _sfail==0 else f'{_sfail} fail'}",
                            expanded=False,
                        ):
                            if _scf:
                                _s1, _s2 = st.columns(2)
                                _s1.metric("Net",  f"${_scf.get('net_cost_usd',0):+,.0f}")
                                _s2.metric("Flex", f"{_scf.get('flexibility_score',0):.1f}/10")
                            if st.button(f"Restore {_sn['label']}",
                                         key=f"restore_{_sn['label']}"):
                                _push_version(json.loads(_sn["layout_json"]))
                                st.session_state.eval_result = _sn.get("eval_result")
                                st.session_state.eval_alts   = _get_failure_alternatives(
                                    _sn.get("eval_result") or {}, _mat_now)
                                st.rerun()

            with st.expander("Output Log", expanded=False):
                for _msg in reversed(st.session_state.output_log[-6:]):
                    st.markdown(
                        f'<div class="log-entry">{_msg[:220]}'
                        f'{"…" if len(_msg)>220 else ""}</div>',
                        unsafe_allow_html=True,
                    )

            # (Inline agent chat removed from Design Details — the single agent
            #  chat now lives only in the left sidebar to avoid duplication.)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — COMPARE
# ══════════════════════════════════════════════════════════════════════════════
with tab_cmp:

    # ── Data ─────────────────────────────────────────────────────────────────
    _snaps_c = st.session_state.snapshots
    _cvm_now = st.session_state.get("compare_view_mode", "2D")
    _cmp_ids = st.session_state.get("cmp_labels", False)
    _cmp_ev  = st.session_state.get("cmp_eval",   True)
    _DOT_C   = [_ACC, _ACC2, "#ffd060", "#ff8080", "#88d088", "#c0a0ff"]

    def _snap_fails(s):
        _ev_ = (s.get("eval_result") or {}).get("summary", {})
        return _ev_.get("beam_failures", 0) + _ev_.get("column_failures", 0)

    # ── Validate cmp_sel_indices against current snapshots ─────────────────────
    _all_snap_labels = [s["label"] for s in _snaps_c]
    _sel_idx_raw = st.session_state.get("cmp_sel_indices", [])
    _sel_idx = [i for i in _sel_idx_raw if i < len(_snaps_c)]
    if _sel_idx != _sel_idx_raw:
        st.session_state.cmp_sel_indices = _sel_idx

    # Always include baseline + selected snapshots
    _cmp_opts = [
        {"label": "Baseline", "sub": "Current design",
         "layout_json": json.dumps(layout_obj),
         "eval_result": er, "cost_flexibility": st.session_state.cost_flexibility,
         "dot": _DOT_C[0]}
    ] + [
        {"label": _snaps_c[i]["label"],
         "sub":   "Pass" if _snap_fails(_snaps_c[i]) == 0 else f"{_snap_fails(_snaps_c[i])} fail",
         "layout_json":      _snaps_c[i]["layout_json"],
         "eval_result":      _snaps_c[i].get("eval_result"),
         "cost_flexibility": _snaps_c[i].get("cost_flexibility"),
         "dot": _DOT_C[min(_j + 1, len(_DOT_C)-1)]}
        for _j, i in enumerate(_sel_idx)
    ]
    _n_opts = len(_cmp_opts)

    # ── Metric helpers ────────────────────────────────────────────────────────
    def _co_weight(co):
        return _eval_weight_cost(co.get("eval_result") or {})[0]

    def _co_cost(co):
        cf = co.get("cost_flexibility") or {}
        if cf.get("net_cost_usd") is not None:
            return float(cf["net_cost_usd"])
        return _eval_weight_cost(co.get("eval_result") or {})[1]

    def _co_max_defl(co):
        bs = (co.get("eval_result") or {}).get("beams", [])
        return max((b.get("delta_total_mm", 0) for b in bs), default=None) if bs else None

    def _co_max_util(co):
        ev  = co.get("eval_result") or {}
        rat = []
        for b in ev.get("beams", []):
            if b.get("allow_bend_MPa"):
                rat.append(b["sigma_bend_MPa"] / b["allow_bend_MPa"])
            if b.get("allow_shear_MPa"):
                rat.append(b["tau_MPa"] / b["allow_shear_MPa"])
            if b.get("limit_TL_mm"):
                rat.append(b["delta_total_mm"] / b["limit_TL_mm"])
        for c in ev.get("columns", []):
            if c.get("allow_comp_MPa"):
                rat.append(c["sigma_comp_MPa"] / c["allow_comp_MPa"])
        return round(max(rat) * 100, 1) if rat else None

    def _best_from(pairs, lower=True):
        valid = [(l, v) for l, v in pairs if isinstance(v, (int, float))]
        if not valid:
            return "—", None
        return (min if lower else max)(valid, key=lambda x: x[1])

    # -- Layout: comparison plans (left) + View Settings / Comparison Set rail
    #    Mirrors the ANALYSIS / DESIGN DETAILS rail in the Modify workspace.
    _cmp_main, _cmp_right = st.columns([2.1, 0.55], gap="small")

    with _cmp_right:
        _ct_vs, _ct_set = st.tabs(["  VIEW SETTINGS  ", "  COMPARISON SET  "])
        with _ct_vs:
            st.markdown(
                f'<div class="sb-section" style="margin-top:4px">View Settings</div>',
                unsafe_allow_html=True,
            )
            _vs1, _vs2 = st.columns(2, gap="small")
            with _vs1:
                if st.button("2D", key="cmp_2d", width="stretch",
                             type="primary" if _cvm_now == "2D" else "secondary"):
                    st.session_state["compare_view_mode"] = "2D"
                    st.rerun()
            with _vs2:
                if st.button("3D", key="cmp_3d", width="stretch",
                             type="primary" if _cvm_now == "3D" else "secondary"):
                    st.session_state["compare_view_mode"] = "3D"
                    st.rerun()
            # Level selector (replaces the old Overlay-IDs / Eval-overlay toggles).
            _cmp_lvl_keys = get_level_keys(layout_obj) or ["level_01"]
            _cmp_lvl_opts = (_cmp_lvl_keys + ["All levels"]) if len(_cmp_lvl_keys) > 1 else _cmp_lvl_keys
            _cmp_cur = st.session_state.get("cmp_level", _cmp_lvl_keys[0])
            if _cmp_cur not in _cmp_lvl_opts:
                _cmp_cur = _cmp_lvl_keys[0]
            _cmp_level_sel = st.selectbox(
                "Show", _cmp_lvl_opts,
                index=_cmp_lvl_opts.index(_cmp_cur),
                format_func=lambda x: ("Show all levels" if x == "All levels" else f"Show {x}"),
                key="cmp_level_sel",
            )
            st.session_state.cmp_level = _cmp_level_sel
            _cmp_ids = st.toggle("Show labels", value=_cmp_ids, key="cmp_labels")

            st.markdown(
                f'<div class="sb-section" style="margin-top:10px">Legend</div>',
                unsafe_allow_html=True,
            )
            _legend_items = _present_legend_items(layout_obj, _is_light)
            if _legend_items:
                _leg_html = '<div style="display:grid;grid-template-columns:1fr 1fr;gap:4px 6px;margin-top:2px">'
                for _lc, _ll in _legend_items:
                    _leg_html += (
                        f'<div style="display:flex;align-items:center;gap:4px;font-size:.60rem;color:{_MUT}">'
                        f'<span style="width:8px;height:8px;border-radius:50%;background:{_lc};flex-shrink:0;display:inline-block"></span>'
                        f'{_ll}</div>'
                    )
                _leg_html += '</div>'
                st.markdown(_leg_html, unsafe_allow_html=True)
            _cmp_mat_leg = _material_legend_html(layout_obj, _is_light, _MUT)
            if _cmp_mat_leg:
                st.markdown(_cmp_mat_leg, unsafe_allow_html=True)

            st.markdown('<div style="margin-top:10px"></div>', unsafe_allow_html=True)
            if st.button("Reset View", key="cmp_reset_view", width="stretch"):
                st.session_state["compare_view_mode"] = "2D"
                st.session_state["cmp_labels"] = False
                st.session_state["cmp_eval"]   = True
                st.rerun()
        with _ct_set:
            st.markdown(
                f'<div style="font-size:.60rem;color:{_MUT};margin:4px 0 6px;line-height:1.5">'
                f'Pick which snapshots to compare — add as many as you need.</div>',
                unsafe_allow_html=True,
            )
            # Baseline always shown
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:7px;padding:4px 6px;'
                f'border-radius:5px;background:{"#eef7f7" if _is_light else "#0d2828"};margin-bottom:3px">'
                f'<span style="width:8px;height:8px;border-radius:50%;background:{_DOT_C[0]};flex-shrink:0;display:inline-block"></span>'
                f'<span style="font-size:.70rem;font-weight:700;color:{_TEXT}">Baseline (Current)</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
            if _snaps_c:
                _ca1, _ca2 = st.columns(2, gap="small")
                with _ca1:
                    if st.button("Add all", key="cmp_add_all", width="stretch"):
                        st.session_state.cmp_sel_indices = list(range(len(_snaps_c)))
                        st.rerun()
                with _ca2:
                    if st.button("Clear", key="cmp_clear_all", width="stretch",
                                 disabled=not _sel_idx):
                        st.session_state.cmp_sel_indices = []
                        st.rerun()
                for _si, _sn in enumerate(_snaps_c):
                    _in_cmp = _si in _sel_idx
                    _dot_c  = _DOT_C[min(_sel_idx.index(_si)+1 if _in_cmp else 0, len(_DOT_C)-1)]
                    _s_fails = _snap_fails(_sn)
                    _s_sub  = "Pass" if _s_fails == 0 else f"{_s_fails} fail"
                    _s_bg   = f"{'rgba(42,192,192,0.08)' if _in_cmp else 'transparent'}"
                    _s_brd  = f"border:1px solid {_ACC if _in_cmp else _BORD}"
                    _c1, _c2 = st.columns([4, 1], gap="small")
                    with _c1:
                        st.markdown(
                            f'<div style="display:flex;align-items:center;gap:6px;padding:4px 6px;'
                            f'border-radius:5px;background:{_s_bg};{_s_brd};margin-bottom:2px">'
                            f'<span style="width:8px;height:8px;border-radius:50%;background:{_dot_c if _in_cmp else _MUT};flex-shrink:0;display:inline-block"></span>'
                            f'<div style="min-width:0"><div style="font-size:.70rem;font-weight:{"700" if _in_cmp else "400"};color:{_TEXT if _in_cmp else _MUT};overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{_sn["label"]}</div>'
                            f'<div style="font-size:.58rem;color:{_MUT}">{_s_sub}</div></div>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
                    with _c2:
                        if _in_cmp:
                            if st.button("✕", key=f"cmp_rm_{_si}", width="stretch"):
                                _new_idx = [i for i in _sel_idx if i != _si]
                                st.session_state.cmp_sel_indices = _new_idx
                                st.rerun()
                        else:
                            if st.button("+", key=f"cmp_add_{_si}", width="stretch"):
                                st.session_state.cmp_sel_indices = _sel_idx + [_si]
                                st.rerun()
            else:
                st.markdown(
                    f'<div style="font-size:.60rem;color:{_MUT};padding:6px 4px;'
                    f'border:1px dashed {_BORD};border-radius:6px;margin-top:3px">'
                    f'Save snapshots in the Modify tab to compare options here.</div>',
                    unsafe_allow_html=True,
                )

    with _cmp_main:
        # ── Report options bar (Export JSON lives in the global top bar) ────────────
        _rp1, _rp3, _rp4 = st.columns([4.4, 0.9, 0.7], gap="small")
        with _rp1:
            st.markdown(
                f'<div style="font-size:.60rem;font-weight:700;color:{_MUT};'
                f'text-transform:uppercase;letter-spacing:1px;padding:6px 0">'
                f'Compare Options</div>',
                unsafe_allow_html=True,
            )
        with _rp3:
            with st.popover("🧾 AI Report", width="stretch"):
                st.caption("Agent writes a structural report; the PDF includes the "
                           "explanation, labelled plans and shear/moment diagrams.")
                if st.button("Generate report", key="cmp_gen_report", width="stretch"):
                    with st.spinner("Writing structural report…"):
                        if _llm_is_reachable():
                            _rep = _run_agent_chat(
                                "Write a concise structural report for this layout: summarise the "
                                "framing system, materials, spans, any failing elements and the "
                                "recommended fixes. Plain prose, no JSON.",
                                layout_obj, er,
                            )
                            if (not _rep) or _rep.startswith(("APPLY_TOOL:", "GENERATE_GRID", "EVALUATE")):
                                _rep = _structural_summary_text(layout_obj, er)
                        else:
                            _rep = _structural_summary_text(layout_obj, er)
                    st.session_state["_cmp_report_txt"] = _rep
                _rep_txt = st.session_state.get("_cmp_report_txt")
                if _rep_txt:
                    st.markdown(
                        f'<div style="font-size:.66rem;color:{_MUT};max-height:140px;'
                        f'overflow-y:auto;white-space:pre-wrap;line-height:1.5">{_rep_txt}</div>',
                        unsafe_allow_html=True,
                    )
                    try:
                        _rep_pdf = _sheet_pdf_bytes(
                            json.dumps(layout_obj), json.dumps(er) if er else "",
                            str(_lid), str(_mat_now),
                            tuple((h.get("prompt") or h.get("label") or "")
                                  for h in st.session_state.get("history", [])[-7:]),
                            True, _rep_txt,
                        )
                        st.download_button(
                            "⤓ Download report (PDF)", data=_rep_pdf,
                            file_name=f"{_lid}_structural_report.pdf",
                            mime="application/pdf", width="stretch", key="cmp_dl_report",
                        )
                    except Exception as _re:
                        st.caption(f"Report build failed: {_re}")
        with _rp4:
            if st.button("✕ Reset", width="stretch", key="btn_reset_cmp"):
                st.session_state.snapshots = []
                st.session_state.cmp_sel_indices = []
                st.rerun()

        # ── Comparison plans area ─────────────────────────────────────────────────
        st.markdown(f'<div style="margin-top:10px;border-top:1px solid {_BORD}"></div>',
                    unsafe_allow_html=True)

        if _n_opts < 2:
            st.markdown(
                f'<div style="font-size:.70rem;color:{_MUT};padding:20px 8px;'
                f'text-align:center;line-height:1.9">'
                f'Select at least one snapshot using <b>+</b> in the '
                f'<b>Comparison Set</b> tab on the right.</div>',
                unsafe_allow_html=True,
            )
        else:
            # (Baseline-only insight chips removed — the metric cards below already
            #  show the per-option comparison.)

            # ── Metric row ─────────────────────────────────────────────────────────
            def _delta_badge(val, base, lower_good=True):
                if val is None or base is None or abs(base) < 0.001:
                    return ""
                d    = (val - base) / abs(base) * 100
                good = (d < 0) if lower_good else (d > 0)
                clr  = _PASS_C if good else _FAIL
                arr  = "↓" if d < 0 else "↑"
                return (f'<span style="font-size:.58rem;font-weight:700;'
                        f'color:{clr};margin-left:3px">{arr}&nbsp;{abs(d):.1f}%</span>')

            def _met_card(title, unit, vals, fmt=".1f", lower_good=True):
                base = vals[0]
                html = (
                    f'<div style="flex:1;border:1px solid {_BORD};border-radius:8px;'
                    f'padding:8px 10px;background:{_CARD};min-width:0">'
                    f'<div style="font-size:.58rem;font-weight:700;color:{_MUT};'
                    f'text-transform:uppercase;letter-spacing:.5px;margin-bottom:2px">'
                    f'{title}</div>'
                    f'<div style="font-size:.55rem;color:{_MUT};margin-bottom:6px">({unit})</div>'
                    f'<div style="display:flex;gap:6px">'
                )
                for _i, (_co, _v) in enumerate(zip(_cmp_opts, vals)):
                    _vstr = (f'{_v:{fmt}}' if isinstance(_v, (int, float)) else "—")
                    _dlta = "" if _i == 0 else _delta_badge(_v, base, lower_good)
                    _lbl_clr = _MUT if _i == 0 else (
                        (_PASS_C if (isinstance(_v, (int, float)) and isinstance(base, (int, float))
                                     and ((_v < base) if lower_good else (_v > base)))
                         else _TEXT)
                    )
                    html += (
                        f'<div style="flex:1;min-width:0;text-align:center">'
                        f'<div style="font-size:.55rem;color:{_MUT};margin-bottom:2px;'
                        f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'
                        f'{_co["label"]}</div>'
                        f'<div style="font-size:.75rem;font-weight:800;color:{_lbl_clr}">'
                        f'{_vstr}</div>'
                        f'{_dlta}</div>'
                    )
                html += '</div></div>'
                return html

            _wvals = [_co_weight(c)   for c in _cmp_opts]
            _cvals = [_co_cost(c)     for c in _cmp_opts]
            _dvals = [_co_max_defl(c) for c in _cmp_opts]
            _uvals = [_co_max_util(c) for c in _cmp_opts]

            st.markdown(
                f'<div style="display:flex;gap:8px;margin-bottom:12px">'
                + _met_card("Total Weight",    "kN",  _wvals, ".1f")
                + _met_card("Total Cost",      "USD", _cvals, ".0f")
                + _met_card("Max Deflection",  "mm",  _dvals, ".1f")
                + _met_card("Max Utilization", "%",   _uvals, ".1f")
                + '</div>',
                unsafe_allow_html=True,
            )

            # ── Diff legend (each non-baseline window is coloured vs the baseline) ──
            _baseline_layout = _normalize_layout(json.loads(_cmp_opts[0]["layout_json"]))
            _add_c = "#1a8050" if _is_light else "#40d090"
            _rem_c = "#cc2020" if _is_light else "#ff5050"
            _mod_c = "#7c4dff" if _is_light else "#9b7cff"
            st.markdown(
                f'<div style="display:flex;gap:14px;align-items:center;margin-bottom:8px;'
                f'font-size:.60rem;color:{_MUT}">'
                f'<span style="font-weight:700;text-transform:uppercase;letter-spacing:.5px">vs Baseline</span>'
                f'<span style="display:flex;align-items:center;gap:4px"><span style="width:10px;height:10px;border-radius:2px;background:{_add_c};display:inline-block"></span>Added</span>'
                f'<span style="display:flex;align-items:center;gap:4px"><span style="width:10px;height:10px;border-radius:2px;background:{_rem_c};display:inline-block"></span>Removed</span>'
                f'<span style="display:flex;align-items:center;gap:4px"><span style="width:10px;height:10px;border-radius:2px;background:{_mod_c};display:inline-block"></span>Changed</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

            # ── Floor plan columns ─────────────────────────────────────────────────
            _pcols = st.columns(_n_opts, gap="small")
            for _ci, (_pcol, _co) in enumerate(zip(_pcols, _cmp_opts)):
                with _pcol:
                    _dc = _co.get("dot", _DOT_C[min(_ci, len(_DOT_C)-1)])
                    _badge = (
                        '<span class="badge-curr">Current Design</span>'
                        if _ci == 0 else
                        f'<span class="badge-opt">Applied Changes ({_ci})</span>'
                    )
                    st.markdown(
                        f'<div class="cmp-card-hdr">'
                        f'<span style="display:flex;align-items:center;gap:6px">'
                        f'<span style="width:8px;height:8px;border-radius:50%;'
                        f'background:{_dc};flex-shrink:0;display:inline-block"></span>'
                        f'<span class="cmp-title">{_co["label"]}</span></span>'
                        f'{_badge}</div>',
                        unsafe_allow_html=True,
                    )
                    _plan_ci = _normalize_layout(json.loads(_co["layout_json"]))
                    _ph = max(220, 300 - (_n_opts - 2) * 20)
                    _cmp_lk = ("__ALL__" if st.session_state.get("cmp_level") == "All levels"
                               else st.session_state.get("cmp_level", "level_01"))
                    if _cvm_now == "2D":
                        _fig_ci = _render_floor_plan_plotly(
                            _plan_ci,
                            eval_result=_co["eval_result"] if _cmp_ev else None,
                            level_key=_cmp_lk,
                            labels=_cmp_ids, height_px=_ph, is_light=_is_light,
                            diff_on=(_ci > 0),
                            before_layout=(_baseline_layout if _ci > 0 else None),
                        )
                        st.plotly_chart(
                            _fig_ci, width="stretch",
                            config=dict(scrollZoom=True, displaylogo=False,
                                        modeBarButtonsToRemove=[
                                            "lasso2d", "select2d",
                                            "zoomIn2d", "zoomOut2d", "autoScale2d",
                                        ]),
                            key=f"cmp_plan_{_ci}",
                        )
                    else:
                        components.html(
                            _render_3d_viewport(
                                _plan_ci,
                                eval_result=_co["eval_result"] if _cmp_ev else None,
                                selected_el="",
                                active_level=_cmp_lk,
                                is_light=_is_light,
                                height=_ph,
                                before_layout=(_baseline_layout if _ci > 0 else None),
                                labels=_cmp_ids,
                            ),
                            height=_ph + 8,
                            scrolling=False,
                        )
                    # Per-plan footer metrics
                    _fw = _co_weight(_co)
                    _fc = _co_cost(_co)
                    _fd = _co_max_defl(_co)
                    _fu = _co_max_util(_co)
                    _fparts = []
                    if _fw is not None: _fparts.append(f"Weight: {_fw:.1f} kN")
                    if _fc is not None: _fparts.append(f"Cost: ${_fc:,.0f}")
                    if _fd is not None: _fparts.append(f"Max Defl: {_fd:.1f} mm")
                    if _fu is not None: _fparts.append(f"Util: {_fu:.0f}%")
                    st.markdown(
                        f'<div style="font-size:.58rem;color:{_MUT};text-align:center;'
                        f'padding:4px 2px;border-top:1px solid {_BORD};line-height:1.6">'
                        + " &nbsp;·&nbsp; ".join(_fparts) + '</div>',
                        unsafe_allow_html=True,
                    )


