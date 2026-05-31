from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

# ── Paths ──────────────────────────────────────────────────────────────────────
REPO_ROOT           = Path(__file__).resolve().parents[2]
DEFAULT_LAYOUT_PATH = REPO_ROOT / "layout_input" / "layout_schema.json"
EDITED_LAYOUT_PATH  = REPO_ROOT / "team_01_edited_layout.json"
BEFORE_LAYOUT_PATH  = REPO_ROOT / "team_01_edited_layout_before.json"
VIEWER_FILE_PATH    = REPO_ROOT / "layout_viewer.html"
VIEWER_BASE_URL     = "http://127.0.0.1:8000/layout_viewer.html"
PYTHON_DIR          = Path(__file__).resolve().parent

if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

if not EDITED_LAYOUT_PATH.exists() and DEFAULT_LAYOUT_PATH.exists():
    EDITED_LAYOUT_PATH.write_text(
        DEFAULT_LAYOUT_PATH.read_text(encoding="utf-8"), encoding="utf-8"
    )


# ── JSON helpers ───────────────────────────────────────────────────────────────

def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _normalize_layout(payload: object) -> dict:
    if isinstance(payload, dict):
        return payload.get("layout", payload) if isinstance(payload.get("layout"), dict) else payload
    if isinstance(payload, list):
        if not payload:
            raise ValueError("Uploaded JSON list is empty")
        first = payload[0]
        if isinstance(first, dict):
            return first.get("layout", first) if isinstance(first.get("layout"), dict) else first
        raise ValueError("First list item must be a layout object")
    raise ValueError("Layout JSON must be an object or a non-empty list")


def _load_working_layout() -> dict:
    if EDITED_LAYOUT_PATH.exists():
        return _normalize_layout(_read_json(EDITED_LAYOUT_PATH))
    if DEFAULT_LAYOUT_PATH.exists():
        return _normalize_layout(_read_json(DEFAULT_LAYOUT_PATH))
    return {}


def _viewer_is_reachable() -> bool:
    try:
        with urllib.request.urlopen(VIEWER_BASE_URL, timeout=0.8) as r:
            return r.status == 200
    except Exception:
        return False


def _viewer_url(highlight: str = "", compare: bool = False) -> str:
    layout_stamp = int(EDITED_LAYOUT_PATH.stat().st_mtime_ns) if EDITED_LAYOUT_PATH.exists() else 0
    theme        = st.session_state.get("theme", "dark")
    url = (
        f"{VIEWER_BASE_URL}"
        f"?v={st.session_state.viewer_nonce}"
        f"&layout={layout_stamp}"
        f"&theme={theme}"
    )
    if highlight:
        url += f"&highlight={highlight}"
    if compare and BEFORE_LAYOUT_PATH.exists():
        url += "&mode=compare"
    return url


def _count_elements(layout: dict) -> tuple[int, int]:
    cols  = sum(1 for el in layout.get("structure", []) if len(el.get("geometry", [])) == 1)
    beams = sum(1 for el in layout.get("structure", []) if len(el.get("geometry", [])) == 2)
    return cols, beams


# ── Structural helpers (direct calls, no input() blocking) ─────────────────────

def _run_evaluate(layout_json_str: str, sdl: float = 3.5, ll: float = 2.0) -> dict | None:
    try:
        from nodes.evaluate import evaluate_structure
        return evaluate_structure(layout_json_str, ll_kNm2=ll, sdl_kNm2=sdl)
    except Exception as e:
        st.warning(f"Evaluation error: {e}")
        return None


def _run_grid_options(layout: dict, material: str) -> list[dict]:
    try:
        from nodes.tools import build_structural_grid_with_options
        bundle = build_structural_grid_with_options(layout, "", material=material)
        return bundle.get("options", [])
    except Exception as e:
        st.warning(f"Grid options error: {e}")
        return []


def _run_cost_flex(before_str: str, after_str: str) -> dict | None:
    try:
        from nodes.cost_flexibility import build_cost_flexibility_node
        node = build_cost_flexibility_node()
        state: dict = {
            "layout_json_string":       after_str,
            "layout_before_change":     before_str,
            "original_layout_json_string": before_str,
            "came_from":                "modify",
        }
        out = node(state)
        return out.get("cost_flexibility")
    except Exception as e:
        st.warning(f"Cost/flex error: {e}")
        return None


def _get_failure_alternatives(eval_result: dict, material: str) -> list[str]:
    try:
        from nodes.evaluate import _build_failure_alternatives
        return _build_failure_alternatives(eval_result, [], material)
    except Exception:
        return []


