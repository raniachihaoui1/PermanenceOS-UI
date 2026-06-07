
# ─── query params ─────────────────────────────────────────────────────────────
_pending_sel = st.query_params.get("_sel", "")
if _pending_sel != st.session_state.get("_last_sel_applied", "\x00"):
    st.session_state.selected_el = _pending_sel
    st.session_state["_last_sel_applied"] = _pending_sel

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
    _BG="#071a1a"; _SB="#091f1f"; _CARD="#0d2828"; _ACC="#2ac0c0"; _ACC2="#40d090"
    _BORD="#1a4040"; _TEXT="#c8eeed"; _MUT="#5a9090"; _DIM="#3a6060"
    _FAIL="#ff5050"; _PASS_C="#40d090"; _PASS_BG="#0a3020"; _FAIL_BG="#300a0a"
    _CHAT_Q="#0a3030"; _CHAT_A="#071a1a"; _NUM1_BG=_ACC; _NUM1_C="#071a1a"
    _NUM2_BG="#c07020"; _NUM3_BG="#3070a0"
    _HIGH_BG="#0d2e0d"; _HIGH_C="#60d060"
    _MED_BG="#2e2400";  _MED_C="#d0a020"
    _LOW_BG="#0a1e30";  _LOW_C="#40a0c8"
    _LOAD_BG="#0d2020"; _SNAP_BG="#0d2020"

