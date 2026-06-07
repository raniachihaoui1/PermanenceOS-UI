from __future__ import annotations

import base64
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


@st.cache_data(ttl=5)
def _viewer_is_reachable() -> bool:
    try:
        with urllib.request.urlopen(VIEWER_BASE_URL, timeout=0.8) as r:
            return r.status == 200
    except Exception:
        return False


def _viewer_url(highlight: str = "", compare: bool = False,
                labels: bool = True, option_file: str = "") -> str:
    layout_stamp = int(EDITED_LAYOUT_PATH.stat().st_mtime_ns) if EDITED_LAYOUT_PATH.exists() else 0
    theme        = st.session_state.get("theme", "dark")
    url = (
        f"{VIEWER_BASE_URL}"
        f"?v={st.session_state.viewer_nonce}"
        f"&layout={layout_stamp}"
        f"&theme={theme}"
        f"&labels={'1' if labels else '0'}"
    )
    if highlight:
        url += f"&highlight={highlight}"
    if compare and BEFORE_LAYOUT_PATH.exists():
        url += "&mode=compare"
    if option_file:
        url += f"&optionFile={option_file}"
    return url


def _svg_poly_points(geo, fy):
    return " ".join(f"{x},{fy(y)}" for x, y in geo)


def _svg_centroid(geo):
    pts = geo[:-1] if len(geo) > 2 and geo[0] == geo[-1] else geo
    xs, ys = zip(*pts)
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _svg_dims(geo):
    xs = [p[0] for p in geo]; ys = [p[1] for p in geo]
    return max(xs) - min(xs), max(ys) - min(ys), max(ys), (min(xs) + max(xs)) / 2


def _door_swing_points(a, b, fy_fn, n=12):
    import math
    r  = math.hypot(b[0] - a[0], b[1] - a[1])
    t0 = math.atan2(b[1] - a[1], b[0] - a[0])
    pts = []
    for i in range(n + 1):
        t = t0 + (math.pi / 2) * (i / n)
        pts.append((a[0] + r * math.cos(t), fy_fn(a[1] + r * math.sin(t))))
    return " ".join(f"{x},{y}" for x, y in pts)