def _apply_alternative(alt: str, layout_str: str, material: str,
                        sdl: float, ll: float) -> tuple[str, dict | None]:
    """
    Execute one of the suggested structural alternatives.
    Returns (new_layout_json_str, new_eval_result).
    """
    from nodes.modify import (
        upgrade_element_section, add_midspan_column,
        apply_material_override, BEAM_SECTION_UPGRADE, BEAM_DIM_UPGRADE,
        COL_SECTION_UPGRADE, COL_DIM_UPGRADE, BASE_MATERIALS,
    )
    from nodes.evaluate import evaluate_structure

    # Auto-upgrade all failing beams
    if re.match(r"Auto-upgrade \d+ failing beam", alt, re.IGNORECASE):
        ev = st.session_state.eval_result or {}
        for _ in range(8):
            fails = [b for b in ev.get("beams", [])
                     if not (b["bend_PASS"] and b["shear_PASS"] and b["defl_TL_PASS"] and b["defl_LL_PASS"])]
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
        return layout_str, ev

    # Auto-upgrade all failing columns
    if re.match(r"Auto-upgrade \d+ failing col", alt, re.IGNORECASE):
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

    # Per-element upgrade: "Upgrade CD_1 from IPE240 to IPE300"
    m = re.match(r"Upgrade (\S+) from \S+ to (\S+)", alt, re.IGNORECASE)
    if m:
        elem_id, new_sec = m.group(1), m.group(2)
        layout_str = upgrade_element_section(layout_str, elem_id, new_sec)
        ev = evaluate_structure(layout_str, ll_kNm2=ll, sdl_kNm2=sdl)
        return layout_str, ev

    # Midspan column: "Add midspan column under beam CD_1..."
    m2 = re.match(r"Add midspan column under (?:beam )?(\S+)", alt, re.IGNORECASE)
    if m2:
        beam_id = m2.group(1).rstrip("(")
        layout_str = add_midspan_column(layout_str, beam_id, material)
        ev = evaluate_structure(layout_str, ll_kNm2=ll, sdl_kNm2=sdl)
        return layout_str, ev

    # Material switch: "Switch all framing to STEEL"
    m3 = re.match(r"Switch all framing to (\w+)", alt, re.IGNORECASE)
    if m3:
        new_mat = m3.group(1).upper()
        if new_mat in BASE_MATERIALS:
            layout_str = apply_material_override(layout_str, new_mat)
            ev = evaluate_structure(layout_str, ll_kNm2=ll, sdl_kNm2=sdl)
            return layout_str, ev

    # Find minimum (regex from evaluate.py alternatives)
    m4 = re.match(r"Upgrade all to (\S+)", alt, re.IGNORECASE)
    if m4:
        tier = m4.group(1)
        layout_str = apply_material_override(layout_str, tier)
        ev = evaluate_structure(layout_str, ll_kNm2=ll, sdl_kNm2=sdl)
        return layout_str, ev

    return layout_str, None


# ── Agent chat (reason LLM only, no graph invocation, no input() calls) ────────

def _run_agent_chat(prompt: str, layout: dict, eval_result: dict | None = None) -> str:
    """
    Use the reason node LLM to answer a question or explain structural results.
    Does NOT invoke the full LangGraph — no blocking input() calls.
    """
    try:
        from _runtime.bootstrap import bootstrap
        from _runtime.llm import call_llm
        from nodes.reason import SYSTEM_PROMPT
        from nodes.tools import get_action_tools
        from graph import _format_tool_catalog

        ctx          = bootstrap()
        tool_catalog = _format_tool_catalog(get_action_tools())

        structure = layout.get("structure", [])
        beams     = [el for el in structure if len(el.get("geometry", [])) == 2]
        cols      = [el for el in structure if len(el.get("geometry", [])) == 1]

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

        context_msg = {
            "role": "user",
            "content": (
                f"Context: Layout '{layout.get('layoutId', '?')}' has "
                f"{len(cols)} columns and {len(beams)} beams.{eval_lines}\n\n"
                f"Valid rooms: {[r.get('name') for r in layout.get('rooms', [])]}\n\n"
                f"User request:\n{prompt}\n\n"
                f"Layout summaries:\n"
                f"{json.dumps({'layoutId': layout.get('layoutId'), 'rooms': [{'id': r['id'], 'name': r['name']} for r in layout.get('rooms', [])]})}"
            ),
        }

        result = call_llm(ctx.llm, SYSTEM_PROMPT, [context_msg], tool_catalog)
        return result.get("final_response", "") or "(Agent returned empty response)"
    except Exception as e:
        return f"Agent error: {e}"


# ── Session state ──────────────────────────────────────────────────────────────