_CSS = f"""
html,body,[data-testid="stApp"],[data-testid="stAppViewContainer"],[data-testid="stMain"]{{
  background:{_BG}!important;font-family:'Inter','Segoe UI',system-ui,sans-serif!important;font-size:13px!important}}
[data-testid="block-container"]{{padding:.3rem 1rem .2rem!important}}
section[data-testid="stSidebar"]{{background:{_SB}!important;border-right:1px solid {_BORD}!important}}
section[data-testid="stSidebar"]>div:first-child{{padding:14px 14px 10px!important}}
section[data-testid="stSidebar"] p,section[data-testid="stSidebar"] label{{color:{_TEXT}!important}}
section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p{{color:{_MUT}!important;font-size:.70rem!important}}
[data-testid="stHeader"]{{background:{_BG}!important;border-bottom:1px solid {_BORD}!important}}
[data-testid="stTabs"] [data-baseweb="tab-list"]{{background:transparent!important;border-bottom:1px solid {_BORD}!important;gap:0!important;padding:0!important}}
[data-testid="stTabs"] [data-baseweb="tab"]{{color:{_MUT}!important;font-size:.76rem!important;font-weight:700!important;letter-spacing:1.4px!important;text-transform:uppercase!important;padding:10px 22px!important;border-bottom:2px solid transparent!important;background:transparent!important}}
[data-testid="stTabs"] [aria-selected="true"]{{color:{_ACC}!important;border-bottom:2px solid {_ACC}!important}}
[data-testid="stTabs"] [data-baseweb="tab-border"]{{display:none!important}}
[data-testid="stTabPanel"]{{padding-top:6px!important}}
[data-testid="stForm"]{{background:{_CARD}!important;border:1px solid {_BORD}!important;border-radius:8px!important;padding:8px!important}}
[data-testid="stTextArea"] textarea{{background:{_CARD}!important;color:{_TEXT}!important;border-color:{_BORD}!important;font-size:.73rem!important}}
[data-testid="stTextInput"] input{{background:{_CARD}!important;color:{_TEXT}!important;border-color:{_BORD}!important}}
[data-baseweb="select"]>div{{background:{_CARD}!important;border-color:{_BORD}!important;color:{_TEXT}!important}}
[data-baseweb="popover"] [role="listbox"]{{background:{_CARD}!important}}
[data-baseweb="popover"] [role="option"]{{color:{_TEXT}!important}}
[data-testid="stExpander"] details{{background:{_CARD}!important;border:1px solid {_BORD}!important;border-radius:6px!important}}
[data-testid="stExpander"] summary{{color:{_ACC}!important;font-size:.72rem!important;font-weight:600!important}}
[data-testid="stFileUploader"] section{{background:{_CARD}!important;border-color:{_BORD}!important}}
[data-testid="stFileUploaderDropzoneInstructions"]{{display:none!important}}
[data-testid="stFileUploaderDropzone"]{{min-height:auto!important;padding:5px 10px!important;background:{_CARD}!important;border-color:{_BORD}!important}}
[data-testid="stRadio"] label p{{color:{_TEXT}!important;font-size:.72rem!important}}
[data-testid="stCheckbox"] label p{{color:{_TEXT}!important;font-size:.72rem!important}}
[data-testid="stSlider"] [data-baseweb="slider"] [role="slider"]{{background:{_ACC}!important}}
p,label{{color:{_TEXT}}}
[data-testid="stMarkdown"] p{{color:{_TEXT}}}
small,[data-testid="stCaption"] p{{color:{_MUT}!important;font-size:.64rem!important}}
[data-testid="stMetricValue"]{{color:{_TEXT}!important;font-size:.95rem!important}}
[data-testid="stMetricLabel"] p{{color:{_MUT}!important;font-size:.62rem!important}}
hr{{border-color:{_BORD}!important;margin:8px 0!important}}
button[kind="primary"]{{background:{_ACC}!important;color:{"#fff" if _is_light else "#071a1a"}!important;border:none!important;font-weight:700!important;font-size:.72rem!important;border-radius:6px!important}}
button[kind="secondary"]{{background:transparent!important;color:{_TEXT}!important;border:1px solid {_BORD}!important;font-size:.72rem!important;border-radius:6px!important}}
.sb-brand{{font-size:.88rem;font-weight:800;color:{_ACC};letter-spacing:.8px;line-height:1.1}}
.sb-sub{{font-size:.60rem;color:{_MUT};margin-bottom:10px}}
.sb-section{{font-size:.58rem;font-weight:700;color:{_ACC};letter-spacing:1.5px;text-transform:uppercase;margin:12px 0 5px;display:flex;align-items:center;gap:6px}}
.sb-section::after{{content:'';flex:1;height:1px;background:{_BORD}}}
.sb-filename{{font-size:.71rem;font-weight:600;color:{_TEXT};margin:3px 0 1px}}
.sb-success{{font-size:.63rem;color:{_ACC2};font-weight:600}}
.beta{{background:{"#d4f0ee" if _is_light else "#0a3030"};color:{_ACC};font-size:.54rem;font-weight:700;padding:1px 5px;border-radius:3px;vertical-align:middle;margin-left:4px;text-transform:uppercase;letter-spacing:.5px;border:1px solid {_BORD}}}
.load-row{{display:flex;justify-content:space-between;font-size:.66rem;padding:3px 0;border-bottom:1px solid {_BORD};color:{_MUT}}}
.load-row b{{color:{_TEXT};font-weight:600}}
.load-block{{background:{_LOAD_BG};border:1px solid {_BORD};border-radius:6px;padding:8px 10px}}
.page-hdr{{display:flex;align-items:center;gap:4px;padding:4px 0 3px}}
.hdr-lid{{font-size:.72rem;color:{_MUT};margin-right:6px}}
.stat-chip{{display:inline-block;background:{"#e8f4f4" if _is_light else "#0d3030"};border:1px solid {_BORD};border-radius:4px;padding:2px 7px;margin-left:3px;font-size:.64rem;color:{_MUT}}}
.stat-chip b{{color:{_ACC}}}
.needs-review{{background:{"#fff0e8" if _is_light else "#3a1a08"}!important;color:{"#c04010" if _is_light else "#ff9860"}!important;border-color:{"#d08060" if _is_light else "#7a4020"}!important}}
.step-bar{{display:flex;align-items:center;gap:0;overflow:hidden;padding:2px 0}}
.stp{{display:flex;align-items:center;gap:4px;padding:3px 5px;white-space:nowrap;min-width:0}}
.stp-n{{display:inline-flex;width:20px;height:20px;border-radius:50%;font-size:.58rem;font-weight:800;align-items:center;justify-content:center;flex-shrink:0}}
.stp-done .stp-n{{background:{_ACC};color:{"#fff" if _is_light else "#071a1a"}}}
.stp-active .stp-n{{background:{"#fff" if _is_light else "#0d2828"};color:{_ACC};border:2px solid {_ACC}}}
.stp-todo .stp-n{{background:{"#dde8e8" if _is_light else "#1a3030"};color:{_MUT}}}
.stp-lbl{{font-size:.63rem;font-weight:600}}
.stp-done .stp-lbl{{color:{_TEXT}}}
.stp-active .stp-lbl{{color:{_ACC};font-weight:700}}
.stp-todo .stp-lbl{{color:{_MUT}}}
.stp-sub{{font-size:.54rem;color:{_MUT}}}
.stp-arr{{color:{_BORD};font-size:.65rem;margin:0 0px;flex-shrink:0}}
.plan-legend{{display:flex;gap:12px;padding:5px 4px 3px;flex-wrap:wrap}}
.leg-item{{display:flex;align-items:center;gap:4px;font-size:.61rem;color:{_MUT}}}
.leg-col{{width:9px;height:9px;border-radius:50%;background:{_ACC};flex-shrink:0}}
.leg-beam{{width:14px;height:3px;background:{_ACC2};flex-shrink:0;border-radius:1px}}
.leg-wall{{width:14px;height:3px;background:{"#889898" if _is_light else "#445858"};flex-shrink:0}}
.leg-dash{{width:14px;height:0;border-top:2px dashed {_MUT};flex-shrink:0}}
.stat-bar{{background:{_CARD};border:1px solid {_BORD};border-radius:6px;padding:6px 12px;display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-top:4px}}
.sb-i{{font-size:.63rem;color:{_MUT};white-space:nowrap}}
.sb-i b{{color:{_TEXT};font-weight:600}}
.sb-pass{{background:{_PASS_BG};color:{_PASS_C};font-size:.61rem;font-weight:700;padding:2px 8px;border-radius:10px;white-space:nowrap}}
.sb-fail{{background:{_FAIL_BG};color:{_FAIL};font-size:.61rem;font-weight:700;padding:2px 8px;border-radius:10px;white-space:nowrap}}
.sb-pend{{color:{_MUT};font-size:.61rem}}
.panel-hdr{{font-size:.58rem;font-weight:700;color:{_ACC};letter-spacing:1.4px;text-transform:uppercase;margin:4px 0 7px;display:flex;align-items:center;gap:6px}}
.panel-hdr::after{{content:'';flex:1;height:1px;background:{_BORD}}}
.rec-card{{background:{_CARD};border:1px solid {_BORD};border-radius:8px;padding:12px;margin-bottom:9px}}
.rec-top{{display:flex;align-items:center;gap:6px;margin-bottom:4px}}
.rec-n{{display:inline-flex;width:22px;height:22px;border-radius:50%;font-size:.66rem;font-weight:800;align-items:center;justify-content:center;flex-shrink:0;color:#fff}}
.rec-title{{font-size:.78rem;font-weight:700;color:{_TEXT};flex:1;min-width:0}}
.imp-high{{background:{_HIGH_BG};color:{_HIGH_C};font-size:.54rem;font-weight:700;padding:2px 6px;border-radius:8px;text-transform:uppercase;letter-spacing:.3px;white-space:nowrap}}
.imp-med{{background:{_MED_BG};color:{_MED_C};font-size:.54rem;font-weight:700;padding:2px 6px;border-radius:8px;text-transform:uppercase;letter-spacing:.3px;white-space:nowrap}}
.imp-low{{background:{_LOW_BG};color:{_LOW_C};font-size:.54rem;font-weight:700;padding:2px 6px;border-radius:8px;text-transform:uppercase;letter-spacing:.3px;white-space:nowrap}}
.rec-desc{{font-size:.65rem;color:{_MUT};line-height:1.4;margin-bottom:8px}}
.rec-metrics{{display:flex;gap:0;border-top:1px solid {_BORD};padding-top:8px;margin-bottom:8px}}
.rec-met{{flex:1;text-align:center}}
.rec-met-lbl{{font-size:.56rem;color:{_MUT};text-transform:uppercase;letter-spacing:.3px;margin-bottom:1px}}
.rec-met-pos{{font-size:.70rem;font-weight:700;color:{_PASS_C}}}
.rec-met-neg{{font-size:.70rem;font-weight:700;color:{_FAIL}}}
.chat-q{{background:{_CHAT_Q};border-left:3px solid {_ACC};border-radius:3px;padding:4px 7px;margin-bottom:3px;font-size:.65rem;color:{_TEXT};line-height:1.4}}
.chat-a{{background:{_CHAT_A};border-left:3px solid {_ACC2};border-radius:3px;padding:4px 7px;margin-bottom:3px;font-size:.65rem;color:{_TEXT};line-height:1.4}}
.agent-resp{{background:{_CHAT_Q};border-left:3px solid {_ACC};padding:7px 10px;border-radius:3px;font-size:.70rem;color:{_TEXT};line-height:1.5;margin-top:5px}}
.crit-item{{background:{"#fff4f4" if _is_light else "#200808"};border-left:3px solid {"#cc2020" if _is_light else "#aa2020"};padding:4px 7px;margin-bottom:3px;border-radius:2px;font-size:.66rem;color:{_TEXT};cursor:pointer}}
.pass-badge{{background:{_PASS_BG};color:{_PASS_C};padding:2px 8px;border-radius:4px;font-weight:700;font-size:.67rem;display:inline-block;margin:3px 0}}
.hist-item{{display:flex;gap:8px;margin-bottom:6px;padding-bottom:6px;border-bottom:1px solid {_BORD}}}
.hist-dot{{width:7px;height:7px;border-radius:50%;background:{_ACC};margin-top:4px;flex-shrink:0}}
.hist-label{{font-size:.70rem;color:{_TEXT};font-weight:600}}
.hist-sub{{font-size:.60rem;color:{_MUT}}}
.log-entry{{background:{_CARD};border-left:3px solid {_ACC};padding:4px 7px;margin-bottom:3px;border-radius:3px;font-size:.67rem;color:{_TEXT}}}
.grid-card{{border:1px solid {_BORD};border-radius:6px;padding:6px 9px;margin-bottom:4px;background:{_CARD}}}
.grid-card-active{{border-color:{_ACC};background:{"#ddf4f4" if _is_light else "#0d3030"}}}
.grid-label{{font-size:.75rem;font-weight:700;color:{_TEXT}}}
.grid-spacing{{font-size:.64rem;color:{_MUT}}}
.fail-ct{{color:{_FAIL};font-weight:700}}.pass-ct{{color:{_PASS_C};font-weight:700}}
.snap-pill{{display:inline-block;background:{_SNAP_BG};border:1px solid {_BORD};color:{_MUT};padding:2px 8px;border-radius:10px;margin:2px;font-size:.63rem}}
.snap-pill-active{{border-color:{_ACC};color:{_ACC};font-weight:700}}
.cmp-card-hdr{{background:{"#eef7f7" if _is_light else "#0d2828"};border-bottom:1px solid {_BORD};padding:6px 11px;display:flex;justify-content:space-between;align-items:center}}
.cmp-title{{font-size:.70rem;font-weight:700;color:{_TEXT}}}
.badge-curr{{background:{"#d0ecec" if _is_light else "#0d3030"};color:{_ACC};font-size:.57rem;padding:2px 7px;border-radius:8px}}
.badge-opt{{background:{_HIGH_BG};color:{_HIGH_C};font-size:.57rem;padding:2px 7px;border-radius:8px}}
.insight-card{{background:{_CARD};border:1px solid {_BORD};border-radius:8px;padding:10px 12px;margin-bottom:6px;display:flex;align-items:flex-start;gap:10px}}
.insight-ico{{font-size:1.0rem;margin-top:1px}}
.insight-lbl{{font-size:.57rem;color:{_MUT};text-transform:uppercase;letter-spacing:.3px}}
.insight-opt{{font-size:.73rem;font-weight:700;color:{_TEXT}}}
.insight-det{{font-size:.61rem;color:{_MUT}}}
.rec-box{{background:{_HIGH_BG};border:1px solid {"#90c8a0" if _is_light else "#1a5020"};border-radius:8px;padding:11px;margin-top:7px}}
.rec-box-lbl{{font-size:.57rem;color:{_HIGH_C};text-transform:uppercase;letter-spacing:1px;font-weight:700;margin-bottom:4px}}
.rec-box-txt{{font-size:.67rem;color:{_TEXT};line-height:1.5}}
.cmp-tbl{{width:100%;border-collapse:collapse;border:1px solid {_BORD};border-radius:8px;overflow:hidden}}
.cmp-tbl th{{padding:6px 10px;background:{_CARD};border-bottom:1px solid {_BORD};font-size:.63rem;color:{_MUT};text-transform:uppercase;letter-spacing:.6px;text-align:center}}
.cmp-tbl th:first-child{{text-align:left}}
.cmp-tbl td{{padding:6px 10px;font-size:.70rem;text-align:center;border-bottom:1px solid {_BORD}}}
.cmp-tbl td:first-child{{text-align:left;color:{_MUT};font-size:.63rem;font-weight:600}}
.cmp-best{{color:{_PASS_C};font-weight:700}}
.cmp-norm{{color:{_TEXT};font-weight:600}}
/* ── Tighten layout without breaking scroll ────────────────────────────── */
[data-testid="stAppViewContainer"]{{overflow-x:hidden!important}}
[data-testid="stMainBlockContainer"]{{padding:.4rem .8rem .4rem!important;max-width:100%!important}}
[data-testid="block-container"]{{padding:.4rem .8rem .4rem!important;max-width:100%!important}}
/* ── Static sidebar — hide ALL collapse/expand arrows ──────────────────── */
[data-testid="collapsedControl"],
[data-testid="stSidebarCollapseButton"],
[data-testid="stSidebarCollapsedControl"],
button[aria-label="Close sidebar"],
button[aria-label="Open sidebar"],
button[aria-label="collapse"],
button[aria-label="expand"]{{display:none!important;pointer-events:none!important}}
/* ── Sidebar fixed 280 px ──────────────────────────────────────────────── */
section[data-testid="stSidebar"]{{
  width:280px!important;min-width:280px!important;max-width:280px!important;
  transform:translateX(0)!important;transition:none!important;visibility:visible!important}}
section[data-testid="stSidebar"]>div:first-child{{
  width:280px!important;padding:12px 12px 10px!important;overflow-y:auto!important}}
/* ── Collapse toggle button ────────────────────────────────────────────── */
button[data-testid="baseButton-secondary"][kind="secondary"]{{
  font-size:.68rem!important;padding:2px 6px!important}}
.inp-toggle button{{
  padding:1px 6px!important;min-height:unset!important;font-size:.72rem!important;
  background:transparent!important;border:1px solid {_BORD}!important;
  color:{_MUT}!important;border-radius:4px!important;line-height:1.4!important}}
/* ── Grid options bar ──────────────────────────────────────────────────── */
.grid-opt-bar{{display:flex;align-items:center;gap:6px;padding:5px 0 5px;
  border-bottom:1px solid {_BORD};margin-bottom:4px;flex-wrap:wrap}}
.grid-opt-lbl{{font-size:.60rem;font-weight:700;color:{_MUT};
  text-transform:uppercase;letter-spacing:1.2px;white-space:nowrap;padding-right:4px}}
.gobar-active{{background:{_ACC}!important;color:{"#071a1a" if not _is_light else "#fff"}!important;
  border-color:{_ACC}!important;font-weight:700!important}}
.gobar-inactive{{background:{_CARD}!important;color:{_MUT}!important;
  border:1px solid {_BORD}!important;font-weight:600!important}}
"""

