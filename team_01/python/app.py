from __future__ import annotations

import json
import math
import sys
import urllib.request
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

# ── Paths ─────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LAYOUT_PATH = REPO_ROOT / "layout_input" / "layout_schema.json"
EDITED_LAYOUT_PATH = REPO_ROOT / "team_01_edited_layout.json"
VIEWER_FILE_PATH = REPO_ROOT / "layout_viewer.html"
VIEWER_BASE_URL = "http://127.0.0.1:8000/layout_viewer.html"
PYTHON_DIR = Path(__file__).resolve().parent

if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

# Ensure EDITED_LAYOUT_PATH exists on first run
if not EDITED_LAYOUT_PATH.exists() and DEFAULT_LAYOUT_PATH.exists():
    EDITED_LAYOUT_PATH.write_text(
        DEFAULT_LAYOUT_PATH.read_text(encoding="utf-8"), encoding="utf-8"
    )

# ── Layout helpers ─────────────────────────────────────────────────────────────

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
    raise ValueError("Layout JSON must be an object or a non-empty list of objects")


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


def _viewer_url() -> str:
    layout_stamp = int(EDITED_LAYOUT_PATH.stat().st_mtime_ns) if EDITED_LAYOUT_PATH.exists() else 0
    viewer_stamp = int(VIEWER_FILE_PATH.stat().st_mtime_ns) if VIEWER_FILE_PATH.exists() else 0
    return (
        f"{VIEWER_BASE_URL}"
        f"?v={st.session_state.viewer_nonce}"
        f"&layout={layout_stamp}&viewer={viewer_stamp}"
    )


# ── Cost + element counts ──────────────────────────────────────────────────────

def _quick_cost(layout: dict) -> float:
    total = 0.0
    for el in layout.get("structure", []):
        attrs = el.get("attributes", {})
        mat = attrs.get("material", "RCC").upper()
        geom = el.get("geometry", [])
        if len(geom) == 2:
            length_m = math.dist(geom[0], geom[1])
            w = float(attrs.get("width", 200)) / 1000
            d = float(attrs.get("depth", 300)) / 1000
            vol = w * d * length_m
        else:
            h = float(attrs.get("height", 3.5))
            dims = attrs.get("dimensions", "200x200")
            try:
                wx, dy = (float(p) for p in dims.split("x", 1))
            except Exception:
                wx, dy = 200.0, 200.0
            vol = (wx / 1000) * (dy / 1000) * h
        if "STEEL" in mat:
            total += vol * 7850 * 2.0
        elif "TIMBER" in mat:
            total += vol * 700.0
        else:
            total += vol * 200.0
    return round(total, 2)


def _count_elements(layout: dict) -> tuple[int, int]:
    cols = sum(1 for el in layout.get("structure", []) if len(el.get("geometry", [])) == 1)
    beams = sum(1 for el in layout.get("structure", []) if len(el.get("geometry", [])) == 2)
    return cols, beams


# ── Structural Python helpers (lazy imports) ───────────────────────────────────

def _run_evaluate(layout_json_str: str) -> dict | None:
    try:
        from nodes.evaluate import evaluate_structure
        return evaluate_structure(layout_json_str)
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


# ── Agent integration ──────────────────────────────────────────────────────────