def _ensure_session() -> None:
    defaults: dict = {
        "viewer_nonce":    0,
        "history":         [],
        "agent_log":       [],
        "eval_result":     None,
        "eval_alts":       [],
        "state_history":   [],
        "cost_flexibility": None,
        "material":        "RCC",
        "sdl_kNm2":        3.5,
        "live_load_kNm2":  2.0,
        "grid_options":    [],
        "selected_grid":   None,
        "output_log":      [],
        "theme":           "dark",
        "selected_el":     "",
        "compare_mode":    False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ── Page setup ─────────────────────────────────────────────────────────────────

st.set_page_config(page_title="PermanenceOS", layout="wide", initial_sidebar_state="collapsed")
_ensure_session()

_is_light = st.session_state.get("theme", "dark") == "light"

_DARK = """
  [data-testid="stAppViewContainer"]{background:#111318}
  .os-title{font-size:1.25rem;font-weight:700;color:#e0e6f0;letter-spacing:.4px;line-height:2.4rem}
  .stat-chip{display:inline-block;background:#1c2030;border:1px solid #2a3040;border-radius:4px;padding:2px 10px;margin-left:5px;font-size:.78rem;color:#9aa8c0}
  .stat-chip b{color:#c8d8f0}
  .needs-review{background:#5a2a10;color:#ff9860;border-color:#8b4020}
  .panel-hdr{font-size:.78rem;font-weight:700;color:#6a7a9a;letter-spacing:1px;text-transform:uppercase;margin:8px 0 4px}
  .grid-card{border:1px solid #2a3040;border-radius:6px;padding:7px 10px;margin-bottom:4px;background:#141820}
  .grid-card-active{border-color:#4a8adf;background:#1a2840}
  .grid-label{font-size:.86rem;font-weight:700;color:#c0d0e8}
  .grid-spacing{font-size:.73rem;color:#6a7a90}
  .grid-stats{font-size:.76rem;color:#8898b0;margin-top:2px}
  .eval-big{font-size:2.6rem;font-weight:800;line-height:1.1}
  .eval-label{font-size:.70rem;color:#6a7a90;text-transform:uppercase;letter-spacing:.5px}
  .eval-fail{color:#ff5050}.eval-pass{color:#40c040}
  .crit-item{background:#1c2030;border-left:3px solid #cc3030;padding:5px 8px;margin-bottom:4px;border-radius:2px;font-size:.76rem;color:#a0b0c8}
  .pass-badge{background:#1a7a3a;color:#fff;padding:2px 8px;border-radius:4px;font-weight:700;font-size:.78rem}
  .log-entry{background:#1c1f26;border-left:3px solid #4a90d9;padding:5px 8px;margin-bottom:4px;border-radius:3px;font-size:.79rem;color:#a0b4cc}
  .state-pill{display:inline-block;background:#1c2030;color:#8090a8;padding:2px 8px;border-radius:10px;margin:2px;font-size:.74rem}
  .state-pill-active{background:#1e3a60;color:#8abcf0}
  .agent-response{background:#1a1f2e;border-left:3px solid #4a90d9;padding:6px 10px;border-radius:3px;font-size:.80rem;color:#c0d0e8;margin-top:6px}
  .alt-btn{background:#1e2a40;border:1px solid #3a5080;border-radius:4px;padding:4px 8px;margin-bottom:4px;font-size:.76rem;color:#90b8e8;cursor:pointer}
"""
_LIGHT = """
  [data-testid="stAppViewContainer"]{background:#f5f7fa}
  .os-title{font-size:1.25rem;font-weight:700;color:#1a2540;letter-spacing:.4px;line-height:2.4rem}
  .stat-chip{display:inline-block;background:#fff;border:1px solid #d0d8e8;border-radius:4px;padding:2px 10px;margin-left:5px;font-size:.78rem;color:#4a5a70}
  .stat-chip b{color:#1a2a40}
  .needs-review{background:#fff0e8;color:#c04010;border-color:#e08060}
  .panel-hdr{font-size:.78rem;font-weight:700;color:#4a6080;letter-spacing:1px;text-transform:uppercase;margin:8px 0 4px}
  .grid-card{border:1px solid #d0d8e8;border-radius:6px;padding:7px 10px;margin-bottom:4px;background:#fff}
  .grid-card-active{border-color:#3a7adf;background:#eaf2ff}
  .grid-label{font-size:.86rem;font-weight:700;color:#1a2a40}
  .grid-spacing{font-size:.73rem;color:#6a7a90}
  .grid-stats{font-size:.76rem;color:#5a6a80;margin-top:2px}
  .eval-big{font-size:2.6rem;font-weight:800;line-height:1.1}
  .eval-label{font-size:.70rem;color:#6a7a90;text-transform:uppercase;letter-spacing:.5px}
  .eval-fail{color:#cc2020}.eval-pass{color:#208020}
  .crit-item{background:#fff4f4;border-left:3px solid #cc3030;padding:5px 8px;margin-bottom:4px;border-radius:2px;font-size:.76rem;color:#3a4050}
  .pass-badge{background:#d4f0da;color:#1a5a2a;padding:2px 8px;border-radius:4px;font-weight:700;font-size:.78rem}
  .log-entry{background:#f0f5ff;border-left:3px solid #3a80d9;padding:5px 8px;margin-bottom:4px;border-radius:3px;font-size:.79rem;color:#2a3a50}
  .state-pill{display:inline-block;background:#e8edf5;color:#4a5a70;padding:2px 8px;border-radius:10px;margin:2px;font-size:.74rem}
  .state-pill-active{background:#d0e4ff;color:#1a4a90}
  .agent-response{background:#f0f5ff;border-left:3px solid #3a80d9;padding:6px 10px;border-radius:3px;font-size:.80rem;color:#1a2a40;margin-top:6px}
"""
_fail_ct = ".fail-ct{color:#ff6060;font-weight:700}.pass-ct{color:#40c040;font-weight:700}"
if _is_light:
    _fail_ct = ".fail-ct{color:#cc2020;font-weight:700}.pass-ct{color:#208020;font-weight:700}"

st.markdown(
    f"<style>[data-testid='block-container']{{padding-top:.7rem;padding-bottom:.4rem}}"
    f"div[data-testid='stTabs'] button{{font-size:.82rem}}"
    f"{_fail_ct}"
    f"{''.join((_LIGHT if _is_light else _DARK).splitlines())}</style>",
    unsafe_allow_html=True,
)

# ── Load working layout ────────────────────────────────────────────────────────

layout_obj  = _load_working_layout()
n_cols, n_beams = _count_elements(layout_obj)
er = st.session_state.eval_result
has_failures = (
    er is not None
    and (er.get("summary", {}).get("beam_failures", 0) > 0
         or er.get("summary", {}).get("column_failures", 0) > 0)
)

# ── Header ─────────────────────────────────────────────────────────────────────

hdr_title, hdr_stats, hdr_theme, hdr_export = st.columns([2, 5, 1, 1])

with hdr_title:
    st.markdown('<span class="os-title">PermanenceOS</span>', unsafe_allow_html=True)

with hdr_stats:
    review = '<span class="stat-chip needs-review">&#9888; Needs review</span>' if has_failures else ""
    _cf = st.session_state.get("cost_flexibility")
    cost_chip = (
        f'<span class="stat-chip">net <b>${_cf["net_cost_usd"]:+,.0f}</b></span>'
        if _cf else ""
    )
    st.markdown(
        f'<span class="stat-chip"><b>{n_cols}</b> columns</span>'
        f'<span class="stat-chip"><b>{n_beams}</b> beams</span>'
        f'{cost_chip}{review}',
        unsafe_allow_html=True,
    )

with hdr_theme:
    if st.button("Light" if not _is_light else "Dark", use_container_width=True, key="btn_theme"):
        st.session_state.theme = "light" if not _is_light else "dark"
        st.rerun()

with hdr_export:
    st.download_button(
        "Export JSON",
        data=json.dumps(layout_obj, indent=2, ensure_ascii=False),
        file_name="layout_export.json",
        mime="application/json",
        use_container_width=True,
    )

st.divider()

# ── Three-column body ──────────────────────────────────────────────────────────

col_input, col_viewer, col_eval = st.columns([1, 2, 1], gap="medium")

# ══════════════════════════════════════════════════════════════════════════════
# LEFT — Input & Grid Options
# ══════════════════════════════════════════════════════════════════════════════

with col_input:
    # Upload
    st.markdown('<div class="panel-hdr">Layout</div>', unsafe_allow_html=True)
    uploaded = st.file_uploader("Upload Layout JSON", type=["json"])
    if uploaded is not None:
        try:
            loaded = _normalize_layout(json.loads(uploaded.getvalue().decode("utf-8")))
            _write_json(EDITED_LAYOUT_PATH, loaded)
            for k in ("viewer_nonce", "eval_result", "eval_alts", "agent_log",
                      "grid_options", "selected_grid", "cost_flexibility"):
                if k == "viewer_nonce":
                    st.session_state[k] += 1
                else:
                    st.session_state[k] = [] if k in ("eval_alts", "agent_log", "grid_options") else None
            st.success(f"Loaded '{loaded.get('layoutId', 'unnamed')}'")
            st.rerun()
        except Exception as exc:
            st.error(f"Invalid JSON: {exc}")

    if st.button("Reset to default", use_container_width=True, key="btn_reset"):
        if DEFAULT_LAYOUT_PATH.exists():
            _write_json(EDITED_LAYOUT_PATH, _read_json(DEFAULT_LAYOUT_PATH))
        elif EDITED_LAYOUT_PATH.exists():
            EDITED_LAYOUT_PATH.unlink()
        for k in ("viewer_nonce",):
            st.session_state[k] += 1
        for k in ("eval_result", "eval_alts", "agent_log", "state_history",
                  "grid_options", "selected_grid", "output_log", "cost_flexibility"):
            st.session_state[k] = [] if isinstance(st.session_state[k], list) else None
        st.rerun()

    # Material
    st.markdown('<div class="panel-hdr">Material</div>', unsafe_allow_html=True)
    _MAT_LABELS = {"RCC": "Concrete (RCC)", "STEEL": "Steel", "TIMBER": "Timber"}
    mat_choice = st.radio(
        "material_selector",
        options=list(_MAT_LABELS.keys()),
        format_func=lambda k: _MAT_LABELS[k],
        index=list(_MAT_LABELS.keys()).index(st.session_state.material),
        horizontal=True,
        label_visibility="collapsed",
    )
    if mat_choice != st.session_state.material:
        st.session_state.material = mat_choice
        st.session_state.grid_options = []
        st.rerun()

    # Loads
    st.markdown('<div class="panel-hdr">Loads</div>', unsafe_allow_html=True)
    sdl_options = {1.5: "Timber 1.5", 2.5: "Light 2.5", 3.5: "Standard 3.5", 5.0: "Heavy 5.0"}
    sdl_val = st.select_slider(
        "SDL (kN/m²)",
        options=list(sdl_options.keys()),
        value=st.session_state.sdl_kNm2,
        format_func=lambda v: f"{sdl_options[v]} kN/m²",
    )
    if sdl_val != st.session_state.sdl_kNm2:
        st.session_state.sdl_kNm2 = sdl_val

    ll_options = {2.0: "Residential", 3.0: "Office", 5.0: "Retail/Public"}
    ll_val = st.select_slider(
        "LL (kN/m²)",
        options=list(ll_options.keys()),
        value=st.session_state.live_load_kNm2,
        format_func=lambda v: f"{ll_options[v]} {v} kN/m²",
    )
    if ll_val != st.session_state.live_load_kNm2:
        st.session_state.live_load_kNm2 = ll_val

    # JSON preview
    with st.expander("JSON Preview", expanded=False):
        s = json.dumps(layout_obj, indent=2, ensure_ascii=False)
        st.code(s[:2000] + ("\n..." if len(s) > 2000 else ""), language="json")

    # Grid Options
    st.markdown('<div class="panel-hdr">Grid Options</div>', unsafe_allow_html=True)

    c_gen, c_rec = st.columns(2)
    with c_gen:
        gen_clicked = st.button("Generate", use_container_width=True, key="btn_gen")
    with c_rec:
        rec_clicked = st.button("↺ Refresh", use_container_width=True, key="btn_rec")

    if gen_clicked or rec_clicked or (not st.session_state.grid_options and layout_obj.get("structure")):
        with st.spinner("Computing structural grid options…"):
            st.session_state.grid_options = _run_grid_options(layout_obj, st.session_state.material)
        if gen_clicked or rec_clicked:
            st.rerun()

    for opt in st.session_state.grid_options:
        label    = opt["label"]
        spacing  = opt["spacing"]
        failures = opt.get("failures", 0)
        cost_opt = opt.get("cost", 0)
        is_active = st.session_state.selected_grid == label
        fail_cls  = "fail-ct" if failures > 0 else "pass-ct"
        card_cls  = "grid-card grid-card-active" if is_active else "grid-card"

        st.markdown(
            f'<div class="{card_cls}">'
            f'<span class="grid-label">{label}</span>'
            f'<span class="grid-spacing" style="margin-left:6px;">{spacing}m max span</span>'
            f'<div class="grid-stats">'
            f'<span class="{fail_cls}">{failures} failures</span>'
            f' &bull; ${cost_opt:,.0f}'
            f'</div></div>',
            unsafe_allow_html=True,
        )
        if st.button(f"Apply {label}", key=f"grid_{label}", use_container_width=True):
            opt_layout = opt.get("layout", {})
            # Save before snapshot
            if EDITED_LAYOUT_PATH.exists():
                BEFORE_LAYOUT_PATH.write_text(
                    EDITED_LAYOUT_PATH.read_text(encoding="utf-8"), encoding="utf-8"
                )
            _write_json(EDITED_LAYOUT_PATH, opt_layout)
            st.session_state.selected_grid     = label
            st.session_state.viewer_nonce      += 1
            st.session_state.eval_result       = opt.get("evaluation")
            st.session_state.eval_alts         = _get_failure_alternatives(
                opt.get("evaluation") or {}, st.session_state.material
            )
            st.session_state.cost_flexibility  = None
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# CENTER — Three.js Viewer + Tabs
# ══════════════════════════════════════════════════════════════════════════════

with col_viewer:
    tab_model, tab_costs, tab_compare, tab_history, tab_output = st.tabs(
        ["Model", "Costs", "Compare", "History", "Output"]
    )

    # ── Model tab ─────────────────────────────────────────────────────────────
    with tab_model:
        structure = layout_obj.get("structure", [])
        all_ids   = [el["id"] for el in structure]
        col_ids   = [el["id"] for el in structure if len(el.get("geometry", [])) == 1]
        beam_ids  = [el["id"] for el in structure if len(el.get("geometry", [])) == 2]

        # Grid option quick-switch buttons at top
        if st.session_state.grid_options:
            st.markdown('<div class="panel-hdr">Switch option</div>', unsafe_allow_html=True)
            opt_cols = st.columns(min(len(st.session_state.grid_options), 4))
            for idx, (oc, opt) in enumerate(zip(opt_cols, st.session_state.grid_options)):
                with oc:
                    is_sel = st.session_state.selected_grid == opt["label"]
                    label_text = opt["label"]
                    fail_mark = "✗" if opt.get("failures", 0) > 0 else "✓"
                    btn_type = "primary" if is_sel else "secondary"
                    if st.button(f"{fail_mark} {label_text}", key=f"quick_{idx}", use_container_width=True, type=btn_type):
                        opt_layout = opt.get("layout", {})
                        if EDITED_LAYOUT_PATH.exists():
                            BEFORE_LAYOUT_PATH.write_text(
                                EDITED_LAYOUT_PATH.read_text(encoding="utf-8"), encoding="utf-8"
                            )
                        _write_json(EDITED_LAYOUT_PATH, opt_layout)
                        st.session_state.selected_grid    = opt["label"]
                        st.session_state.viewer_nonce    += 1
                        st.session_state.eval_result      = opt.get("evaluation")
                        st.session_state.eval_alts        = _get_failure_alternatives(
                            opt.get("evaluation") or {}, st.session_state.material
                        )
                        st.session_state.cost_flexibility = None
                        st.rerun()

        # Element selector + actions
        row_sel, row_action = st.columns([3, 1]), st.columns([1, 1, 1])
        with row_sel[0]:
            selected_el = st.selectbox(
                "Element",
                options=[""] + all_ids,
                index=([""] + all_ids).index(st.session_state.selected_el)
                      if st.session_state.selected_el in all_ids else 0,
                label_visibility="collapsed",
                key="el_selector",
            )
            st.session_state.selected_el = selected_el

        with row_sel[1]:
            if st.button("Delete", use_container_width=True,
                         disabled=not selected_el, key="btn_del"):
                from nodes.modify import remove_element
                before_str = json.dumps(layout_obj)
                new_str    = remove_element(before_str, selected_el)
                new_layout = json.loads(new_str)
                BEFORE_LAYOUT_PATH.write_text(before_str, encoding="utf-8")
                _write_json(EDITED_LAYOUT_PATH, new_layout)
                st.session_state.viewer_nonce    += 1
                st.session_state.grid_options     = []
                st.session_state.selected_el      = ""
                st.session_state.eval_result      = None
                st.session_state.eval_alts        = []
                st.session_state.cost_flexibility = None
                st.rerun()

        # Upgrade section dropdown
        if selected_el:
            el_obj = next((e for e in structure if e["id"] == selected_el), None)
            if el_obj:
                from nodes.modify import (
                    BEAM_SECTION_UPGRADE, BEAM_DIM_UPGRADE,
                    COL_SECTION_UPGRADE, COL_DIM_UPGRADE,
                )
                is_beam = len(el_obj.get("geometry", [])) == 2
                attrs   = el_obj.get("attributes", {})
                cur_sec = (attrs.get("section")
                           or (f"{attrs.get('width','')}x{attrs.get('depth','')}"
                               if is_beam else attrs.get("dimensions", ""))
                           or "")

                upgrade_options = {}
                if is_beam:
                    if cur_sec in BEAM_SECTION_UPGRADE:
                        nxt, _, _ = BEAM_SECTION_UPGRADE[cur_sec]
                        upgrade_options[f"Upgrade beam → {nxt}"] = nxt
                    if cur_sec in BEAM_DIM_UPGRADE:
                        nxt, _, _ = BEAM_DIM_UPGRADE[cur_sec]
                        upgrade_options[f"Upgrade beam → {nxt}"] = nxt
                else:
                    if cur_sec in COL_SECTION_UPGRADE:
                        nxt, _ = COL_SECTION_UPGRADE[cur_sec]
                        upgrade_options[f"Upgrade col → {nxt}"] = nxt
                    if cur_sec in COL_DIM_UPGRADE:
                        nxt = COL_DIM_UPGRADE[cur_sec]
                        upgrade_options[f"Upgrade col → {nxt}"] = nxt

                if upgrade_options:
                    up_label = st.selectbox(
                        "Upgrade",
                        options=["—"] + list(upgrade_options.keys()),
                        label_visibility="collapsed",
                        key="upgrade_sel",
                    )
                    if up_label != "—" and st.button("Apply upgrade", key="btn_upgrade",
                                                      use_container_width=True):
                        from nodes.modify import upgrade_element_section
                        before_str = json.dumps(layout_obj)
                        new_str    = upgrade_element_section(
                            before_str, selected_el, upgrade_options[up_label]
                        )
                        new_layout = json.loads(new_str)
                        BEFORE_LAYOUT_PATH.write_text(before_str, encoding="utf-8")
                        _write_json(EDITED_LAYOUT_PATH, new_layout)
                        st.session_state.viewer_nonce    += 1
                        st.session_state.eval_result      = None
                        st.session_state.eval_alts        = []
                        st.session_state.cost_flexibility = None
                        st.rerun()

                if is_beam:
                    if st.button("Add midspan column", key="btn_midspan", use_container_width=True):
                        from nodes.modify import add_midspan_column
                        before_str = json.dumps(layout_obj)
                        new_str    = add_midspan_column(
                            before_str, selected_el, st.session_state.material
                        )
                        new_layout = json.loads(new_str)
                        BEFORE_LAYOUT_PATH.write_text(before_str, encoding="utf-8")
                        _write_json(EDITED_LAYOUT_PATH, new_layout)
                        st.session_state.viewer_nonce    += 1
                        st.session_state.eval_result      = None
                        st.session_state.eval_alts        = []
                        st.session_state.cost_flexibility = None
                        st.rerun()

        # Three.js viewer
        if _viewer_is_reachable():
            components.iframe(
                _viewer_url(
                    highlight=st.session_state.selected_el,
                    compare=st.session_state.compare_mode,
                ),
                height=460, scrolling=False,
            )
        else:
            st.warning(
                "Three.js viewer offline — run `python -m http.server 8000` from the repo root."
            )

    # ── Costs tab ─────────────────────────────────────────────────────────────
    with tab_costs:
        st.markdown('<div class="panel-hdr">Cost & Flexibility</div>', unsafe_allow_html=True)
        if st.button("Run cost & flexibility analysis", use_container_width=True, key="btn_cf"):
            before_str = (
                BEFORE_LAYOUT_PATH.read_text(encoding="utf-8")
                if BEFORE_LAYOUT_PATH.exists()
                else json.dumps(layout_obj)
            )
            with st.spinner("Analysing cost and flexibility…"):
                cf = _run_cost_flex(before_str, json.dumps(layout_obj))
            if cf:
                st.session_state.cost_flexibility = cf
            st.rerun()

        cf = st.session_state.get("cost_flexibility")
        if cf is None:
            st.caption("Apply a grid option or make a change, then run analysis.")
        else:
            net = cf.get("net_cost_usd", 0)
            ca  = cf.get("cost_added_usd", 0)
            cs  = cf.get("cost_saved_usd", 0)
            st.metric("Net Cost Change", f"${net:+,.0f}")
            if ca or cs:
                c1, c2 = st.columns(2)
                c1.metric("Added", f"+${ca:,.0f}")
                c2.metric("Saved", f"-${abs(cs):,.0f}")
            st.markdown("---")
            flex    = cf.get("flexibility_score", 0)
            fl_lbl  = cf.get("flexibility_label", "")
            disrupt = cf.get("disruption_score", 0)
            dl_lbl  = cf.get("disruption_label", "")
            penalty = cf.get("spatial_penalty", 0.0)
            st.metric("Flexibility", f"{flex:.1f}/10 — {fl_lbl}")
            st.metric("Disruption",  f"{disrupt}/10 — {dl_lbl}")
            if penalty > 0:
                st.metric("Spatial Penalty", f"{penalty:.2f}  (mid-room column intrusion)")
            if cf.get("summary"):
                st.caption(cf["summary"])

    # ── Compare tab ───────────────────────────────────────────────────────────
    with tab_compare:
        st.markdown('<div class="panel-hdr">Before / After Comparison</div>', unsafe_allow_html=True)

        compare_on = st.toggle("Show comparison overlay", value=st.session_state.compare_mode)
        if compare_on != st.session_state.compare_mode:
            st.session_state.compare_mode = compare_on
            st.session_state.viewer_nonce += 1
            st.rerun()

        if not BEFORE_LAYOUT_PATH.exists():
            st.caption("No before-snapshot yet. Apply a grid option or make a structural change first.")
        else:
            before_layout = json.loads(BEFORE_LAYOUT_PATH.read_text(encoding="utf-8"))
            after_layout  = layout_obj

            def _struct_map(lay: dict) -> dict:
                return {el["id"]: el for el in lay.get("structure", [])}

            bmap  = _struct_map(before_layout)
            amap  = _struct_map(after_layout)
            added   = [k for k in amap if k not in bmap]
            removed = [k for k in bmap if k not in amap]
            changed = [k for k in bmap if k in amap and
                       bmap[k].get("attributes") != amap[k].get("attributes")]

            c_add, c_rem, c_chg = st.columns(3)
            c_add.metric("Added",   f"+{len(added)}")
            c_rem.metric("Removed", f"-{len(removed)}")
            c_chg.metric("Changed", str(len(changed)))

            if removed:
                st.markdown("**Removed** (shown red in viewer):")
                st.write(", ".join(removed[:20]) + ("…" if len(removed) > 20 else ""))
            if added:
                st.markdown("**Added** (shown green in viewer):")
                st.write(", ".join(added[:20]) + ("…" if len(added) > 20 else ""))
            if changed:
                st.markdown("**Section changes:**")
                for eid in changed[:10]:
                    ba = bmap[eid].get("attributes", {})
                    aa = amap[eid].get("attributes", {})
                    diffs = [f"{k}: {ba.get(k,'—')}→{aa.get(k,'—')}"
                             for k in set(list(ba) + list(aa)) if ba.get(k) != aa.get(k)]
                    st.caption(f"**{eid}**: {' | '.join(diffs)}")

            if _viewer_is_reachable():
                components.iframe(_viewer_url(compare=True), height=380, scrolling=False)

    # ── History tab ───────────────────────────────────────────────────────────
    with tab_history:
        st.markdown('<div class="panel-hdr">State History</div>', unsafe_allow_html=True)
        if not st.session_state.state_history:
            st.caption("No states recorded yet.")
        else:
            for i, snap in enumerate(reversed(st.session_state.state_history)):
                real_i = len(st.session_state.state_history) - 1 - i
                is_last = real_i == len(st.session_state.state_history) - 1
                pill_cls = "state-pill state-pill-active" if is_last else "state-pill"
                st.markdown(
                    f'<span class="{pill_cls}">{real_i + 1}. {snap["label"]}</span>',
                    unsafe_allow_html=True,
                )
                if st.button(f"Restore #{real_i + 1}", key=f"restore_{real_i}"):
                    _write_json(EDITED_LAYOUT_PATH, snap["layout_json"])
                    st.session_state.viewer_nonce   += 1
                    st.session_state.eval_result     = snap.get("eval_result")
                    st.session_state.eval_alts       = _get_failure_alternatives(
                        snap.get("eval_result") or {}, st.session_state.material
                    )
                    st.session_state.grid_options    = []
                    st.rerun()

    # ── Output tab ────────────────────────────────────────────────────────────
    with tab_output:
        st.markdown('<div class="panel-hdr">Agent Output</div>', unsafe_allow_html=True)
        if st.session_state.output_log:
            for i, msg in enumerate(reversed(st.session_state.output_log[-10:])):
                n = len(st.session_state.output_log) - i
                st.markdown(
                    f'<div class="agent-response"><b>{n}.</b> {msg}</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.caption("Agent responses appear here.")


# ══════════════════════════════════════════════════════════════════════════════
# RIGHT — Agent Chat + Evaluation
# ══════════════════════════════════════════════════════════════════════════════

with col_eval:

    # ── Agent chat ────────────────────────────────────────────────────────────
    st.markdown('<div class="panel-hdr">Ask Structural Agent</div>', unsafe_allow_html=True)

    with st.form("agent_form", clear_on_submit=True):
        prompt_input = st.text_area(
            "prompt",
            placeholder="e.g. Why is beam A1-B1 failing? What should I do?",
            label_visibility="collapsed",
            height=70,
        )
        submitted = st.form_submit_button("Send", use_container_width=True)

    if submitted and prompt_input.strip():
        with st.spinner("Agent is reasoning…"):
            response = _run_agent_chat(
                prompt_input.strip(),
                layout_obj,
                st.session_state.eval_result,
            )
        st.session_state.output_log.append(response)
        st.session_state.history.append({"prompt": prompt_input, "response": response})
        current_layout = _load_working_layout()
        label = prompt_input[:28] + ("…" if len(prompt_input) > 28 else "")
        st.session_state.state_history.append({
            "label":       label,
            "layout_json": current_layout,
            "eval_result": st.session_state.eval_result,
        })
        st.rerun()

    if st.session_state.output_log:
        last = st.session_state.output_log[-1]
        preview = last[:400] + ("…" if len(last) > 400 else "")
        st.markdown(
            f'<div class="agent-response">{preview}</div>',
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # ── Evaluate ──────────────────────────────────────────────────────────────
    st.markdown('<div class="panel-hdr">Structural Evaluation</div>', unsafe_allow_html=True)

    _mat_now = st.session_state.material
    _sdl_now = st.session_state.sdl_kNm2
    _ll_now  = st.session_state.live_load_kNm2

    if st.button("▶  Evaluate structure", use_container_width=True, key="btn_eval"):
        from nodes.modify import apply_material_override
        layout_str = json.dumps(layout_obj)
        # Apply material so evaluation sees the right sections
        layout_str_mat = apply_material_override(layout_str, _mat_now)
        applied_layout = json.loads(layout_str_mat)

        # Save before snapshot
        BEFORE_LAYOUT_PATH.write_text(layout_str, encoding="utf-8")
        _write_json(EDITED_LAYOUT_PATH, applied_layout)
        st.session_state.viewer_nonce += 1

        with st.spinner("Evaluating structure…"):
            ev = _run_evaluate(layout_str_mat, sdl=_sdl_now, ll=_ll_now)
        if ev:
            st.session_state.eval_result = ev
            st.session_state.eval_alts   = _get_failure_alternatives(ev, _mat_now)
        st.rerun()

    er = st.session_state.eval_result
    if er is None:
        st.caption("Press Evaluate or apply a grid option.")
    else:
        summary = er.get("summary", {})
        bf = summary.get("beam_failures", 0)
        cf = summary.get("column_failures", 0)
        overall = summary.get("overall_PASS", False)

        # Big score
        c_status, c_score = st.columns(2)
        with c_status:
            cls = "eval-pass" if overall else "eval-fail"
            txt = "PASS" if overall else "FAIL"
            st.markdown(
                f'<div class="{cls}" style="font-size:1.8rem;font-weight:800">{txt}</div>'
                f'<div class="eval-label">Overall</div>',
                unsafe_allow_html=True,
            )
        with c_score:
            total_el = max(len(er.get("beams", [])) + len(er.get("columns", [])), 1)
            score    = round(100 * (1 - (bf + cf) / total_el), 1)
            s_cls    = "eval-pass" if score >= 90 else ("eval-fail" if score < 70 else "")
            st.markdown(
                f'<div class="{s_cls}" style="font-size:1.8rem;font-weight:800">{score}</div>'
                f'<div class="eval-label">Score / 100</div>',
                unsafe_allow_html=True,
            )

        c_bf, c_cf = st.columns(2)
        with c_bf:
            bf_cls = "eval-big eval-fail" if bf > 0 else "eval-big eval-pass"
            st.markdown(
                f'<div class="{bf_cls}">{bf}</div>'
                f'<div class="eval-label">Beam failures</div>',
                unsafe_allow_html=True,
            )
        with c_cf:
            cf_cls = "eval-big eval-fail" if cf > 0 else "eval-big eval-pass"
            st.markdown(
                f'<div class="{cf_cls}">{cf}</div>'
                f'<div class="eval-label">Column failures</div>',
                unsafe_allow_html=True,
            )

        # Max span
        beams = er.get("beams", [])
        if beams:
            max_span = max((b.get("span_m", 0) for b in beams), default=0)
            st.caption(f"Max beam span: **{max_span:.2f} m**")

        # Critical items
        st.markdown('<div class="panel-hdr" style="margin-top:6px">Critical checks</div>',
                    unsafe_allow_html=True)

        failing_beams = [b for b in beams
                         if not b.get("bend_PASS") or not b.get("shear_PASS")
                         or not b.get("defl_TL_PASS") or not b.get("defl_LL_PASS")]
        failing_cols  = [c for c in er.get("columns", [])
                         if not c.get("stress_PASS") or not c.get("buckling_PASS")]

        if not failing_beams and not failing_cols:
            st.markdown('<span class="pass-badge">All checks passed ✓</span>', unsafe_allow_html=True)

            # Cost/flex prompt after pass
            st.markdown("---")
            if st.button("Run cost & flexibility", use_container_width=True, key="btn_cf_r"):
                before_str = (
                    BEFORE_LAYOUT_PATH.read_text(encoding="utf-8")
                    if BEFORE_LAYOUT_PATH.exists()
                    else json.dumps(layout_obj)
                )
                with st.spinner("Analysing…"):
                    cf_res = _run_cost_flex(before_str, json.dumps(layout_obj))
                if cf_res:
                    st.session_state.cost_flexibility = cf_res
                st.rerun()
        else:
            for b in failing_beams[:6]:
                checks = []
                if not b.get("bend_PASS"):     checks.append("bending")
                if not b.get("shear_PASS"):    checks.append("shear")
                if not b.get("defl_TL_PASS") or not b.get("defl_LL_PASS"):
                    checks.append("deflection")
                st.markdown(
                    f'<div class="crit-item">'
                    f'<b>{b["id"]}</b> {b.get("span_m", 0):.2f}m · {b.get("section_mm", "?")}'
                    f'<br/>Fails: {", ".join(checks)}'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            for c in failing_cols[:4]:
                checks = []
                if not c.get("stress_PASS"):   checks.append("stress")
                if not c.get("buckling_PASS"): checks.append("buckling")
                st.markdown(
                    f'<div class="crit-item">'
                    f'<b>{c["id"]}</b> {c.get("section_mm", "?")} · SF={c.get("SF_buckling", "?")}'
                    f'<br/>Fails: {", ".join(checks)}'
                    f'</div>',
                    unsafe_allow_html=True,
                )

            # Alternatives as action buttons
            alts = st.session_state.eval_alts
            if alts:
                st.markdown(
                    '<div class="panel-hdr" style="margin-top:8px">Suggested fixes</div>',
                    unsafe_allow_html=True,
                )
                for i, alt in enumerate(alts):
                    if st.button(alt, key=f"alt_{i}", use_container_width=True):
                        before_str = json.dumps(layout_obj)
                        BEFORE_LAYOUT_PATH.write_text(before_str, encoding="utf-8")
                        with st.spinner(f"Applying: {alt[:40]}…"):
                            new_str, new_ev = _apply_alternative(
                                alt, before_str, _mat_now, _sdl_now, _ll_now
                            )
                        if new_str != before_str:
                            new_layout = json.loads(new_str)
                            _write_json(EDITED_LAYOUT_PATH, new_layout)
                            st.session_state.viewer_nonce    += 1
                            st.session_state.cost_flexibility = None
                            label = alt[:30] + ("…" if len(alt) > 30 else "")
                            st.session_state.state_history.append({
                                "label":       label,
                                "layout_json": new_layout,
                                "eval_result": new_ev,
                            })
                        if new_ev is not None:
                            st.session_state.eval_result = new_ev
                            st.session_state.eval_alts   = _get_failure_alternatives(
                                new_ev, _mat_now
                            )
                        st.rerun()

    # Cost/flex summary if available
    _cf = st.session_state.get("cost_flexibility")
    if _cf:
        st.markdown("---")
        st.markdown('<div class="panel-hdr">Cost & Flexibility</div>', unsafe_allow_html=True)
        net = _cf.get("net_cost_usd", 0)
        flex = _cf.get("flexibility_score", 0)
        fl_lbl = _cf.get("flexibility_label", "")
        disrupt = _cf.get("disruption_score", 0)
        c1, c2 = st.columns(2)
        c1.metric("Net cost",    f"${net:+,.0f}")
        c2.metric("Flexibility", f"{flex:.1f}/10")
        st.caption(f"Disruption: {disrupt}/10 · {_cf.get('disruption_label','')}")
        if _cf.get("summary"):
            st.caption(_cf["summary"])