st.markdown(f"<style>{_CSS}</style>", unsafe_allow_html=True)

# ─── JS bridge ────────────────────────────────────────────────────────────────
components.html("""
<script>
(function(){
  if(window._selBridgeReady)return;window._selBridgeReady=true;
  window.parent.addEventListener('message',function(ev){
    if(!ev.data||ev.data.type!=='selectElement')return;
    var eid=ev.data.elementId||'';
    var url=new URL(window.parent.location.href);
    var prev=url.searchParams.get('_sel')||'';
    if(eid===prev)return;
    if(eid){url.searchParams.set('_sel',eid);}else{url.searchParams.delete('_sel');}
    window.parent.history.replaceState(null,'',url.toString());
    window.parent.dispatchEvent(new PopStateEvent('popstate',{state:null}));
    setTimeout(function(){window.parent.dispatchEvent(new PopStateEvent('popstate',{state:null}));},40);
  });
})();
</script>""", height=1)

# ─── layout data ──────────────────────────────────────────────────────────────
layout_obj      = _load_working_layout()
n_cols, n_beams = _count_elements(layout_obj)
er              = st.session_state.eval_result
_sm             = (er or {}).get("summary", {})
_has_fail       = _sm.get("beam_failures", 0) > 0 or _sm.get("column_failures", 0) > 0
_mat_now        = st.session_state.material
_sdl_now        = st.session_state.sdl_kNm2
_ll_now         = st.session_state.live_load_kNm2

_REC_DELTAS = [(7.22, 6.5, 1.85), (3.44, 2.80, 0.90), (1.65, 1.20, 0.43)]

# ─── SIDEBAR ──────────────────────────────────────────────────────────────────
prompt_input = ""
submitted    = False