def _render_floor_plan_html(
    layout: dict,
    eval_result: dict | None = None,
    highlight: str = "",
    labels: bool = False,
    height_px: int = 380,
    is_light: bool = False,
    view_mode: str = "2D",
    diff_on: bool = False,
    auto_on: bool = True,
) -> str:
    if is_light:
        BG     = "#f0f8f8"
        ROOM   = "#daeaea"
        FG     = "#1a3535"
        ACCENT = "#088a87"
        PASS_C = "#1a8050"
        FAIL_C = "#cc2020"
        SEL_C  = "#c07800"
        WIN_C  = "#2060a0"
    else:
        BG     = "#0c2020"
        ROOM   = "#172e2e"
        FG     = "#c8eeed"
        ACCENT = "#2ac0c0"
        PASS_C = "#40d090"
        FAIL_C = "#ff5050"
        SEL_C  = "#ffd060"
        WIN_C  = "#4696dc"

    all_pts: list = list(layout.get("outline", []))
    for r in layout.get("rooms",     []): all_pts.extend(r.get("geometry", []))
    for d in layout.get("doors",     []): all_pts.extend(d.get("geometry", []))
    for w in layout.get("windows",   []): all_pts.extend(w.get("geometry", []))
    for f in layout.get("furniture", []): all_pts.extend(f.get("geometry", []))
    for s in layout.get("structure", []): all_pts.extend(s.get("geometry", []))

    if not all_pts:
        return (
            f'<!DOCTYPE html><html><head><meta charset="utf-8"><style>'
            f'*{{margin:0;padding:0}}html,body{{background:{BG};height:100%;display:flex;'
            f'align-items:center;justify-content:center}}</style></head><body>'
            f'<span style="color:{ACCENT};font-family:monospace;font-size:.82rem">'
            f'Upload a layout JSON to view the plan</span></body></html>'
        )

    xs = [p[0] for p in all_pts]; ys = [p[1] for p in all_pts]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    span = max(x1 - x0, y1 - y0) or 1
    pad  = span * 0.07 + 0.5
    vb_x, vb_y = x0 - pad, y0 - pad
    vb_w, vb_h = (x1 - x0) + 2 * pad, (y1 - y0) + 2 * pad

    def fy(y): return (y0 + y1) - y

    u = span * 0.012  # SVG-unit scalar for column radii and label sizes

    el_status: dict[str, str] = {}
    if eval_result:
        for b in eval_result.get("beams", []):
            ok = b["bend_PASS"] and b["shear_PASS"] and b["defl_TL_PASS"] and b["defl_LL_PASS"]
            el_status[b["id"]] = "pass" if ok else "fail"
        for c in eval_result.get("columns", []):
            ok = c["stress_PASS"] and c["buckling_PASS"]
            el_status[c["id"]] = "pass" if ok else "fail"

    # Needed for score badges — define before the room loop
    _all_structure = layout.get("structure", [])

    parts: list[str] = []

    # ── ROOMS ──────────────────────────────────────────────────────────────────
    for room in layout.get("rooms", []):
        geo = room.get("geometry", [])
        if len(geo) < 3:
            continue
        pts_str = _svg_poly_points(geo, fy)
        cx, cy  = _svg_centroid(geo)
        w       = _svg_dims(geo)[0]
        label   = room.get("name", "")
        rid     = room.get("id", "")
        # Tooltip text for hover
        _area   = abs(sum(
            (geo[i][0]*geo[(i+1)%len(geo)][1] - geo[(i+1)%len(geo)][0]*geo[i][1])
            for i in range(len(geo))
        )) / 2
        _tip    = f"{label}&#10;Area: {_area:.1f} m²" if label else ""
        parts.append(
            f'<polygon data-room="{rid}" data-name="{label}" '
            f'points="{pts_str}" fill="{ROOM}" fill-opacity="0.88" '
            f'stroke="{FG}" stroke-opacity="0.22" stroke-width="0.8" '
            f'vector-effect="non-scaling-stroke" style="cursor:pointer">'
            + (f'<title>{_tip}</title>' if _tip else "")
            + f'</polygon>'
        )
        if label and w > u * 3:
            parts.append(
                f'<text x="{cx}" y="{fy(cy)}" text-anchor="middle" '
                f'dominant-baseline="central" font-family="monospace" '
                f'font-size="{u*1.05}" fill="{FG}" fill-opacity="0.55" '
                f'pointer-events="none">{label}</text>'
            )
        if el_status:
            _rxs = [p[0] for p in geo]; _rys = [p[1] for p in geo]
            _rx0, _rx1 = min(_rxs), max(_rxs)
            _ry0, _ry1 = min(_rys), max(_rys)
            _rpad = max(_rx1-_rx0, _ry1-_ry0, 0.1) * 0.12
            _near = []
            for _el in _all_structure:
                _eg = _el.get("geometry", [])
                _eid2 = _el.get("id", "")
                if _eid2 not in el_status:
                    continue
                if len(_eg) == 1:
                    if (_rx0-_rpad) <= _eg[0][0] <= (_rx1+_rpad) and (_ry0-_rpad) <= _eg[0][1] <= (_ry1+_rpad):
                        _near.append(el_status[_eid2])
                elif len(_eg) == 2:
                    _mx = (_eg[0][0]+_eg[1][0])/2; _my = (_eg[0][1]+_eg[1][1])/2
                    if (_rx0-_rpad) <= _mx <= (_rx1+_rpad) and (_ry0-_rpad) <= _my <= (_ry1+_rpad):
                        _near.append(el_status[_eid2])
            if _near:
                _rs = sum(1 for s in _near if s == "pass") / len(_near)
                _sc = "#40d090" if _rs >= 0.9 else ("#ffaa22" if _rs >= 0.5 else "#ff5050")
                _badge_y = fy(cy) + (u * 1.4 if label else 0)
                parts.append(
                    f'<text x="{cx}" y="{_badge_y}" text-anchor="middle" '
                    f'dominant-baseline="central" font-family="monospace" font-weight="700" '
                    f'font-size="{u*2.0}" fill="{_sc}" fill-opacity="0.72">'
                    f'{_rs:.2f}</text>'
                )

    # ── OUTLINE ────────────────────────────────────────────────────────────────
    outline = layout.get("outline", [])
    if len(outline) > 1:
        parts.append(
            f'<polyline points="{_svg_poly_points(outline, fy)}" fill="none" '
            f'stroke="{ACCENT}" stroke-opacity="0.8" stroke-width="1.5" '
            f'stroke-linejoin="round" vector-effect="non-scaling-stroke"/>'
        )

    # ── DOORS ──────────────────────────────────────────────────────────────────
    for door in layout.get("doors", []):
        geo = door.get("geometry", [])
        if len(geo) < 2:
            continue
        a, b = geo[0], geo[-1]
        ax, ay = a[0], fy(a[1])
        arc_pts = _door_swing_points(a, b, fy)
        arc_end = arc_pts.split(" ")[-1].split(",")
        parts.append(
            f'<line x1="{ax}" y1="{ay}" x2="{b[0]}" y2="{fy(b[1])}" '
            f'stroke="{BG}" stroke-width="4" vector-effect="non-scaling-stroke"/>'
        )
        parts.append(
            f'<polyline points="{arc_pts}" fill="none" stroke="{FG}" stroke-opacity="0.5" '
            f'stroke-width="0.8" stroke-dasharray="3 2" '
            f'vector-effect="non-scaling-stroke"/>'
        )
        parts.append(
            f'<line x1="{ax}" y1="{ay}" x2="{arc_end[0]}" y2="{arc_end[1]}" '
            f'stroke="{FG}" stroke-opacity="0.5" stroke-width="0.8" '
            f'vector-effect="non-scaling-stroke"/>'
        )

    # ── WINDOWS ────────────────────────────────────────────────────────────────
    for win in layout.get("windows", []):
        geo = win.get("geometry", [])
        if len(geo) >= 2:
            parts.append(
                f'<polyline points="{_svg_poly_points(geo, fy)}" fill="none" '
                f'stroke="{WIN_C}" stroke-width="1.5" vector-effect="non-scaling-stroke"/>'
            )

    # ── FURNITURE ──────────────────────────────────────────────────────────────
    for furn in layout.get("furniture", []):
        geo = furn.get("geometry", [])
        if len(geo) >= 3:
            parts.append(
                f'<polygon points="{_svg_poly_points(geo, fy)}" fill="{FG}" fill-opacity="0.06" '
                f'stroke="{FG}" stroke-opacity="0.22" stroke-width="0.6" '
                f'vector-effect="non-scaling-stroke"/>'
            )

    # ── BEAMS ──────────────────────────────────────────────────────────────────
    # stroke-width values are in screen pixels (vector-effect="non-scaling-stroke")
    structure = _all_structure
    beams = [s for s in structure if len(s.get("geometry", [])) == 2]
    cols  = [s for s in structure if len(s.get("geometry", [])) == 1]

    for beam in beams:
        eid    = beam["id"]
        geo    = beam["geometry"]
        p1, p2 = geo[0], geo[1]
        status = el_status.get(eid, "none")
        stroke = FAIL_C if status == "fail" else (PASS_C if status == "pass" else ACCENT)
        is_sel = eid == highlight
        sw     = "3.5" if is_sel else "2"
        sc     = SEL_C if is_sel else stroke
        parts.append(
            f'<line data-eid="{eid}" x1="{p1[0]}" y1="{fy(p1[1])}" '
            f'x2="{p2[0]}" y2="{fy(p2[1])}" stroke="{sc}" '
            f'stroke-width="{sw}" stroke-linecap="round" '
            f'vector-effect="non-scaling-stroke" style="cursor:pointer"/>'
        )
        # Wide transparent hit area (12 px) for easy clicking
        parts.append(
            f'<line data-eid="{eid}" x1="{p1[0]}" y1="{fy(p1[1])}" '
            f'x2="{p2[0]}" y2="{fy(p2[1])}" stroke="transparent" '
            f'stroke-width="12" vector-effect="non-scaling-stroke" style="cursor:pointer"/>'
        )
        if labels:
            mx = (p1[0] + p2[0]) / 2
            my = (fy(p1[1]) + fy(p2[1])) / 2
            parts.append(
                f'<text x="{mx}" y="{my - u*0.6}" text-anchor="middle" '
                f'font-size="{u*0.85}" fill="{SEL_C if is_sel else stroke}" '
                f'font-family="monospace" pointer-events="none">{eid}</text>'
            )

    # ── COLUMNS ────────────────────────────────────────────────────────────────
    for col_el in cols:
        eid    = col_el["id"]
        geo    = col_el["geometry"]
        cx_c   = geo[0][0]
        cy_c   = fy(geo[0][1])
        status = el_status.get(eid, "none")
        fill   = FAIL_C if status == "fail" else (PASS_C if status == "pass" else ACCENT)
        is_sel = eid == highlight
        r_c    = u * (1.0 if is_sel else 0.75)
        parts.append(
            f'<circle data-eid="{eid}" cx="{cx_c}" cy="{cy_c}" r="{r_c}" '
            f'fill="{SEL_C if is_sel else fill}" fill-opacity="0.92" '
            f'stroke="{BG}" stroke-width="1" '
            f'vector-effect="non-scaling-stroke" style="cursor:pointer"/>'
        )
        if labels:
            parts.append(
                f'<text x="{cx_c}" y="{cy_c + r_c + u*0.8}" text-anchor="middle" '
                f'font-size="{u*0.85}" fill="{SEL_C if is_sel else fill}" '
                f'font-family="monospace" pointer-events="none">{eid}</text>'
            )

    # ── LEGEND ────────────────────────────────────────────────────────────────
    if el_status:
        lx  = vb_x + vb_w * 0.015
        ly  = vb_y + vb_h * 0.973
        dr  = u * 0.4
        gap = u * 3.8
        parts.append(
            f'<circle cx="{lx}" cy="{ly}" r="{dr}" fill="{PASS_C}"/>'
            f'<text x="{lx + dr*2.2}" y="{ly}" dominant-baseline="middle" '
            f'font-size="{u*0.82}" fill="#5a9898" font-family="monospace">pass</text>'
            f'<circle cx="{lx + gap}" cy="{ly}" r="{dr}" fill="{FAIL_C}"/>'
            f'<text x="{lx + gap + dr*2.2}" y="{ly}" dominant-baseline="middle" '
            f'font-size="{u*0.82}" fill="#5a9898" font-family="monospace">fail</text>'
        )

    svg_inner = "".join(parts)
    hl_json   = json.dumps(highlight)

    _tt_bg  = "rgba(20,50,50,0.92)" if not is_light else "rgba(230,245,245,0.96)"
    _tt_clr = "#c8eeed" if not is_light else "#1a2a30"
    _tt_brd = "#2ac0c0" if not is_light else "#088a87"

    # Toolbar overlay state
    _tb_vm_txt   = view_mode
    _tb_lab_js   = "true"  if labels   else "false"
    _tb_diff_js  = "true"  if diff_on  else "false"
    _tb_auto_js  = "true"  if auto_on  else "false"
    _tb_bg       = "rgba(7,26,26,0.82)"    if not is_light else "rgba(230,245,245,0.92)"
    _tb_brd      = "#1a4040"               if not is_light else "#c0d8d8"
    _tb_clr      = "#6ab8b8"              if not is_light else "#336868"
    _tb_act_clr  = "#2ac0c0"              if not is_light else "#088a87"
    _tb_act_bg   = "rgba(42,192,192,0.18)" if not is_light else "rgba(8,138,135,0.12)"

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
* {{ margin:0; padding:0; box-sizing:border-box }}
html, body {{ background:{BG}; overflow:hidden; width:100%; height:100% }}
svg {{ display:block; width:100%; height:{height_px}px; cursor:grab; user-select:none }}
svg.panning {{ cursor:grabbing }}
[data-eid] {{ cursor:pointer }}
[data-room] {{ cursor:pointer; transition: fill-opacity .15s; }}
[data-room]:hover {{ fill-opacity: .98 !important; filter: brightness(1.06); }}
#tt {{
  position:fixed; pointer-events:none; display:none;
  background:{_tt_bg}; color:{_tt_clr}; border:1px solid {_tt_brd};
  border-radius:6px; padding:6px 10px; font-size:11px; font-family:'Suisse Intl','Suisse Int\'l','Inter','Segoe UI',sans-serif;
  line-height:1.5; box-shadow:0 4px 16px rgba(0,0,0,.25); z-index:9999; max-width:180px;
  white-space:pre-line;
}}
#tt .tt-name {{ font-weight:700; font-size:12px; color:{_tt_brd}; margin-bottom:2px; }}
#vis-tb {{
  position:fixed; top:8px; right:8px; z-index:1000;
  display:flex; align-items:center; gap:2px;
  background:{_tb_bg}; border:1px solid {_tb_brd};
  border-radius:8px; padding:3px 5px;
  backdrop-filter:blur(6px);
}}
.tb-btn {{
  background:none; border:none; cursor:pointer;
  color:{_tb_clr}; font-size:.60rem; font-family:'Suisse Intl','Suisse Int\'l','Inter','Segoe UI',sans-serif;
  font-weight:700; letter-spacing:.6px; text-transform:uppercase;
  padding:3px 8px; border-radius:5px;
  transition:background .12s,color .12s;
}}
.tb-btn:hover {{ background:{_tb_act_bg}; color:{_tb_act_clr}; }}
.tb-btn.tb-on {{ background:{_tb_act_bg}; color:{_tb_act_clr}; }}
.tb-sep {{ width:1px; height:13px; background:{_tb_brd}; margin:0 3px; flex-shrink:0; }}
</style></head>
<body>
<div id="tt"><span class="tt-name" id="tt-name"></span><span id="tt-body"></span></div>
<svg xmlns="http://www.w3.org/2000/svg"
     viewBox="{vb_x} {vb_y} {vb_w} {vb_h}"
     preserveAspectRatio="xMidYMid meet">
  <rect x="{vb_x}" y="{vb_y}" width="{vb_w}" height="{vb_h}" fill="{BG}"/>
  {svg_inner}