def _run_agent_capture(prompt: str) -> tuple[str, list[dict], dict | None]:
    from _runtime.bootstrap import bootstrap
    from graph import build_graph, _build_initial_state, _format_evaluation

    ctx = bootstrap()
    app_graph = build_graph(ctx)
    initial_state = _build_initial_state(prompt, ctx)
    final_state = app_graph.invoke(initial_state)

    # Persist material override
    material = final_state.get("material_override")
    if material:
        from nodes.modify import DEFAULT_SECTIONS
        sec = DEFAULT_SECTIONS.get(material)
        if sec:
            state_layout = final_state.get("layout_json_string")
            data = json.loads(state_layout) if state_layout else None
            if data is None and ctx.edited_layout_path.exists():
                data = json.loads(ctx.edited_layout_path.read_text(encoding="utf-8"))
            if data:
                is_steel = "STEEL" in material.upper()
                global_beam_sec = sec.get("beam_section", "") if is_steel else ""
                global_col_sec  = sec.get("col_section",  "") if is_steel else ""
                for el in data.get("structure", []):
                    attrs = el.setdefault("attributes", {})
                    attrs["material"] = material
                    is_beam = len(el.get("geometry", [])) == 2
                    cur_sec = attrs.get("section", "")
                    if is_beam and global_beam_sec and cur_sec and cur_sec != global_beam_sec:
                        continue
                    if not is_beam and global_col_sec and cur_sec and cur_sec != global_col_sec:
                        continue
                    if is_beam:
                        attrs["depth"] = str(sec["beam_depth_mm"])
                        attrs["width"] = str(sec["beam_width_mm"])
                        if is_steel and "beam_section" in sec:
                            attrs["section"] = sec["beam_section"]
                        else:
                            attrs.pop("section", None)
                    else:
                        attrs["dimensions"] = sec["col_dims"]
                        if is_steel and "col_section" in sec:
                            attrs["section"] = sec["col_section"]
                        else:
                            attrs.pop("section", None)
                ctx.edited_layout_path.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
                )

    agent_log = final_state.get("agent_log", [])
    eval_result = None
    if final_state.get("evaluation_result"):
        try:
            eval_result = json.loads(final_state["evaluation_result"])
        except Exception:
            pass

    llm_response = (
        final_state.get("final_response")
        or final_state.get("comparison_result")
        or ""
    )
    eval_table = _format_evaluation(final_state.get("evaluation_result"))
    if eval_table and llm_response:
        response = llm_response + "\n\n" + eval_table
    elif eval_table:
        response = eval_table
    else:
        response = llm_response
    if not response and ctx.edited_layout_path.exists():
        response = f"Done. Layout saved to {ctx.edited_layout_path.name}"

    return response, agent_log, eval_result


# ── Session state ──────────────────────────────────────────────────────────────

def _ensure_session() -> None:
    defaults: dict = {
        "viewer_nonce": 0,
        "history": [],
        "agent_log": [],
        "eval_result": None,
        "state_history": [],
        "prev_cost": None,
        "material": "RCC",
        "grid_options": [],
        "selected_grid": None,
        "output_log": [],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ── Page setup ─────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="PermanenceOS",
    layout="wide",
    initial_sidebar_state="collapsed",
)
_ensure_session()