with st.sidebar:
    if _logo_b64:
        st.markdown(
            f'<img src="data:image/png;base64,{_logo_b64}" style="height:26px;margin-bottom:4px">',
            unsafe_allow_html=True,
        )
    st.markdown(
        '<div class="sb-brand">PermanenceOS</div>'
        '<div class="sb-sub">AI-Powered Structural Design</div>',
        unsafe_allow_html=True,
    )

    # ── INPUTS (collapsible) ──────────────────────────────────────────────────
    _inp_exp = st.session_state.get("inputs_expanded", True)
    _lid     = layout_obj.get("layoutId", "")   # always defined for page header use
    _ih1, _ih2 = st.columns([4, 1], gap="small")
    with _ih1:
        st.markdown('<div class="sb-section">Inputs</div>', unsafe_allow_html=True)
    with _ih2:
        if st.button("▼" if _inp_exp else "▶", key="btn_inp_toggle",
                     use_container_width=True, help="Collapse/expand inputs panel"):
            st.session_state.inputs_expanded = not _inp_exp
            st.rerun()

    if _inp_exp:
        st.markdown("**Upload Model**", help="Revit, IFC, JSON layouts")
        _upload = st.file_uploader(
            "layout", type=["json"], label_visibility="collapsed", key="sb_uploader"
        )
        if _upload is not None:
            try:
                _loaded = _normalize_layout(json.loads(_upload.getvalue().decode("utf-8")))
                _write_json(EDITED_LAYOUT_PATH, _loaded)
                for _k in ("eval_result", "eval_alts", "agent_log", "grid_options",
                           "selected_grid", "cost_flexibility", "last_comparison"):
                    st.session_state[_k] = (
                        [] if isinstance(st.session_state.get(_k), list) else None)
                st.session_state.viewer_nonce += 1
                st.rerun()
            except Exception as _exc:
                st.error(f"Invalid JSON: {_exc}")

        if _lid:
            st.markdown(
                f'<div class="sb-filename">{_lid}</div>'
                f'<div class="sb-success">✓ Model loaded successfully</div>',
                unsafe_allow_html=True,
            )

        st.divider()
        st.markdown("**Define Loads**")
        st.caption("Manage load cases")

        _MAT_LABELS = {"RCC": "Concrete", "STEEL": "Steel", "TIMBER": "Timber"}
        mat_choice = st.radio(
            "Material", list(_MAT_LABELS.keys()),
            format_func=lambda k: _MAT_LABELS[k],
            index=list(_MAT_LABELS.keys()).index(_mat_now),
            horizontal=True, label_visibility="collapsed",
        )
        if mat_choice != _mat_now:
            st.session_state.material     = mat_choice
            st.session_state.grid_options = []
            st.rerun()

        _sdl_opts = {1.5: "1.5", 2.5: "2.5", 3.5: "3.5", 5.0: "5.0"}
        _sdl_v = st.select_slider(
            "Dead Load SDL (kN/m²)", list(_sdl_opts.keys()),
            value=_sdl_now, format_func=lambda v: f"{v} kN/m²",
        )
        if _sdl_v != _sdl_now:
            st.session_state.sdl_kNm2 = _sdl_v

        _ll_opts = {2.0: "2.0", 3.0: "3.0", 5.0: "5.0"}
        _ll_v = st.select_slider(
            "Live Load LL (kN/m²)", list(_ll_opts.keys()),
            value=_ll_now, format_func=lambda v: f"{v} kN/m²",
        )
        if _ll_v != _ll_now:
            st.session_state.live_load_kNm2 = _ll_v

        st.divider()
        st.markdown('<div class="sb-section">Load Summary</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="load-block">'
            f'<div class="load-row"><span>Dead Load</span><b>{_sdl_now:.2f} kN/m²</b></div>'
            f'<div class="load-row"><span>Live Load</span><b>{_ll_now:.2f} kN/m²</b></div>'
            f'<div class="load-row"><span>Wind Load</span><b>0.85 kN/m²</b></div>'
            f'<div class="load-row" style="border:none"><span>Seismic Load</span><b>1.20 kN/m²</b></div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        st.caption("Manage Load Cases →")

        st.divider()
        _uc1, _uc2 = st.columns(2)
        with _uc1:
            if st.button("Undo", use_container_width=True, key="btn_undo",
                         disabled=not BEFORE_LAYOUT_PATH.exists()):
                _cur = (EDITED_LAYOUT_PATH.read_text(encoding="utf-8")
                        if EDITED_LAYOUT_PATH.exists() else "{}")
                _bef = BEFORE_LAYOUT_PATH.read_text(encoding="utf-8")
                EDITED_LAYOUT_PATH.write_text(_bef, encoding="utf-8")
                BEFORE_LAYOUT_PATH.write_text(_cur, encoding="utf-8")
                st.session_state.viewer_nonce    += 1
                st.session_state.eval_result      = None
                st.session_state.eval_alts        = []
                st.session_state.cost_flexibility = None
                st.rerun()
        with _uc2:
            if st.button("Reset", use_container_width=True, key="btn_reset"):
                if DEFAULT_LAYOUT_PATH.exists():
                    _write_json(EDITED_LAYOUT_PATH, _read_json(DEFAULT_LAYOUT_PATH))
                elif EDITED_LAYOUT_PATH.exists():
                    EDITED_LAYOUT_PATH.unlink()
                st.session_state.viewer_nonce += 1
                for _k2 in ("eval_result", "eval_alts", "agent_log", "state_history",
                            "grid_options", "selected_grid", "output_log",
                            "cost_flexibility", "last_comparison"):
                    st.session_state[_k2] = (
                        [] if isinstance(st.session_state.get(_k2), list) else None)
                st.rerun()

        with st.expander("Structural Grid Options", expanded=False):
            _gcols2 = st.columns(2)
            with _gcols2[0]:
                gen_clicked = st.button("Generate", use_container_width=True, key="btn_gen")
            with _gcols2[1]:
                rec_clicked = st.button("Refresh",  use_container_width=True, key="btn_rec")
            if gen_clicked or rec_clicked:
                with st.spinner("Computing grid options…"):
                    st.session_state.grid_options = _run_grid_options(layout_obj, _mat_now)
                for _gi, _gopt in enumerate(st.session_state.grid_options, 1):
                    _gp = REPO_ROOT / f"team_01_option_{_gi}.json"
                    _gp.write_text(
                        json.dumps(_gopt["layout"], indent=2, ensure_ascii=False), encoding="utf-8")
                st.rerun()
            for _gopt in st.session_state.grid_options:
                _gl   = _gopt["label"]
                _gs   = _gopt["spacing"]
                _gf   = _gopt.get("failures", 0)
                _gc   = _gopt.get("cost", 0)
                _gact = st.session_state.selected_grid == _gl
                _gcls = "grid-card grid-card-active" if _gact else "grid-card"
                _gcol = "pass-ct" if _gf == 0 else "fail-ct"
                st.markdown(
                    f'<div class="{_gcls}"><span class="grid-label">{_gl}</span>'
                    f'<span class="grid-spacing" style="margin-left:6px">{_gs}m</span>'
                    f'<div class="grid-stats"><span class="{_gcol}">{_gf} fail</span>'
                    f' · ${_gc:,.0f}</div></div>',
                    unsafe_allow_html=True,
                )
                if st.button(f"Apply {_gl}", key=f"grid_{_gl}", use_container_width=True):
                    _bstr = (EDITED_LAYOUT_PATH.read_text(encoding="utf-8")
                             if EDITED_LAYOUT_PATH.exists() else json.dumps(layout_obj))
                    BEFORE_LAYOUT_PATH.write_text(_bstr, encoding="utf-8")
                    _write_json(EDITED_LAYOUT_PATH, _gopt.get("layout", {}))
                    st.session_state.selected_grid    = _gl
                    st.session_state.viewer_nonce    += 1
                    st.session_state.eval_result      = _gopt.get("evaluation")
                    st.session_state.eval_alts        = _get_failure_alternatives(
                        _gopt.get("evaluation") or {}, _mat_now)
                    st.session_state.cost_flexibility = None
                    st.rerun()

    # ── AI AGENT (always visible) ─────────────────────────────────────────────
    st.markdown(
        f'<div style="border-top:1px solid {_BORD};margin:8px 0 6px"></div>'
        f'<div style="font-size:.76rem;font-weight:700;color:{_TEXT};margin-bottom:4px">'
        f'AI Agent <span class="beta">BETA</span></div>',
        unsafe_allow_html=True,
    )
    _history = st.session_state.get("history", [])
    if _history:
        _bub = ""
        for _msg in _history[-3:]:
            _q = _msg.get("prompt", "")
            _a = _msg.get("response", "")
            if _q:
                _bub += f'<div class="chat-q">{_q[:90]}{"…" if len(_q)>90 else ""}</div>'
            if _a:
                _bub += f'<div class="chat-a">{_a[:120]}{"…" if len(_a)>120 else ""}</div>'
        st.markdown(
            f'<div style="max-height:100px;overflow-y:auto;margin-bottom:5px">{_bub}</div>',
            unsafe_allow_html=True,
        )

    with st.form("agent_form", clear_on_submit=True):
        prompt_input = st.text_area(
            "Ask agent",
            placeholder="Ask anything about your structure…\ne.g. reduce deflection in beam B1",
            label_visibility="collapsed",
            height=62,
        )
        submitted = st.form_submit_button("Ask Agent  ›", use_container_width=True)

    st.markdown('<div class="sb-section" style="margin-top:8px">Suggestions</div>',
                unsafe_allow_html=True)
    _sg1, _sg2 = st.columns(2)
    if _sg1.button("Reduce deflection", use_container_width=True, key="sg1"):
        prompt_input = "Reduce max deflection"
        submitted    = True
    if _sg2.button("Lower weight",      use_container_width=True, key="sg2"):
        prompt_input = "Lower structural weight"
        submitted    = True
    _sg3, _sg4 = st.columns(2)
    if _sg3.button("Optimize cost",     use_container_width=True, key="sg3"):
        prompt_input = "Optimize structural cost"
        submitted    = True
    if _sg4.button("Improve shear",     use_container_width=True, key="sg4"):
        prompt_input = "Improve shear capacity"
        submitted    = True

# ─── Agent processing ─────────────────────────────────────────────────────────
if submitted and prompt_input.strip():
    with st.spinner("Agent reasoning…"):
        _resp = _run_agent_chat(prompt_input.strip(), layout_obj, er)

    if _resp == "GENERATE_GRID":
        with st.spinner("Generating structural grid options…"):
            st.session_state.grid_options = _run_grid_options(layout_obj, _mat_now)
        for _gi, _gopt in enumerate(st.session_state.grid_options, 1):
            (REPO_ROOT / f"team_01_option_{_gi}.json").write_text(
                json.dumps(_gopt["layout"], indent=2, ensure_ascii=False), encoding="utf-8")
        _resp = f"Generated {len(st.session_state.grid_options)} grid option(s)."
    elif _resp == "EVALUATE":
        from nodes.modify import apply_material_override
        _ls_ag = apply_material_override(json.dumps(layout_obj), _mat_now)
        BEFORE_LAYOUT_PATH.write_text(json.dumps(layout_obj), encoding="utf-8")
        _write_json(EDITED_LAYOUT_PATH, json.loads(_ls_ag))
        st.session_state.viewer_nonce += 1
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
_hcols = st.columns([5, 1, 1], gap="small")

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
                 use_container_width=True, key="btn_theme"):
        st.session_state.theme        = "light" if not _is_light else "dark"
        st.session_state.viewer_nonce += 1
        st.rerun()