</svg>
<div id="vis-tb">
  <button id="tb-vm"   class="tb-btn" onclick="tbToggleVM()">{_tb_vm_txt}</button>
  <div class="tb-sep"></div>
  <button id="tb-lab"  class="tb-btn" onclick="tbToggleLabels()">Labels</button>
  <button id="tb-diff" class="tb-btn" onclick="tbToggleDiff()">Diff</button>
  <button id="tb-auto" class="tb-btn" onclick="tbToggleAuto()">Auto</button>
</div>
<script>
(function(){{
  // ── Toolbar state ──────────────────────────────────────────────────────────
  var _tbVM    = '{_tb_vm_txt}';
  var _tbLab   = {_tb_lab_js};
  var _tbDiff  = {_tb_diff_js};
  var _tbAuto  = {_tb_auto_js};

  function tbPost(key, val) {{
    window.parent.postMessage({{type:'toolbar', key:key, val:String(val)}}, '*');
  }}
  function tbUI() {{
    var bvm   = document.getElementById('tb-vm');
    var blab  = document.getElementById('tb-lab');
    var bdiff = document.getElementById('tb-diff');
    var bauto = document.getElementById('tb-auto');
    if(bvm)  {{ bvm.textContent = _tbVM; bvm.className  = 'tb-btn' + (_tbVM === '3D' ? ' tb-on' : ''); }}
    if(blab)  blab.className  = 'tb-btn' + (_tbLab  ? ' tb-on' : '');
    if(bdiff) bdiff.className = 'tb-btn' + (_tbDiff ? ' tb-on' : '');
    if(bauto) bauto.className = 'tb-btn' + (_tbAuto ? ' tb-on' : '');
  }}
  function tbToggleVM()     {{ _tbVM  = _tbVM==='2D'?'3D':'2D'; tbPost('vm',    _tbVM);           tbUI(); }}
  function tbToggleLabels() {{ _tbLab  = !_tbLab;               tbPost('labels', _tbLab?'1':'0'); tbUI(); }}
  function tbToggleDiff()   {{ _tbDiff = !_tbDiff;              tbPost('diff',   _tbDiff?'1':'0'); tbUI(); }}
  function tbToggleAuto()   {{ _tbAuto = !_tbAuto;              tbPost('auto',   _tbAuto?'1':'0'); tbUI(); }}
  tbUI();

  var HL = {hl_json};
  var svg = document.querySelector('svg');
  var tt  = document.getElementById('tt');
  var ttName = document.getElementById('tt-name');
  var ttBody = document.getElementById('tt-body');
  var vbArr = svg.getAttribute('viewBox').split(' ').map(Number);
  var origX = vbArr[0], origY = vbArr[1], origW = vbArr[2], origH = vbArr[3];
  var vbx = origX, vby = origY, vbw = origW, vbh = origH;

  function setVB(){{ svg.setAttribute('viewBox', vbx+' '+vby+' '+vbw+' '+vbh); }}

  // Restore highlight for already-selected element
  if(HL) {{
    document.querySelectorAll('[data-eid="'+HL+'"]').forEach(function(el){{
      if(el.getAttribute('stroke') !== 'transparent')
        el.style.filter = 'brightness(1.8) drop-shadow(0 0 3px {SEL_C})';
    }});
  }}

  // ── Room hover tooltip ────────────────────────────────────────────────────
  document.querySelectorAll('[data-room]').forEach(function(el){{
    var name = el.getAttribute('data-name') || '';
    el.addEventListener('mouseenter', function(e){{
      if(!name) return;
      ttName.textContent = name;
      // Try to extract area from title
      var titleEl = el.querySelector('title');
      var extra = titleEl ? titleEl.textContent.replace(name,'').replace(/^\\n/,'') : '';
      ttBody.textContent = extra;
      tt.style.display = 'block';
      positionTT(e);
    }});
    el.addEventListener('mousemove', positionTT);
    el.addEventListener('mouseleave', function(){{ tt.style.display = 'none'; }});
  }});

  function positionTT(e){{
    var x = e.clientX + 12, y = e.clientY + 12;
    var w = tt.offsetWidth, h = tt.offsetHeight;
    if(x + w > window.innerWidth  - 8) x = e.clientX - w - 8;
    if(y + h > window.innerHeight - 8) y = e.clientY - h - 8;
    tt.style.left = x + 'px';
    tt.style.top  = y + 'px';
  }}

  // ── Room click: flash highlight ───────────────────────────────────────────
  document.querySelectorAll('[data-room]').forEach(function(el){{
    el.addEventListener('click', function(e){{
      if(moved) return;
      // deselect structural elements
      document.querySelectorAll('[data-eid]').forEach(function(x){{ x.style.filter=''; }});
      el.style.filter = 'brightness(1.12) saturate(1.4)';
      setTimeout(function(){{ el.style.filter=''; }}, 600);
      window.parent.postMessage({{type:'selectElement', elementId:''}}, '*');
    }});
  }});

  // ── Zoom on wheel ─────────────────────────────────────────────────────────
  svg.addEventListener('wheel', function(e){{
    e.preventDefault();
    var rect = svg.getBoundingClientRect();
    var px = (e.clientX - rect.left) / rect.width;
    var py = (e.clientY - rect.top)  / rect.height;
    var factor = e.deltaY < 0 ? 0.87 : 1/0.87;
    var cx = vbx + px*vbw, cy = vby + py*vbh;
    vbw *= factor; vbh *= factor;
    vbx = cx - px*vbw; vby = cy - py*vbh;
    setVB();
  }}, {{passive:false}});

  // ── Pan on drag ───────────────────────────────────────────────────────────
  var drag = false, moved = false, lx, ly;
  svg.addEventListener('mousedown', function(e){{
    drag=true; moved=false; lx=e.clientX; ly=e.clientY;
    svg.classList.add('panning');
    tt.style.display = 'none';
  }});
  document.addEventListener('mousemove', function(e){{
    if(!drag) return;
    var dx=e.clientX-lx, dy=e.clientY-ly;
    if(Math.abs(dx)+Math.abs(dy) > 2) moved=true;
    var rect=svg.getBoundingClientRect();
    vbx -= dx*vbw/rect.width; vby -= dy*vbh/rect.height;
    lx=e.clientX; ly=e.clientY; setVB();
  }});
  document.addEventListener('mouseup', function(){{ drag=false; svg.classList.remove('panning'); }});

  // ── Double-click to reset zoom ────────────────────────────────────────────
  svg.addEventListener('dblclick', function(e){{
    if(!e.target.closest('[data-eid]') && !e.target.closest('[data-room]')){{
      vbx=origX; vby=origY; vbw=origW; vbh=origH; setVB();
    }}
  }});

  // ── Click structural elements ─────────────────────────────────────────────
  document.querySelectorAll('[data-eid]').forEach(function(el){{
    var id = el.getAttribute('data-eid');
    el.addEventListener('click', function(e){{
      if(moved) return;
      e.stopPropagation();
      document.querySelectorAll('[data-eid]').forEach(function(x){{ x.style.filter=''; }});
      document.querySelectorAll('[data-eid="'+id+'"]').forEach(function(x){{
        if(x.getAttribute('stroke') !== 'transparent')
          x.style.filter = 'brightness(1.8) drop-shadow(0 0 3px {SEL_C})';
      }});
      window.parent.postMessage({{type:'selectElement', elementId:id}}, '*');
    }});
  }});

  // ── Click empty to deselect ───────────────────────────────────────────────
  svg.addEventListener('click', function(e){{
    if(!moved && !e.target.closest('[data-eid]') && !e.target.closest('[data-room]')){{
      document.querySelectorAll('[data-eid]').forEach(function(x){{ x.style.filter=''; }});
      window.parent.postMessage({{type:'selectElement', elementId:''}}, '*');
    }}
  }});
}})();
</script>
</body></html>"""


def _count_elements(layout: dict) -> tuple[int, int]:
    cols  = sum(1 for el in layout.get("structure", []) if len(el.get("geometry", [])) == 1)
    beams = sum(1 for el in layout.get("structure", []) if len(el.get("geometry", [])) == 2)
    return cols, beams


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
    try:
        from nodes.tools import build_structural_grid_with_options
        bundle = build_structural_grid_with_options(layout, "", material=material)
        return bundle.get("options", [])
    except Exception as e:
        st.warning(f"Grid options error: {e}")
        return []




def _get_failure_alternatives(eval_result: dict, material: str) -> list[str]:
    try:
        from nodes.evaluate import _build_failure_alternatives
        return _build_failure_alternatives(eval_result, [], material)
    except Exception:
        return []


def _run_comparison(before_str: str, after_str: str) -> str:
    try:
        from _runtime.bootstrap import bootstrap
        from nodes.comparison import build_comparison_node
        ctx  = bootstrap()
        node = build_comparison_node(ctx.llm)
        state: dict = {
            "layout_json_string":   after_str,
            "layout_before_change": before_str,
            "came_from":            "structural_change",
            "messages":             [],
            "cycle":                0,
        }
        out = node(state)
        return out.get("comparison_result", "")
    except Exception:
        return ""



def _apply_alternative(alt: str, layout_str: str, material: str,
                        sdl: float, ll: float) -> tuple[str, dict | None]:
    from nodes.modify import (
        upgrade_element_section, add_midspan_column,
        apply_material_override, BEAM_SECTION_UPGRADE, BEAM_DIM_UPGRADE,
        COL_SECTION_UPGRADE, COL_DIM_UPGRADE, BASE_MATERIALS,
    )
    from nodes.evaluate import evaluate_structure

    if re.match(r"Auto-upgrade \d+ failing beam", alt, re.IGNORECASE):
        ev = st.session_state.eval_result or {}
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
        return layout_str, ev

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

def _run_agent_chat(prompt: str, layout: dict, eval_result: dict | None = None) -> str:
    try:
        from _runtime.bootstrap import bootstrap
        from _runtime.llm import call_llm
        from nodes.reason import SYSTEM_PROMPT
        from nodes.tools import get_action_tools
        from graph import _format_tool_catalog

        ctx          = bootstrap()
        tool_catalog = _format_tool_catalog(get_action_tools())
        structure    = layout.get("structure", [])
        beams        = [el for el in structure if len(el.get("geometry", [])) == 2]
        cols         = [el for el in structure if len(el.get("geometry", [])) == 1]

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

        last_err: Exception | None = None
        result = None
        for _attempt in range(2):
            try:
                result = call_llm(ctx.llm, SYSTEM_PROMPT, [context_msg], tool_catalog)
                break
            except Exception as _e:
                last_err = _e
                if _attempt == 0:
                    import time as _time; _time.sleep(1)
        if result is None:
            raise last_err  # type: ignore[misc]

        if result.get("action") == "tool":
            calls = result.get("tool_calls", [])
            if any(c.get("name") == "tag_and_audit" for c in calls):
                return "GENERATE_GRID"
            if calls:
                first = calls[0]
                return (
                    f"Agent wants to apply **{first.get('name', 'action')}** — "
                    "use the controls in the left panel to proceed."
                )

        resp = result.get("final_response", "")
        if not resp:
            return "EVALUATE"
        return resp
    except Exception as e:
        msg = str(e)
        if "empty response" in msg.lower() or "unavailable" in msg.lower() or "rate-limited" in msg.lower():
            return "The AI model is not responding right now — please try again in a moment."
        return f"Agent error: {msg}"


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
        "last_comparison": None,
        "material":        "RCC",
        "sdl_kNm2":        3.5,
        "live_load_kNm2":  2.0,
        "grid_options":    [],
        "selected_grid":   None,
        "output_log":      [],
        "selected_el":     "",
        "_last_sel_applied": "\x00",
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
[data-testid="block-container"]{{padding:.3rem 1rem .2rem!important}}
section[data-testid="stSidebar"]{{background:{_SB}!important;border-right:1px solid {_BORD}!important}}
section[data-testid="stSidebar"]>div:first-child{{padding:14px 14px 10px!important}}
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
.chat-q{{background:{_CHAT_Q};border-left:3px solid {_ACC};border-radius:3px;padding:4px 7px;margin-bottom:3px;font-size:.70rem;color:{_TEXT};line-height:1.4;font-family:{_F}}}
.chat-a{{background:{_CHAT_A};border-left:3px solid {_ACC2};border-radius:3px;padding:4px 7px;margin-bottom:3px;font-size:.70rem;color:{_TEXT};line-height:1.4;font-family:{_F}}}
.agent-resp{{background:{_CHAT_Q};border-left:3px solid {_ACC};padding:7px 10px;border-radius:3px;font-size:.70rem;color:{_TEXT};line-height:1.5;margin-top:5px;font-family:{_F}}}
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
  width:280px!important;min-width:280px!important;max-width:280px!important;
  transform:translateX(0)!important;transition:none!important;visibility:visible!important}}
section[data-testid="stSidebar"]>div:first-child{{
  width:280px!important;padding:12px 12px 10px!important;overflow-y:auto!important}}
.inp-toggle button{{
  padding:1px 6px!important;min-height:unset!important;font-size:.70rem!important;
  background:transparent!important;border:1px solid {_BORD}!important;
  color:{_MUT}!important;border-radius:4px!important;line-height:1.4!important;font-family:{_F}!important}}
"""