# ── CSS ───────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
  [data-testid="stAppViewContainer"] { background: #111318; }
  [data-testid="block-container"] { padding-top: 0.7rem; padding-bottom: 0.4rem; }
  .os-title {
    font-size: 1.25rem; font-weight: 700; color: #e0e6f0;
    letter-spacing: 0.4px; line-height: 2.4rem;
  }
  .stat-chip {
    display: inline-block; background: #1c2030;
    border: 1px solid #2a3040; border-radius: 4px;
    padding: 2px 10px; margin-left: 5px;
    font-size: 0.78rem; color: #9aa8c0;
  }
  .stat-chip b { color: #c8d8f0; }
  .needs-review { background: #5a2a10; color: #ff9860; border-color: #8b4020; }
  .panel-hdr {
    font-size: 0.78rem; font-weight: 700; color: #6a7a9a;
    letter-spacing: 1px; text-transform: uppercase;
    margin: 8px 0 4px;
  }
  .grid-card {
    border: 1px solid #2a3040; border-radius: 6px;
    padding: 7px 10px; margin-bottom: 4px;
    background: #141820;
  }
  .grid-card-active { border-color: #4a8adf; background: #1a2840; }
  .grid-label { font-size: 0.86rem; font-weight: 700; color: #c0d0e8; }
  .grid-spacing { font-size: 0.73rem; color: #6a7a90; }
  .grid-stats { font-size: 0.76rem; color: #8898b0; margin-top: 2px; }
  .fail-ct { color: #ff6060; font-weight: 700; }
  .pass-ct { color: #40c040; font-weight: 700; }
  .eval-big { font-size: 2.6rem; font-weight: 800; line-height: 1.1; }
  .eval-label {
    font-size: 0.70rem; color: #6a7a90;
    text-transform: uppercase; letter-spacing: 0.5px;
  }
  .eval-fail { color: #ff5050; }
  .eval-pass { color: #40c040; }
  .crit-item {
    background: #1c2030; border-left: 3px solid #cc3030;
    padding: 5px 8px; margin-bottom: 4px;
    border-radius: 2px; font-size: 0.76rem; color: #a0b0c8;
  }
  .pass-badge {
    background: #1a7a3a; color: #fff;
    padding: 2px 8px; border-radius: 4px;
    font-weight: 700; font-size: 0.78rem;
  }
  .log-entry {
    background: #1c1f26; border-left: 3px solid #4a90d9;
    padding: 5px 8px; margin-bottom: 4px;
    border-radius: 3px; font-size: 0.79rem; color: #a0b4cc;
  }
  .state-pill {
    display: inline-block; background: #1c2030; color: #8090a8;
    padding: 2px 8px; border-radius: 10px;
    margin: 2px; font-size: 0.74rem;
  }
  .state-pill-active { background: #1e3a60; color: #8abcf0; }
  div[data-testid="stTabs"] button { font-size: 0.82rem; }
</style>
""", unsafe_allow_html=True)

# ── Load working layout ────────────────────────────────────────────────────────

layout_obj = _load_working_layout()
n_cols, n_beams = _count_elements(layout_obj)
cost = _quick_cost(layout_obj)
er = st.session_state.eval_result
has_failures = (
    er is not None
    and (
        er.get("summary", {}).get("beam_failures", 0) > 0
        or er.get("summary", {}).get("column_failures", 0) > 0
    )
)

# ── Header row ────────────────────────────────────────────────────────────────

hdr_title, hdr_stats, hdr_export = st.columns([2, 6, 1])

with hdr_title:
    st.markdown('<span class="os-title">PermanenceOS</span>', unsafe_allow_html=True)

with hdr_stats:
    review_badge = (
        '<span class="stat-chip needs-review">&#9888; Needs review</span>'
        if has_failures else ""
    )
    st.markdown(
        f'<span class="stat-chip"><b>{n_cols}</b> columns</span>'
        f'<span class="stat-chip"><b>{n_beams}</b> beams</span>'
        f'<span class="stat-chip">&#8364; <b>{cost:,.0f}</b></span>'
        f'{review_badge}',
        unsafe_allow_html=True,
    )

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
# LEFT — Input panel
# ══════════════════════════════════════════════════════════════════════════════

with col_input:
    st.markdown('<div class="panel-hdr">Input</div>', unsafe_allow_html=True)

    # ── Upload JSON ──────────────────────────────────────────────────────────
    uploaded = st.file_uploader("Upload Layout JSON", type=["json"])
    if uploaded is not None:
        try:
            payload = json.loads(uploaded.getvalue().decode("utf-8"))
            loaded = _normalize_layout(payload)
            _write_json(EDITED_LAYOUT_PATH, loaded)
            st.session_state.viewer_nonce += 1
            st.session_state.eval_result = None
            st.session_state.agent_log = []
            st.session_state.grid_options = []
            st.session_state.selected_grid = None
            st.success(f"Loaded '{loaded.get('layoutId', 'unnamed')}'")
            st.rerun()
        except Exception as exc:
            st.error(f"Invalid JSON: {exc}")

    if st.button("Reset to default", use_container_width=True, key="btn_reset"):
        if DEFAULT_LAYOUT_PATH.exists():
            _write_json(EDITED_LAYOUT_PATH, _read_json(DEFAULT_LAYOUT_PATH))
        elif EDITED_LAYOUT_PATH.exists():
            EDITED_LAYOUT_PATH.unlink()
        st.session_state.viewer_nonce += 1
        st.session_state.eval_result = None
        st.session_state.agent_log = []
        st.session_state.state_history = []
        st.session_state.prev_cost = None
        st.session_state.grid_options = []
        st.session_state.selected_grid = None
        st.session_state.output_log = []
        st.rerun()

    # ── Material selector ─────────────────────────────────────────────────────
    st.markdown('<div class="panel-hdr">Material</div>', unsafe_allow_html=True)
    _MAT_LABELS = {"RCC": "Concrete", "STEEL": "Steel", "TIMBER": "Timber"}
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

    # ── JSON viewer ───────────────────────────────────────────────────────────
    with st.expander("JSON Preview", expanded=False):
        layout_str_preview = json.dumps(layout_obj, indent=2, ensure_ascii=False)
        st.code(
            layout_str_preview[:2000] + ("\n..." if len(layout_str_preview) > 2000 else ""),
            language="json",
        )

    # ── Grid Options ──────────────────────────────────────────────────────────
    st.markdown('<div class="panel-hdr">Grid Options</div>', unsafe_allow_html=True)

    if not st.session_state.grid_options:
        with st.spinner("Computing grid variants..."):
            st.session_state.grid_options = _run_grid_options(layout_obj, st.session_state.material)

    if st.button("↺ Recompute", use_container_width=True, key="btn_recompute"):
        with st.spinner("Computing grid variants..."):
            st.session_state.grid_options = _run_grid_options(layout_obj, st.session_state.material)
        st.rerun()

    for opt in st.session_state.grid_options:
        label    = opt["label"]
        spacing  = opt["spacing"]
        failures = opt.get("failures", 0)
        cost_opt = opt.get("cost", 0)
        is_active = st.session_state.selected_grid == label
        fail_cls = "fail-ct" if failures > 0 else "pass-ct"
        card_cls = "grid-card grid-card-active" if is_active else "grid-card"

        st.markdown(
            f'<div class="{card_cls}">'
            f'<span class="grid-label">{label}</span>'
            f'<span class="grid-spacing" style="margin-left:6px;">{spacing}m</span>'
            f'<div class="grid-stats">'
            f'<span class="{fail_cls}">{failures} failures</span>'
            f' &bull; &#8364;{cost_opt:,.0f}'
            f'</div></div>',
            unsafe_allow_html=True,
        )
        if st.button(f"Apply {label}", key=f"grid_{label}", use_container_width=True):
            opt_layout = opt.get("layout", {})
            _write_json(EDITED_LAYOUT_PATH, opt_layout)
            st.session_state.selected_grid = label
            st.session_state.viewer_nonce += 1
            with st.spinner("Evaluating..."):
                ev = _run_evaluate(json.dumps(opt_layout))
            if ev:
                st.session_state.eval_result = ev
            st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# CENTER — Viewer + tabs
# ══════════════════════════════════════════════════════════════════════════════

with col_viewer:
    tab_model, tab_costs, tab_history, tab_output = st.tabs(["Model", "Costs", "History", "Output"])

    with tab_model:
        structure = layout_obj.get("structure", [])
        col_ids = [el["id"] for el in structure if len(el.get("geometry", [])) == 1]

        t_sel, t_del = st.columns([3, 1])
        with t_sel:
            selected_col = st.selectbox(
                "Select Column",
                options=[""] + col_ids,
                label_visibility="collapsed",
            )
        with t_del:
            if st.button("Delete", use_container_width=True, disabled=not selected_col):
                from nodes.modify import remove_element
                new_str = remove_element(json.dumps(layout_obj), selected_col)
                _write_json(EDITED_LAYOUT_PATH, json.loads(new_str))
                st.session_state.viewer_nonce += 1
                st.session_state.grid_options = []
                st.rerun()

        if _viewer_is_reachable():
            components.iframe(_viewer_url(), height=480, scrolling=False)
        else:
            st.warning(
                "Three.js viewer not running — "
                "start with `python -m http.server 8000` from the repo root."
            )

    with tab_costs:
        st.markdown('<div class="panel-hdr">Cost Breakdown</div>', unsafe_allow_html=True)
        total_cost = _quick_cost(layout_obj)
        prev_cost = st.session_state.prev_cost
        delta_str = None
        if prev_cost is not None and prev_cost > 0:
            delta_pct = (total_cost - prev_cost) / prev_cost * 100
            delta_str = f"{delta_pct:+.1f}%"
        st.metric("Total Estimate", f"€ {total_cost:,.0f}", delta=delta_str)

        mat_costs: dict[str, float] = {}
        for el in layout_obj.get("structure", []):
            attrs = el.get("attributes", {})
            mat = attrs.get("material", "RCC").upper()
            geom = el.get("geometry", [])
            if len(geom) == 2:
                length_m = math.dist(geom[0], geom[1])
                w = float(attrs.get("width", 200)) / 1000
                d = float(attrs.get("depth", 300)) / 1000
                vol = w * d * length_m
            else:
                h = float(attrs.get("height", 3.5))
                dims = attrs.get("dimensions", "200x200")
                try:
                    wx, dy = (float(p) for p in dims.split("x", 1))
                except Exception:
                    wx, dy = 200.0, 200.0
                vol = (wx / 1000) * (dy / 1000) * h
            if "STEEL" in mat:
                c = vol * 7850 * 2.0
            elif "TIMBER" in mat:
                c = vol * 700.0
            else:
                c = vol * 200.0
            mat_costs[mat] = mat_costs.get(mat, 0) + c

        if mat_costs:
            for mat_name, mat_cost in sorted(mat_costs.items()):
                pct = mat_cost / total_cost * 100 if total_cost > 0 else 0
                st.write(f"**{mat_name}**: €{mat_cost:,.0f} ({pct:.0f}%)")
        else:
            st.caption("No structural elements yet.")

    with tab_history:
        st.markdown('<div class="panel-hdr">State History</div>', unsafe_allow_html=True)
        if not st.session_state.state_history:
            st.caption("No states recorded yet.")
        else:
            for i, snap in enumerate(st.session_state.state_history):
                is_last = i == len(st.session_state.state_history) - 1
                pill_cls = "state-pill state-pill-active" if is_last else "state-pill"
                st.markdown(
                    f'<span class="{pill_cls}">{i + 1}. {snap["label"]}</span>',
                    unsafe_allow_html=True,
                )
                if st.button(f"Restore {i + 1}", key=f"restore_{i}"):
                    _write_json(EDITED_LAYOUT_PATH, snap["layout_json"])
                    st.session_state.viewer_nonce += 1
                    st.session_state.eval_result = snap.get("eval_result")
                    st.session_state.grid_options = []
                    st.rerun()

    with tab_output:
        st.markdown('<div class="panel-hdr">Agent Output</div>', unsafe_allow_html=True)
        if st.session_state.output_log:
            for i, msg in enumerate(reversed(st.session_state.output_log[-10:])):
                st.markdown(
                    f'<div class="agent-response"><b>{len(st.session_state.output_log) - i}.</b> {msg}</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.caption("Agent responses appear here after running a prompt.")

        if st.session_state.agent_log:
            st.markdown(
                '<div class="panel-hdr" style="margin-top:10px;">Reasoning Log</div>',
                unsafe_allow_html=True,
            )
            for entry in st.session_state.agent_log:
                cycle_label = f"Cycle {entry.get('cycle', '?')}"
                result_text = entry.get("result", "")
                next_text   = entry.get("next", "")
                preview = result_text[:100] + ("..." if len(result_text) > 100 else "")
                st.markdown(
                    f'<div class="log-entry">'
                    f'<strong>{cycle_label}</strong> &rarr; <em>{next_text}</em><br/>'
                    f'{preview}'
                    f'</div>',
                    unsafe_allow_html=True,
                )

# ══════════════════════════════════════════════════════════════════════════════
# RIGHT — Evaluation panel (chat input at top, then evaluate button, then results)
# ══════════════════════════════════════════════════════════════════════════════

with col_eval:
    # ── Structural agent chat ─────────────────────────────────────────────────
    st.markdown('<div class="panel-hdr">Ask Structural Agent</div>', unsafe_allow_html=True)

    with st.form("agent_form", clear_on_submit=True):
        prompt_input = st.text_area(
            "prompt",
            placeholder="e.g. Add a structural grid and evaluate it...",
            label_visibility="collapsed",
            height=80,
        )
        submitted = st.form_submit_button("Send to Agent", use_container_width=True)

    prompt = prompt_input if submitted and prompt_input.strip() else None
    if prompt:
        with st.spinner("Agent is reasoning..."):
            try:
                response, agent_log, eval_result = _run_agent_capture(prompt)
            except Exception as exc:
                response = f"Agent error: {exc}"
                agent_log = []
                eval_result = None

        st.session_state.prev_cost = _quick_cost(_load_working_layout())
        st.session_state.viewer_nonce += 1
        st.session_state.agent_log = agent_log
        st.session_state.output_log.append(response)
        st.session_state.grid_options = []
        if eval_result is not None:
            st.session_state.eval_result = eval_result

        st.session_state.history.append({"prompt": prompt, "response": response})

        current_layout = _load_working_layout()
        label = prompt[:28] + ("..." if len(prompt) > 28 else "")
        st.session_state.state_history.append({
            "label": label,
            "layout_json": current_layout,
            "eval_result": eval_result,
        })

        st.rerun()

    # Show last agent response inline
    if st.session_state.output_log:
        last = st.session_state.output_log[-1]
        preview = last[:300] + ("..." if len(last) > 300 else "")
        st.markdown(
            f'<div class="agent-response">{preview}</div>',
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # ── Evaluation ────────────────────────────────────────────────────────────
    st.markdown('<div class="panel-hdr">Evaluation</div>', unsafe_allow_html=True)

    if st.button("Evaluate now", use_container_width=True, key="btn_eval"):
        with st.spinner("Evaluating structure..."):
            ev = _run_evaluate(json.dumps(layout_obj))
        if ev:
            st.session_state.eval_result = ev
            st.rerun()

    er = st.session_state.eval_result
    if er is None:
        st.caption("Press 'Evaluate now' or send a prompt to the agent.")
    else:
        summary = er.get("summary", {})
        bf = summary.get("beam_failures", 0)
        cf = summary.get("column_failures", 0)

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

        st.markdown("---")

        beams = er.get("beams", [])
        if beams:
            max_span = max((b.get("span_m", 0) for b in beams), default=0)
            st.metric("Max span", f"{max_span:.2f} m")

        score = summary.get("score")
        if score is None:
            total_el = max(len(beams) + len(er.get("columns", [])), 1)
            score = round(100 * (1 - (bf + cf) / total_el), 1)
        st.metric("Score", score)

        st.markdown(
            '<div class="panel-hdr" style="margin-top:8px;">Critical Checks</div>',
            unsafe_allow_html=True,
        )

        failing_beams = [
            b for b in beams
            if not b.get("bend_PASS") or not b.get("shear_PASS")
            or not b.get("defl_TL_PASS") or not b.get("defl_LL_PASS")
        ]
        failing_cols = [
            c for c in er.get("columns", [])
            if not c.get("stress_PASS") or not c.get("buckling_PASS")
        ]

        if not failing_beams and not failing_cols:
            st.markdown('<span class="pass-badge">All checks passed</span>', unsafe_allow_html=True)
        else:
            for b in failing_beams[:8]:
                checks = []
                if not b.get("bend_PASS"):
                    checks.append("bending")
                if not b.get("shear_PASS"):
                    checks.append("shear")
                if not b.get("defl_TL_PASS") or not b.get("defl_LL_PASS"):
                    checks.append("deflection")
                st.markdown(
                    f'<div class="crit-item">'
                    f'<b>{b["id"]}</b> &nbsp;'
                    f'{b.get("span_m", 0):.2f}m &bull; {b.get("section_mm", "?")}'
                    f'<br/>Fails: {", ".join(checks)}'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            for c in failing_cols[:5]:
                checks = []
                if not c.get("stress_PASS"):
                    checks.append("stress")
                if not c.get("buckling_PASS"):
                    checks.append("buckling")
                st.markdown(
                    f'<div class="crit-item">'
                    f'<b>{c["id"]}</b> &nbsp; {c.get("section_mm", "?")}'
                    f'<br/>Fails: {", ".join(checks)}'
                    f'</div>',
                    unsafe_allow_html=True,
                )