with _hcols[2]:
    st.download_button(
        "Export JSON",
        data=json.dumps(layout_obj, indent=2, ensure_ascii=False),
        file_name="layout_export.json",
        mime="application/json",
        use_container_width=True,
    )

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

    _sb_col, _run_col = st.columns([4.5, 1.5], gap="small")
    with _sb_col:
        st.markdown(_sbar_html, unsafe_allow_html=True)
    with _run_col:
        _run_clicked = st.button(
            "▶  Run Structural Analysis",
            type="primary", use_container_width=True, key="btn_run_analysis",
        )

    if _run_clicked:
        from nodes.modify import apply_material_override
        _ls2 = apply_material_override(json.dumps(layout_obj), _mat_now)
        BEFORE_LAYOUT_PATH.write_text(json.dumps(layout_obj), encoding="utf-8")
        _write_json(EDITED_LAYOUT_PATH, json.loads(_ls2))
        st.session_state.viewer_nonce += 1
        with st.spinner("Evaluating structure…"):
            _ev2 = _run_evaluate(_ls2, sdl=_sdl_now, ll=_ll_now)
        if _ev2:
            st.session_state.eval_result = _ev2
            st.session_state.eval_alts   = _get_failure_alternatives(_ev2, _mat_now)
        st.rerun()

    # ── Toolbar ───────────────────────────────────────────────────────────────
    _vm   = st.session_state.get("view_mode", "2D")
    _tc1, _tc2, _tc3, _tc4, _tc5 = st.columns([0.6, 0.7, 0.7, 0.7, 2.5], gap="small")
    with _tc1:
        if st.button("3D" if _vm == "2D" else "2D", key="btn_view", use_container_width=True):
            st.session_state["view_mode"] = "3D" if _vm == "2D" else "2D"
            st.rerun()
    with _tc2:
        _lab = st.toggle("Labels", value=st.session_state.labels_on, key="tog_labels")
        if _lab != st.session_state.labels_on:
            st.session_state.labels_on    = _lab
            st.session_state.viewer_nonce += 1
            st.rerun()
    with _tc3:
        _dif = st.toggle("Diff", value=st.session_state.compare_mode, key="tog_diff",
                          disabled=not BEFORE_LAYOUT_PATH.exists())
        if _dif != st.session_state.compare_mode:
            st.session_state.compare_mode = _dif
            st.session_state.viewer_nonce += 1
            st.rerun()
    with _tc4:
        _aut = st.toggle("Auto", value=st.session_state.get("auto_eval", True), key="tog_auto")
        if _aut != st.session_state.get("auto_eval", True):
            st.session_state.auto_eval = _aut
    with _tc5:
        _sn_n = len(st.session_state.snapshots) + 1
        if st.button(f"Save Snapshot #{_sn_n}", key="btn_snap", use_container_width=True):
            st.session_state.snapshots.append({
                "label":            f"Option {_sn_n}",
                "layout_json":      json.dumps(layout_obj),
                "eval_result":      er,
                "cost_flexibility": st.session_state.cost_flexibility,
                "before_json":      (BEFORE_LAYOUT_PATH.read_text(encoding="utf-8")
                                     if BEFORE_LAYOUT_PATH.exists()
                                     else json.dumps(layout_obj)),
            })
            st.rerun()

    _snaps = st.session_state.snapshots
    if _snaps:
        _pills = "".join(
            f'<span class="snap-pill{" snap-pill-active" if i==len(_snaps)-1 else ""}">'
            f'{s["label"]}</span>'
            for i, s in enumerate(_snaps)
        )
        st.markdown(_pills, unsafe_allow_html=True)

    # ── Generate Grid & Options bar ───────────────────────────────────────────
    _gopts_bar  = st.session_state.grid_options
    _sel_opt_i  = st.session_state.get("selected_opt_bar_idx", -1)

    _gbar_parts = []
    _gbar_parts.append('<div class="grid-opt-bar">')
    _gbar_parts.append('<span class="grid-opt-lbl">Layout Options</span>')
    if _gopts_bar:
        for _bi, _bo in enumerate(_gopts_bar[:3]):
            _bact = _sel_opt_i == _bi
            _bfail = _bo.get("failures", 0)
            _bcls = "gobar-active" if _bact else "gobar-inactive"
            _bsub = f"{_bo.get('label','Opt')}"
            _bfmt = f"<span style='font-size:.55rem;opacity:.8'> · {_bfail}✗</span>" if _bfail else ""
            _gbar_parts.append(
                f'<span class="{_bcls}" style="padding:3px 10px;border-radius:5px;'
                f'font-size:.65rem;cursor:pointer;white-space:nowrap">'
                f'{_bsub}{_bfmt}</span>'
            )
    _gbar_parts.append("</div>")
    st.markdown("".join(_gbar_parts), unsafe_allow_html=True)

    # Invisible Streamlit buttons that drive grid option selection
    if _gopts_bar:
        _gobar_btn_cols = st.columns(len(_gopts_bar[:3]) + 1, gap="small")
        with _gobar_btn_cols[0]:
            if st.button("Current", key="gobar_cur", use_container_width=True,
                         type="primary" if _sel_opt_i == -1 else "secondary"):
                st.session_state["selected_opt_bar_idx"] = -1
                st.rerun()
        for _bi2, _bo2 in enumerate(_gopts_bar[:3]):
            with _gobar_btn_cols[_bi2 + 1]:
                _is_active2 = _sel_opt_i == _bi2
                if st.button(
                    _bo2.get("label", f"Opt {_bi2+1}"),
                    key=f"gobar_btn_{_bi2}",
                    use_container_width=True,
                    type="primary" if _is_active2 else "secondary",
                ):
                    st.session_state["selected_opt_bar_idx"] = _bi2
                    st.rerun()

    _preview_opt_file = ""
    if _gopts_bar and _sel_opt_i >= 0 and _sel_opt_i < len(_gopts_bar):
        _preview_opt_file = f"team_01_option_{_sel_opt_i + 1}.json"

    _plan_layout = layout_obj
    if _preview_opt_file:
        _opt_path = REPO_ROOT / _preview_opt_file
        if _opt_path.exists():
            try:
                _plan_layout = _normalize_layout(
                    json.loads(_opt_path.read_text(encoding="utf-8")))
            except Exception:
                pass

    # ── Main: floor plan | right panel ───────────────────────────────────────
    _main_col, _right_col = st.columns([1.65, 1.0], gap="small")

    with _main_col:
        if _vm == "2D":
            components.html(
                _render_floor_plan_html(
                    _plan_layout, eval_result=er,
                    highlight=st.session_state.selected_el,
                    labels=st.session_state.labels_on,
                    height_px=510, is_light=_is_light,
                ),
                height=512, scrolling=False,
            )
        else:
            if _viewer_is_reachable():
                components.iframe(
                    _viewer_url(
                        highlight=st.session_state.selected_el,
                        compare=st.session_state.compare_mode,
                        labels=st.session_state.labels_on,
                        option_file=_preview_opt_file,
                    ),
                    height=512, scrolling=False,
                )
            else:
                st.caption("3D viewer offline — run `python -m http.server 8000` from repo root.")
                components.html(
                    _render_floor_plan_html(
                        _plan_layout, eval_result=er,
                        highlight=st.session_state.selected_el,
                        labels=st.session_state.labels_on,
                        height_px=510, is_light=_is_light,
                    ),
                    height=512, scrolling=False,
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
        _rt1, _rt2 = st.tabs(["AI RECOMMENDATIONS", "DESIGN DETAILS"])

        with _rt1:
            _alts     = st.session_state.eval_alts
            _imp_css  = ["imp-high", "imp-med", "imp-low"]
            _imp_lbls = ["HIGH IMPACT", "MEDIUM IMPACT", "LOW IMPACT"]
            _num_cols = [_NUM1_BG, _NUM2_BG, _NUM3_BG]

            if not _alts:
                st.markdown(
                    f'<div style="font-size:.70rem;color:{_MUT};padding:8px 2px;line-height:1.6">'
                    + ("✓ All structural checks passed."
                       if er else
                       "Run structural analysis to get AI recommendations.")
                    + "</div>",
                    unsafe_allow_html=True,
                )
            else:
                for _ri, _alt in enumerate(_alts[:3]):
                    _icss = _imp_css[min(_ri, 2)]
                    _ilbl = _imp_lbls[min(_ri, 2)]
                    _nc   = _num_cols[min(_ri, 2)]
                    _dw, _dc, _dd = _REC_DELTAS[min(_ri, 2)]
                    st.markdown(
                        f'<div class="rec-card">'
                        f'<div class="rec-top">'
                        f'<span class="rec-n" style="background:{_nc}">{_ri+1}</span>'
                        f'<span class="rec-title">{_alt[:55]}{"…" if len(_alt)>55 else ""}</span>'
                        f'<span class="{_icss}">{_ilbl}</span>'
                        f'</div>'
                        f'<div class="rec-desc">{_alt[:160]}{"…" if len(_alt)>160 else ""}</div>'
                        f'<div class="rec-metrics">'
                        f'<div class="rec-met"><div class="rec-met-lbl">Weight</div>'
                        f'<div class="rec-met-pos">↓ {_dw:.2f}%</div></div>'
                        f'<div class="rec-met"><div class="rec-met-lbl">Cost</div>'
                        f'<div class="rec-met-pos">↓ {_dc:.1f}%</div></div>'
                        f'<div class="rec-met"><div class="rec-met-lbl">Max Deflection</div>'
                        f'<div class="rec-met-neg">↑ {_dd:.2f}%</div></div>'
                        f'</div></div>',
                        unsafe_allow_html=True,
                    )
                    _rc1, _rc2, _rc3 = st.columns([1, 1.2, 1])
                    with _rc1:
                        st.button("Preview", key=f"prev_{_ri}", use_container_width=True)
                    with _rc2:
                        if st.button("Apply Change", key=f"apply_{_ri}",
                                     use_container_width=True, type="primary"):
                            _before_str = json.dumps(layout_obj)
                            BEFORE_LAYOUT_PATH.write_text(_before_str, encoding="utf-8")
                            with st.spinner("Applying…"):
                                _new_str, _new_ev = _apply_alternative(
                                    _alt, _before_str, _mat_now, _sdl_now, _ll_now)
                            if _new_str != _before_str:
                                _write_json(EDITED_LAYOUT_PATH, json.loads(_new_str))
                                st.session_state.viewer_nonce    += 1
                                st.session_state.cost_flexibility = None
                                st.session_state.state_history.append({
                                    "label":       _alt[:30],
                                    "layout_json": json.loads(_new_str),
                                    "eval_result": _new_ev,
                                })
                                with st.spinner("Summarising…"):
                                    _cf_res  = _run_cost_flex(_before_str, _new_str)
                                    _cmp_txt = _run_comparison(_before_str, _new_str)
                                if _cf_res:
                                    st.session_state.cost_flexibility = _cf_res
                                if _cmp_txt:
                                    st.session_state.last_comparison = _cmp_txt
                            if _new_ev is not None:
                                st.session_state.eval_result = _new_ev
                                st.session_state.eval_alts   = _get_failure_alternatives(
                                    _new_ev, _mat_now)
                            st.rerun()
                    with _rc3:
                        if st.button("Compare", key=f"cmp_{_ri}", use_container_width=True):
                            st.session_state.snapshots.append({
                                "label":            f"Option {len(_snaps)+1}",
                                "layout_json":      json.dumps(layout_obj),
                                "eval_result":      er,
                                "cost_flexibility": st.session_state.cost_flexibility,
                                "before_json":      (BEFORE_LAYOUT_PATH.read_text(encoding="utf-8")
                                                     if BEFORE_LAYOUT_PATH.exists()
                                                     else json.dumps(layout_obj)),
                            })
                            st.rerun()

                st.markdown(
                    f'<div style="font-size:.65rem;color:{_ACC};text-align:right;'
                    f'margin-top:4px;cursor:pointer">View All Recommendations →</div>',
                    unsafe_allow_html=True,
                )

        with _rt2:
            _sel     = st.session_state.selected_el
            _sel_obj = next(
                (e for e in layout_obj.get("structure", []) if e["id"] == _sel), None
            ) if _sel else None

            if _sel_obj:
                st.markdown(_el_detail_html(_sel_obj, er), unsafe_allow_html=True)
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
                        _chks = [k for k, f in [
                            ("bend",  not _b.get("bend_PASS")),
                            ("shear", not _b.get("shear_PASS")),
                            ("defl",  not _b.get("defl_TL_PASS") or not _b.get("defl_LL_PASS")),
                        ] if f]
                        _crit_html += (
                            f'<div class="crit-item" '
                            f'onclick="window.parent.postMessage({{type:\'selectElement\','
                            f'elementId:\'{_b["id"]}\'}},\'*\')">'
                            f'<b>{_b["id"]}</b> {_b.get("span_m",0):.1f}m'
                            f'<span style="float:right;color:{_FAIL}">{", ".join(_chks)}</span></div>'
                        )
                    for _c in _fcols[:2]:
                        _chks = [k for k, f in [
                            ("stress", not _c.get("stress_PASS")),
                            ("buck",   not _c.get("buckling_PASS")),
                        ] if f]
                        _crit_html += (
                            f'<div class="crit-item" '
                            f'onclick="window.parent.postMessage({{type:\'selectElement\','
                            f'elementId:\'{_c["id"]}\'}},\'*\')">'
                            f'<b>{_c["id"]}</b>'
                            f'<span style="float:right;color:{_FAIL}">{", ".join(_chks)}</span></div>'
                        )
                    st.markdown(_crit_html, unsafe_allow_html=True)
                elif er:
                    st.markdown('<span class="pass-badge">✓ All elements pass</span>',
                                unsafe_allow_html=True)

            _cf_r     = st.session_state.get("cost_flexibility")
            _last_cmp = st.session_state.get("last_comparison")
            if _cf_r:
                st.markdown(
                    '<div class="panel-hdr" style="margin-top:10px">Cost & Change</div>',
                    unsafe_allow_html=True,
                )
                _cm1, _cm2, _cm3 = st.columns(3)
                _cm1.metric("Net",     f"${_cf_r.get('net_cost_usd', 0):+,.0f}")
                _cm2.metric("Flex",    f"{_cf_r.get('flexibility_score', 0):.1f}/10")
                _cm3.metric("Disrupt", f"{_cf_r.get('disruption_score', 0)}/10")
                if _last_cmp:
                    st.markdown(
                        f'<div class="agent-resp">{_last_cmp[:280]}'
                        f'{"…" if len(_last_cmp)>280 else ""}</div>',
                        unsafe_allow_html=True,
                    )
            elif er:
                if st.button("Analyse cost & flexibility", use_container_width=True, key="btn_cf"):
                    _bs2 = (BEFORE_LAYOUT_PATH.read_text(encoding="utf-8")
                            if BEFORE_LAYOUT_PATH.exists() else json.dumps(layout_obj))
                    with st.spinner("Analysing…"):
                        _cf2 = _run_cost_flex(_bs2, json.dumps(layout_obj))
                    if _cf2:
                        st.session_state.cost_flexibility = _cf2
                    st.rerun()

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
                                _write_json(EDITED_LAYOUT_PATH, json.loads(_sn["layout_json"]))
                                st.session_state.viewer_nonce += 1
                                st.session_state.eval_result   = _sn.get("eval_result")
                                st.session_state.eval_alts     = _get_failure_alternatives(
                                    _sn.get("eval_result") or {}, _mat_now)
                                st.rerun()

            with st.expander("Output Log", expanded=False):
                for _msg in reversed(st.session_state.output_log[-6:]):
                    st.markdown(
                        f'<div class="log-entry">{_msg[:220]}'
                        f'{"…" if len(_msg)>220 else ""}</div>',
                        unsafe_allow_html=True,
                    )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — COMPARE
# ══════════════════════════════════════════════════════════════════════════════
with tab_cmp:

    _snaps_c = st.session_state.snapshots
    _cvm_now = st.session_state.get("compare_view_mode", "2D")

    def _snap_fails(s):
        _ev_ = (s.get("eval_result") or {}).get("summary", {})
        return _ev_.get("beam_failures", 0) + _ev_.get("column_failures", 0)

    _cmp_opts = [
        {"label": "Baseline", "sub": "Current design",
         "layout_json": json.dumps(layout_obj),
         "eval_result": er, "cost_flexibility": st.session_state.cost_flexibility}
    ] + [
        {"label": s["label"],
         "sub":   "Pass" if _snap_fails(s) == 0 else f"{_snap_fails(s)} fail",
         "layout_json":      s["layout_json"],
         "eval_result":      s.get("eval_result"),
         "cost_flexibility": s.get("cost_flexibility")}
        for s in _snaps_c[:2]
    ]
    _n_opts = len(_cmp_opts)

    _ctl1, _ctl2, _ctl3, _ctl4 = st.columns([2.5, 0.7, 0.7, 1.5], gap="small")
    with _ctl1:
        st.markdown(
            f'<div style="font-size:.72rem;font-weight:700;color:{_TEXT};padding:5px 0">'
            f'Comparing <b>{_n_opts}</b> of 3 max options</div>',
            unsafe_allow_html=True,
        )
    with _ctl2:
        if st.button("2D", key="cmp_2d", use_container_width=True,
                     type="primary" if _cvm_now == "2D" else "secondary"):
            st.session_state["compare_view_mode"] = "2D"
            st.rerun()
    with _ctl3:
        if st.button("3D", key="cmp_3d", use_container_width=True,
                     type="primary" if _cvm_now == "3D" else "secondary"):
            st.session_state["compare_view_mode"] = "3D"
            st.rerun()
    with _ctl4:
        _cmp_ids = st.checkbox("Show IDs",     value=False, key="cmp_labels")
        _cmp_ev  = st.checkbox("Eval overlay", value=True,  key="cmp_eval")

    if _n_opts == 1:
        st.info("Save at least one snapshot in the Modify tab to compare options.")
        st.markdown(
            '<div class="cmp-card-hdr"><span class="cmp-title">Baseline</span>'
            '<span class="badge-curr">Current Design</span></div>',
            unsafe_allow_html=True,
        )
        components.html(
            _render_floor_plan_html(
                _normalize_layout(json.loads(_cmp_opts[0]["layout_json"])),
                eval_result=_cmp_opts[0]["eval_result"] if _cmp_ev else None,
                labels=_cmp_ids, height_px=440, is_light=_is_light,
            ),
            height=442, scrolling=False,
        )
    else:
        _plan_cols = st.columns(_n_opts, gap="small")
        _DOT_C = [_ACC, _ACC2, "#ffd060"]
        for _ci, (_pcol, _co) in enumerate(zip(_plan_cols, _cmp_opts)):
            with _pcol:
                _badge = ('<span class="badge-curr">Current Design</span>'
                          if _ci == 0 else f'<span class="badge-opt">Snapshot {_ci}</span>')
                _dc = _DOT_C[min(_ci, 2)]
                st.markdown(
                    f'<div class="cmp-card-hdr">'
                    f'<span style="display:flex;align-items:center;gap:6px">'
                    f'<span style="width:8px;height:8px;border-radius:50%;background:{_dc};'
                    f'flex-shrink:0;display:inline-block"></span>'
                    f'<span class="cmp-title">{_co["label"]}</span></span>'
                    f'{_badge}</div>',
                    unsafe_allow_html=True,
                )
                _plan_ci = _normalize_layout(json.loads(_co["layout_json"]))
                _ph = 390 if _n_opts == 2 else 320
                if _cvm_now == "2D":
                    components.html(
                        _render_floor_plan_html(
                            _plan_ci,
                            eval_result=_co["eval_result"] if _cmp_ev else None,
                            labels=_cmp_ids, height_px=_ph, is_light=_is_light,
                        ),
                        height=_ph + 2, scrolling=False,
                    )
                else:
                    if _viewer_is_reachable():
                        _of = f"team_01_option_{_ci}.json" if _ci > 0 else ""
                        components.iframe(
                            _viewer_url(labels=_cmp_ids, option_file=_of),
                            height=_ph + 2, scrolling=False,
                        )
                    else:
                        components.html(
                            _render_floor_plan_html(
                                _plan_ci,
                                eval_result=_co["eval_result"] if _cmp_ev else None,
                                labels=_cmp_ids, height_px=_ph, is_light=_is_light,
                            ),
                            height=_ph + 2, scrolling=False,
                        )

    if _n_opts > 1:
        _tbl_col, _ins_col = st.columns([1.7, 1.0], gap="small")

        with _tbl_col:
            st.markdown(
                '<div class="panel-hdr" style="margin-top:10px">Summary Metrics</div>',
                unsafe_allow_html=True,
            )

            def _get_m(co):
                _ev_ = (co.get("eval_result") or {}).get("summary", {})
                _cf_ = co.get("cost_flexibility") or {}
                return {
                    "Beam Failures": _ev_.get("beam_failures",  None),
                    "Col Failures":  _ev_.get("column_failures", None),
                    "Max Defl (mm)": _ev_.get("max_defl_mm",     None),
                    "Net Cost ($)":  _cf_.get("net_cost_usd",    None),
                }

            _all_m   = [_get_m(c) for c in _cmp_opts]
            _metrics = ["Beam Failures", "Col Failures", "Max Defl (mm)", "Net Cost ($)"]

            def _fmt(v):
                if v is None: return "—"
                return f"{v:.1f}" if isinstance(v, float) else str(v)

            _hrow  = "".join(f'<th>{c["label"]}</th>' for c in _cmp_opts)
            _tbody = ""
            for _mname in _metrics:
                _vals = [_all_m[i][_mname] for i in range(_n_opts)]
                _nums = [v for v in _vals if isinstance(v, (int, float))]
                _best = min(_nums) if _nums else None
                _cells = (
                    f'<td style="text-align:left;color:{_MUT};font-size:.63rem;'
                    f'font-weight:600">{_mname}</td>'
                )
                for _v in _vals:
                    _cls = "cmp-best" if (_v is not None and _v == _best) else "cmp-norm"
                    _cells += f'<td class="{_cls}">{_fmt(_v)}</td>'
                _tbody += f'<tr style="background:{_BG}">{_cells}</tr>'

            st.markdown(
                f'<table class="cmp-tbl">'
                f'<thead><tr><th style="text-align:left">Metric</th>{_hrow}</tr></thead>'
                f'<tbody>{_tbody}</tbody></table>',
                unsafe_allow_html=True,
            )

        with _ins_col:
            st.markdown(
                '<div class="panel-hdr" style="margin-top:10px">Comparison Insights</div>',
                unsafe_allow_html=True,
            )

            def _best_opt(key, lower=True):
                _vals = []
                for _co in _cmp_opts:
                    _ev_ = (_co.get("eval_result") or {}).get("summary", {})
                    _cf_ = _co.get("cost_flexibility") or {}
                    _v   = _ev_.get(key, _cf_.get(key))
                    _vals.append((_co["label"], _v))
                _valid = [(l, v) for l, v in _vals if isinstance(v, (int, float))]
                if not _valid: return "—", "No data"
                _bl, _bv = (min if lower else max)(_valid, key=lambda x: x[1])
                return _bl, (f"{_bv:.1f}" if isinstance(_bv, float) else str(_bv))

            _insights = [
                ("🏆", "Best Stability",  *_best_opt("beam_failures", True),  "Fewest beam failures"),
                ("📉", "Best Deflection", *_best_opt("max_defl_mm",   True),  "Lowest max deflection"),
                ("💰", "Best Cost",       *_best_opt("net_cost_usd",  True),  "Lowest cost delta"),
            ]
            _ins_html = ""
            for _ico, _lbl, _opt, _val, _det in _insights:
                _ins_html += (
                    f'<div class="insight-card">'
                    f'<span class="insight-ico">{_ico}</span>'
                    f'<div><div class="insight-lbl">{_lbl}</div>'
                    f'<div class="insight-opt">{_opt}</div>'
                    f'<div class="insight-det">{_det}: {_val}</div></div></div>'
                )
            st.markdown(_ins_html, unsafe_allow_html=True)

            _best_lbl, _ = _best_opt("beam_failures", True)
            _last        = st.session_state.get("last_comparison", "")
            st.markdown(
                f'<div class="rec-box">'
                f'<div class="rec-box-lbl">Recommended Option</div>'
                f'<div class="rec-box-txt"><b>{_best_lbl}</b> provides the best structural '
                f'performance based on analysis.'
                + (f' {_last[:180]}{"…" if len(_last)>180 else ""}' if _last else "")
                + '</div></div>',
                unsafe_allow_html=True,
            )

    _rep1, _rep2, _rep3 = st.columns([2, 1, 1], gap="small")
    with _rep1:
        _slots = 2 - len(_snaps_c)
        if _slots > 0:
            st.caption(f"Save {_slots} more snapshot(s) in Modify tab to fill all comparison slots.")
    with _rep2:
        if _snaps_c and st.button("Reset", use_container_width=True, key="btn_reset_cmp"):
            st.session_state.snapshots = []
            st.rerun()
    with _rep3:
        st.download_button(
            "Export Report",
            data=json.dumps({"baseline": layout_obj,
                             "options": [{"label": s["label"],
                                          "layout": json.loads(s["layout_json"])}
                                         for s in _snaps_c]},
                            indent=2, ensure_ascii=False),
            file_name="comparison_report.json",
            mime="application/json",
            use_container_width=True,
        )