st.markdown(f"<style>{_CSS}</style>", unsafe_allow_html=True)

# ─── JS bridge ────────────────────────────────────────────────────────────────
components.html("""
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
      var prev=url.searchParams.get('_sel')||'';
      if(eid===prev)return;
      if(eid){url.searchParams.set('_sel',eid);}else{url.searchParams.delete('_sel');}
      _rerun(url);
    } else if(ev.data.type==='toolbar'){
      url.searchParams.set('_tb_'+ev.data.key, ev.data.val);
      _rerun(url);
    }
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

        # ── Define Loads ──────────────────────────────────────────────────────
        st.markdown(
            f'<div class="inp-sub-hdr">Define Loads</div>',
            unsafe_allow_html=True,
        )
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
        )
        if mat_choice != _mat_now:
            st.session_state.material     = mat_choice
            st.session_state.grid_options = []
            st.rerun()

    # ── Generate Grid + Options ───────────────────────────────────────────────
    st.markdown(
        f'<div style="margin:8px 0 6px;border-top:1px solid {_BORD}"></div>',
        unsafe_allow_html=True,
    )
    _gopts_sb = st.session_state.grid_options
    if st.button("⊕  Generate Grid", use_container_width=True,
                 type="primary", key="btn_gen_main"):
        with st.spinner("Computing grid options…"):
            st.session_state.grid_options = _run_grid_options(layout_obj, _mat_now)
        for _gi, _gopt_g in enumerate(st.session_state.grid_options, 1):
            (REPO_ROOT / f"team_01_option_{_gi}.json").write_text(
                json.dumps(_gopt_g["layout"], indent=2, ensure_ascii=False),
                encoding="utf-8")
        st.session_state["selected_opt_bar_idx"] = -1
        st.rerun()

    if _gopts_sb:
        _ob1, _ob2, _ob3 = st.columns(3, gap="small")
        for _bi, (_obc, _gopt_sb) in enumerate(zip([_ob1, _ob2, _ob3], _gopts_sb[:3])):
            _is_sel_sb = st.session_state.get("selected_opt_bar_idx", -1) == _bi
            with _obc:
                if st.button(
                    f"Option {_bi+1}", key=f"sb_opt_{_bi}",
                    use_container_width=True,
                    type="primary" if _is_sel_sb else "secondary",
                ):
                    _opt_ev = _gopt_sb.get("evaluation")
                    if _opt_ev is None:
                        with st.spinner(f"Evaluating Option {_bi+1}…"):
                            _opt_ev = _run_evaluate(
                                json.dumps(_gopt_sb.get("layout", {})),
                                sdl=_sdl_now, ll=_ll_now)
                        if _opt_ev:
                            st.session_state.grid_options[_bi]["evaluation"] = _opt_ev
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
        for _msg in _history[-3:]:
            _q = _msg.get("prompt", "")
            _a = _msg.get("response", "")
            if _q:
                _bub += f'<div class="chat-q">{_q[:90]}{"…" if len(_q)>90 else ""}</div>'
            if _a:
                _bub += f'<div class="chat-a">{_a[:120]}{"…" if len(_a)>120 else ""}</div>'
        st.markdown(
            f'<div style="max-height:90px;overflow-y:auto;margin-bottom:5px">{_bub}</div>',
            unsafe_allow_html=True,
        )

    with st.form("agent_form", clear_on_submit=True):
        prompt_input = st.text_area(
            "Ask agent",
            placeholder="Ask anything about your structure…\ne.g. reduce deflection in beam B1",
            label_visibility="collapsed",
            height=60,
        )
        submitted = st.form_submit_button("Ask Agent  ›", use_container_width=True)

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
_hcols = st.columns([5, 1, 1, 0.35], gap="small")

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
with _hcols[3]:
    with st.popover("⋮", use_container_width=True):
        st.markdown(
            f'<div style="font-size:.72rem;font-weight:700;color:#c8eeed;'
            f'margin-bottom:6px">PermanenceOS</div>'
            f'<div style="font-size:.65rem;color:#5a9090">AI Structural Design</div>',
            unsafe_allow_html=True,
        )
        st.divider()
        if st.button("Rerun", key="btn_menu_rerun", use_container_width=True):
            st.rerun()
        _theme_lbl = "Switch to Light" if not _is_light else "Switch to Dark"
        if st.button(_theme_lbl, key="btn_menu_theme", use_container_width=True):
            st.session_state.theme        = "light" if not _is_light else "dark"
            st.session_state.viewer_nonce += 1
            st.rerun()
        st.download_button(
            "Export JSON",
            data=json.dumps(layout_obj, indent=2, ensure_ascii=False),
            file_name="layout_export.json",
            mime="application/json",
            use_container_width=True,
            key="btn_menu_export",
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

    _sb_col, _run_col, _snap_col = st.columns([3.5, 1.5, 1.5], gap="small")
    with _sb_col:
        st.markdown(_sbar_html, unsafe_allow_html=True)
    with _run_col:
        _run_clicked = st.button(
            "▶  Run Structural Analysis",
            type="primary", use_container_width=True, key="btn_run_analysis",
        )
    with _snap_col:
        _sn_n = len(st.session_state.snapshots) + 1
        _snap_clicked = st.button(
            f"Save Snapshot #{_sn_n}", key="btn_snap", use_container_width=True,
        )

    if _snap_clicked:
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

    # ── Toolbar state (overlay rendered inside floor plan HTML) ───────────────
    _vm = st.session_state.get("view_mode", "2D")

    _snaps = st.session_state.snapshots
    if _snaps:
        _pills = "".join(
            f'<span class="snap-pill{" snap-pill-active" if i==len(_snaps)-1 else ""}">'
            f'{s["label"]}</span>'
            for i, s in enumerate(_snaps)
        )
        st.markdown(_pills, unsafe_allow_html=True)

    # ── Option selection (handled by sidebar buttons; resolve preview file here) ─
    _gopts_bar = st.session_state.grid_options
    _sel_opt_i = st.session_state.get("selected_opt_bar_idx", -1)

    _preview_opt_file = ""
    if _gopts_bar and 0 <= _sel_opt_i < len(_gopts_bar):
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
    _main_col, _right_col = st.columns([1.65, 0.75], gap="small")

    with _main_col:
        if _vm == "2D":
            components.html(
                _render_floor_plan_html(
                    _plan_layout, eval_result=er,
                    highlight=st.session_state.selected_el,
                    labels=st.session_state.labels_on,
                    height_px=510, is_light=_is_light,
                    view_mode=_vm,
                    diff_on=st.session_state.compare_mode,
                    auto_on=st.session_state.get("auto_eval", True),
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
        _rt1, _rt2 = st.tabs(["  ANALYSIS  ", "  DESIGN DETAILS  "])

        with _rt1:
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
                                    use_container_width=True,
                                ):
                                    st.session_state["preview_alt"] = _alt
                                    st.session_state.viewer_nonce += 1
                                    st.rerun()
                            with _bc2:
                                if st.button(
                                    "Apply Change", key=f"rec_apply_{_ri}",
                                    use_container_width=True, type="primary",
                                ):
                                    _new_ls, _new_ev = _apply_alternative(
                                        _alt, json.dumps(layout_obj),
                                        _mat_now, _sdl_now, _ll_now,
                                    )
                                    if _new_ev:
                                        BEFORE_LAYOUT_PATH.write_text(
                                            json.dumps(layout_obj), encoding="utf-8"
                                        )
                                        _write_json(EDITED_LAYOUT_PATH, json.loads(_new_ls))
                                        st.session_state.eval_result = _new_ev
                                        st.session_state.eval_alts = _get_failure_alternatives(
                                            _new_ev, _mat_now
                                        )
                                        st.session_state.viewer_nonce += 1
                                        st.rerun()

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
