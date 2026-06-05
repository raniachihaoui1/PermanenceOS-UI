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
PYTHON_DIR          = Path(__file__).resolve().parent
LOGO_PATH           = PYTHON_DIR / "Assets" / "Logo.png"

_logo_b64 = ""
if LOGO_PATH.exists():
    try:
        _logo_b64 = base64.b64encode(LOGO_PATH.read_bytes()).decode()
    except Exception:
        pass

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
        parts.append(
            f'<polygon points="{pts_str}" fill="{ROOM}" fill-opacity="0.88" '
            f'stroke="{FG}" stroke-opacity="0.22" stroke-width="0.8" '
            f'vector-effect="non-scaling-stroke"/>'
        )
        if label and w > u * 3:
            parts.append(
                f'<text x="{cx}" y="{fy(cy)}" text-anchor="middle" '
                f'dominant-baseline="central" font-family="monospace" '
                f'font-size="{u*1.05}" fill="{FG}" fill-opacity="0.50">{label}</text>'
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

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
* {{ margin:0; padding:0; box-sizing:border-box }}
html, body {{ background:{BG}; overflow:hidden; width:100%; height:100% }}
svg {{ display:block; width:100%; height:{height_px}px; cursor:grab; user-select:none }}
svg.panning {{ cursor:grabbing }}
[data-eid] {{ cursor:pointer }}
</style></head>
<body>
<svg xmlns="http://www.w3.org/2000/svg"
     viewBox="{vb_x} {vb_y} {vb_w} {vb_h}"
     preserveAspectRatio="xMidYMid meet">
  <rect x="{vb_x}" y="{vb_y}" width="{vb_w}" height="{vb_h}" fill="{BG}"/>
  {svg_inner}
</svg>
<script>
(function(){{
  var HL = {hl_json};
  var svg = document.querySelector('svg');
  var vbArr = svg.getAttribute('viewBox').split(' ').map(Number);
  var origX = vbArr[0], origY = vbArr[1], origW = vbArr[2], origH = vbArr[3];
  var vbx = origX, vby = origY, vbw = origW, vbh = origH;

  function setVB(){{
    svg.setAttribute('viewBox', vbx+' '+vby+' '+vbw+' '+vbh);
  }}

  // Restore highlight for already-selected element
  if(HL) {{
    document.querySelectorAll('[data-eid="'+HL+'"]').forEach(function(el){{
      if(el.getAttribute('stroke') !== 'transparent')
        el.style.filter = 'brightness(1.8) drop-shadow(0 0 3px {SEL_C})';
    }});
  }}

  // Zoom on wheel (zoom toward mouse position)
  svg.addEventListener('wheel', function(e){{
    e.preventDefault();
    var rect = svg.getBoundingClientRect();
    var px = (e.clientX - rect.left) / rect.width;
    var py = (e.clientY - rect.top) / rect.height;
    var factor = e.deltaY < 0 ? 0.87 : 1/0.87;
    var cx = vbx + px * vbw, cy = vby + py * vbh;
    vbw *= factor; vbh *= factor;
    vbx = cx - px * vbw; vby = cy - py * vbh;
    setVB();
  }}, {{passive: false}});

  // Pan on drag
  var drag = false, moved = false, lx, ly;
  svg.addEventListener('mousedown', function(e){{
    drag = true; moved = false;
    lx = e.clientX; ly = e.clientY;
    svg.classList.add('panning');
  }});
  document.addEventListener('mousemove', function(e){{
    if(!drag) return;
    var dx = e.clientX - lx, dy = e.clientY - ly;
    if(Math.abs(dx) + Math.abs(dy) > 2) moved = true;
    var rect = svg.getBoundingClientRect();
    vbx -= dx * vbw / rect.width;
    vby -= dy * vbh / rect.height;
    lx = e.clientX; ly = e.clientY;
    setVB();
  }});
  document.addEventListener('mouseup', function(){{
    drag = false;
    svg.classList.remove('panning');
  }});

  // Double-click empty area to reset zoom/pan
  svg.addEventListener('dblclick', function(e){{
    if(!e.target.closest('[data-eid]')){{
      vbx = origX; vby = origY; vbw = origW; vbh = origH;
      setVB();
    }}
  }});

  // Click elements: instant local highlight + notify Streamlit
  document.querySelectorAll('[data-eid]').forEach(function(el){{
    var id = el.getAttribute('data-eid');
    el.addEventListener('click', function(e){{
      if(moved) return;
      e.stopPropagation();
      document.querySelectorAll('[data-eid]').forEach(function(x){{ x.style.filter = ''; }});
      document.querySelectorAll('[data-eid="'+id+'"]').forEach(function(x){{
        if(x.getAttribute('stroke') !== 'transparent')
          x.style.filter = 'brightness(1.8) drop-shadow(0 0 3px {SEL_C})';
      }});
      window.parent.postMessage({{type:'selectElement', elementId:id}}, '*');
    }});
  }});

  // Click empty SVG to deselect
  svg.addEventListener('click', function(e){{
    if(!moved && !e.target.closest('[data-eid]')){{
      document.querySelectorAll('[data-eid]').forEach(function(x){{ x.style.filter = ''; }});
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


def _run_cost_flex(before_str: str, after_str: str) -> dict | None:
    try:
        from nodes.cost_flexibility import build_cost_flexibility_node
        node = build_cost_flexibility_node()
        state: dict = {
            "layout_json_string":          after_str,
            "layout_before_change":        before_str,
            "original_layout_json_string": before_str,
            "came_from":                   "modify",
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

        result = call_llm(ctx.llm, SYSTEM_PROMPT, [context_msg], tool_catalog)

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
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ── Page setup ─────────────────────────────────────────────────────────────────

st.set_page_config(page_title="PermanenceOS", layout="wide", initial_sidebar_state="collapsed")
_ensure_session()

_pending_sel = st.query_params.get("_sel", "")
if _pending_sel != st.session_state.get("_last_sel_applied", "\x00"):
    st.session_state.selected_el = _pending_sel
    st.session_state["_last_sel_applied"] = _pending_sel

try:
    _is_light = (st.get_option("theme.base") or "dark") == "light"
except Exception:
    _is_light = False

_DARK = """
  html,body,[data-testid="stApp"],[data-testid="stAppViewContainer"],[data-testid="stMain"]{background:#071a1a!important}
  [data-testid="stHeader"]{background:#071a1a!important;border-bottom:1px solid #1a4040!important}
  [role="tabpanel"]{background:#071a1a!important}
  [data-testid="stTabPanel"]{background:#071a1a!important}
  [data-testid="stVerticalBlock"]{background:transparent}
  [data-testid="stForm"]{background:#0d2828!important;border:1px solid #1a5555!important;border-radius:8px!important}
  [data-testid="stTextArea"] textarea{background:#0d2828!important;color:#c8eeed!important;border-color:#1a5555!important}
  [data-testid="stTextInput"] input{background:#0d2828!important;color:#c8eeed!important;border-color:#1a5555!important}
  [data-baseweb="select"] > div{background:#0d2828!important;border-color:#1a5555!important;color:#c8eeed!important}
  [data-baseweb="popover"] [role="listbox"]{background:#0d2828!important}
  [data-baseweb="popover"] [role="option"]{color:#c8eeed!important}
  [data-testid="stExpander"] details{background:#0d2828!important;border:1px solid #1a5555!important}
  [data-testid="stExpander"] summary{color:#2ac0c0!important}
  [data-testid="stFileUploader"] section{background:#0d2828!important;border-color:#1a5555!important}
  [data-testid="stSlider"] [data-baseweb="slider"] [role="slider"]{background:#2ac0c0!important}
  [data-testid="stRadio"] label p{color:#a0d8d8!important}
  [data-testid="stCheckbox"] label p{color:#a0d8d8!important}
  [data-testid="stSelectSlider"] [data-testid="stMarkdown"]{color:#c8eeed!important}
  p,label{color:#c8eeed}
  [data-testid="stWidgetLabel"] p{color:#a0d8d8!important}
  [data-testid="stMetricLabel"] p{color:#6ab8b8!important;font-size:.72rem}
  [data-testid="stMetricValue"]{color:#c8eeed!important}
  [data-testid="stCaption"] p,[data-testid="stCaptionContainer"] p{color:#6ab8b8!important}
  small{color:#6ab8b8!important}
  [data-testid="stMarkdown"] p{color:#c8eeed}
  .stat-chip{display:inline-block;background:#0d3030;border:1px solid #1a5555;border-radius:4px;padding:2px 10px;margin-left:5px;font-size:.78rem;color:#a0d8d8}
  .stat-chip b{color:#c8eeed}
  .needs-review{background:#3a1a08;color:#ff9860;border-color:#7a4020}
  .panel-hdr{font-size:.70rem;font-weight:700;color:#2ac0c0;letter-spacing:1.5px;text-transform:uppercase;margin:8px 0 4px;padding-bottom:0}
  .chat-q{background:#0a3030;border-left:3px solid #2ac0c0;border-radius:3px;padding:5px 8px;margin-bottom:4px;font-size:.73rem;color:#a0c8c8;line-height:1.4}
  .chat-a{background:#071a1a;border-left:3px solid #40d090;border-radius:3px;padding:5px 8px;margin-bottom:4px;font-size:.73rem;color:#c8eeed;line-height:1.4}
  .grid-card{border:1px solid #1a5555;border-radius:6px;padding:7px 10px;margin-bottom:4px;background:#0d2828}
  .grid-card-active{border-color:#2ac0c0;background:#0d3030}
  .grid-label{font-size:.86rem;font-weight:700;color:#c8eeed}
  .grid-spacing{font-size:.73rem;color:#6ab8b8}
  .grid-stats{font-size:.76rem;color:#5a9090;margin-top:2px}
  .eval-big{font-size:2.6rem;font-weight:800;line-height:1.1}
  .eval-label{font-size:.68rem;color:#5a9090;text-transform:uppercase;letter-spacing:.5px}
  .eval-fail{color:#ff5050}.eval-pass{color:#40d090}
  .crit-item{background:#0d2828;border-left:3px solid #cc3030;padding:5px 8px;margin-bottom:4px;border-radius:2px;font-size:.76rem;color:#a0d8d8}
  .pass-badge{background:#0a4040;color:#2ac0c0;padding:2px 10px;border-radius:4px;font-weight:700;font-size:.78rem;display:inline-block;margin:4px 0}
  .agent-response{background:#0d2828;border-left:3px solid #2ac0c0;padding:8px 12px;border-radius:3px;font-size:.80rem;color:#c8eeed;margin-top:6px;line-height:1.5}
  .cost-box{background:#0d2828;border:1px solid #1a5555;border-radius:6px;padding:10px 12px;margin-top:6px}
  .alt-btn{background:#0d3030;border:1px solid #1a5555;border-radius:4px;padding:4px 8px;margin-bottom:4px;font-size:.76rem;color:#6ab8b8;cursor:pointer}
  .snap-pill{display:inline-block;background:#0d3030;border:1px solid #1a5555;color:#6ab8b8;padding:3px 10px;border-radius:10px;margin:2px;font-size:.74rem}
  .snap-pill-active{background:#1a5555;border-color:#2ac0c0;color:#2ac0c0;font-weight:700}
  .viewer-label{font-size:.70rem;color:#5a9090;letter-spacing:1px;text-transform:uppercase;margin-bottom:4px}
  .state-pill{display:inline-block;background:#0d3030;color:#6ab8b8;padding:2px 8px;border-radius:10px;margin:2px;font-size:.74rem}
  .log-entry{background:#0d2828;border-left:3px solid #2ac0c0;padding:5px 8px;margin-bottom:4px;border-radius:3px;font-size:.79rem;color:#8abfbf}
  [data-testid="stFileUploaderDropzoneInstructions"]{display:none!important}
  [data-testid="stFileUploaderDropzone"]{min-height:auto!important;padding:3px 8px!important;background:#0d2828!important;border-color:#1a5555!important}
"""
_LIGHT = """
  [data-testid="stAppViewContainer"]{background:#f5f7fa}
  .stat-chip{display:inline-block;background:#fff;border:1px solid #c0d8d8;border-radius:4px;padding:2px 10px;margin-left:5px;font-size:.78rem;color:#2a5050}
  .stat-chip b{color:#088a87}
  .needs-review{background:#fff0e8;color:#c04010;border-color:#e08060}
  .panel-hdr{font-size:.72rem;font-weight:700;color:#088a87;letter-spacing:1.5px;text-transform:uppercase;margin:10px 0 5px;padding-bottom:3px;border-bottom:1px solid #b0d8d8}
  .grid-card{border:1px solid #c8dede;border-radius:6px;padding:7px 10px;margin-bottom:4px;background:#fff}
  .grid-card-active{border-color:#088a87;background:#e6f7f7}
  .grid-label{font-size:.86rem;font-weight:700;color:#1a2a30}
  .grid-spacing{font-size:.73rem;color:#4a7070}
  .grid-stats{font-size:.76rem;color:#5a7070;margin-top:2px}
  .eval-big{font-size:2.6rem;font-weight:800;line-height:1.1}
  .eval-label{font-size:.68rem;color:#4a7070;text-transform:uppercase;letter-spacing:.5px}
  .eval-fail{color:#cc2020}.eval-pass{color:#088a87}
  .crit-item{background:#fff4f4;border-left:3px solid #cc3030;padding:5px 8px;margin-bottom:4px;border-radius:2px;font-size:.76rem;color:#2a3040}
  .pass-badge{background:#d4f0ee;color:#065f5d;padding:2px 10px;border-radius:4px;font-weight:700;font-size:.78rem;display:inline-block;margin:4px 0}
  .agent-response{background:#e8f7f7;border-left:3px solid #088a87;padding:8px 12px;border-radius:3px;font-size:.80rem;color:#1a2a30;margin-top:6px;line-height:1.5}
  .cost-box{background:#f0f9f9;border:1px solid #b0d8d8;border-radius:6px;padding:10px 12px;margin-top:6px}
  .alt-btn{background:#e6f0f0;border:1px solid #a0c8c8;border-radius:4px;padding:4px 8px;margin-bottom:4px;font-size:.76rem;color:#1a4040;cursor:pointer}
  .snap-pill{display:inline-block;background:#e6f0f0;border:1px solid #a0c8c8;color:#1a4040;padding:3px 10px;border-radius:10px;margin:2px;font-size:.74rem}
  .snap-pill-active{background:#c0e4e4;border-color:#088a87;color:#065f5d;font-weight:700}
  .viewer-label{font-size:.70rem;color:#5a7070;letter-spacing:1px;text-transform:uppercase;margin-bottom:4px}
  .state-pill{display:inline-block;background:#e6f0f0;color:#2a5050;padding:2px 8px;border-radius:10px;margin:2px;font-size:.74rem}
  .log-entry{background:#e8f7f7;border-left:3px solid #088a87;padding:5px 8px;margin-bottom:4px;border-radius:3px;font-size:.79rem;color:#1a3030}
  [data-testid="stFileUploaderDropzoneInstructions"]{display:none!important}
  [data-testid="stFileUploaderDropzone"]{min-height:auto!important;padding:3px 8px!important}
"""
_fail_ct = ".fail-ct{color:#ff6060;font-weight:700}.pass-ct{color:#40c040;font-weight:700}"
if _is_light:
    _fail_ct = ".fail-ct{color:#cc2020;font-weight:700}.pass-ct{color:#208020;font-weight:700}"

st.markdown(
    f"<style>"
    f"[data-testid='block-container']{{padding-top:.6rem;padding-bottom:.3rem}}"
    f"div[data-testid='stTabs'] button{{font-size:.82rem}}"
    f"{_fail_ct}"
    f"{''.join((_LIGHT if _is_light else _DARK).splitlines())}"
    f"</style>",
    unsafe_allow_html=True,
)

# ── Load working layout ────────────────────────────────────────────────────────

layout_obj      = _load_working_layout()
n_cols, n_beams = _count_elements(layout_obj)
er              = st.session_state.eval_result
has_failures    = (
    er is not None
    and (er.get("summary", {}).get("beam_failures", 0) > 0
         or er.get("summary", {}).get("column_failures", 0) > 0)
)

# ── Header (compact dark bar) ──────────────────────────────────────────────────

_logo_part = (
    f'<img src="data:image/png;base64,{_logo_b64}" '
    f'style="height:22px;width:auto;margin-right:10px;vertical-align:middle">'
    if _logo_b64 else
    '<span style="font-size:.78rem;font-weight:800;color:#2ac0c0;letter-spacing:2px;margin-right:12px">PERMANENCEOS</span>'
)
_cf_hdr   = st.session_state.get("cost_flexibility")
_review   = '<span class="stat-chip needs-review">&#9888;</span>' if has_failures else ""
_cost_chip = (
    f'<span class="stat-chip">net <b>${_cf_hdr["net_cost_usd"]:+,.0f}</b></span>'
    if _cf_hdr else ""
)
_lid = layout_obj.get("layoutId", "")
_lid_chip = f'<span style="font-size:.7rem;color:#5a9090;margin-right:8px">{_lid}</span>' if _lid else ""
st.markdown(
    f'<div style="background:#071a1a;margin:-0.6rem -2rem 0.2rem;padding:5px 2rem;'
    f'display:flex;align-items:center;justify-content:space-between;'
    f'border-bottom:1px solid #1a4040;min-height:38px">'
    f'<div style="display:flex;align-items:center;gap:0">'
    f'{_logo_part}{_lid_chip}'
    f'<span class="stat-chip"><b>{n_cols}</b> col</span>'
    f'<span class="stat-chip"><b>{n_beams}</b> beam</span>'
    f'{_cost_chip}{_review}'
    f'</div></div>',
    unsafe_allow_html=True,
)

_, _hc_up, _hc2, _hc_tm, _hc4 = st.columns([0.8, 2.5, 1, 0.7, 1])
with _hc_up:
    _top_upload = st.file_uploader(
        "layout", type=["json"], label_visibility="collapsed", key="top_uploader"
    )
    if _top_upload is not None:
        try:
            _loaded = _normalize_layout(json.loads(_top_upload.getvalue().decode("utf-8")))
            _write_json(EDITED_LAYOUT_PATH, _loaded)
            for _k in ("eval_result", "eval_alts", "agent_log", "grid_options",
                       "selected_grid", "cost_flexibility", "last_comparison"):
                st.session_state[_k] = [] if _k in ("eval_alts", "agent_log", "grid_options") else None
            st.session_state.viewer_nonce += 1
            st.success(f"Loaded '{_loaded.get('layoutId', 'unnamed')}'")
            st.rerun()
        except Exception as _exc:
            st.error(f"Invalid JSON: {_exc}")
with _hc2:
    _can_undo = BEFORE_LAYOUT_PATH.exists()
    if st.button("↩ Undo", use_container_width=True, key="btn_undo",
                 disabled=not _can_undo, help="Restore layout to previous state"):
        _current = EDITED_LAYOUT_PATH.read_text(encoding="utf-8") if EDITED_LAYOUT_PATH.exists() else "{}"
        _before  = BEFORE_LAYOUT_PATH.read_text(encoding="utf-8")
        EDITED_LAYOUT_PATH.write_text(_before,  encoding="utf-8")
        BEFORE_LAYOUT_PATH.write_text(_current, encoding="utf-8")
        st.session_state.viewer_nonce    += 1
        st.session_state.eval_result      = None
        st.session_state.eval_alts        = []
        st.session_state.cost_flexibility = None
        st.session_state.last_comparison  = None
        st.rerun()
with _hc_tm:
    st.write("")  # vertical spacer to align
with _hc4:
    st.download_button(
        "Export",
        data=json.dumps(layout_obj, indent=2, ensure_ascii=False),
        file_name="layout_export.json",
        mime="application/json",
        use_container_width=True,
    )

# ── Three-column body ──────────────────────────────────────────────────────────
col_ctrl, col_plan, col_analysis = st.columns([1.2, 3.8, 1.5], gap="small")


# ══════════════════════════════════════════════════════════════════════════════
# LEFT — Controls
# ══════════════════════════════════════════════════════════════════════════════

with col_ctrl:

    # ── Agent chat ─────────────────────────────────────────────────────────────
    st.markdown('<div class="panel-hdr">Ask Agent</div>', unsafe_allow_html=True)

    # Scrollable chat thread
    _history = st.session_state.get("history", [])
    if _history:
        _bubbles = ""
        for _msg in _history[-6:]:
            _q = _msg.get("prompt", "")
            _a = _msg.get("response", "")
            if _q:
                _bubbles += f'<div class="chat-q">{_q[:120]}{"…" if len(_q)>120 else ""}</div>'
            if _a:
                _short = _a[:200] + ("…" if len(_a) > 200 else "")
                _bubbles += f'<div class="chat-a">{_short}</div>'
        st.markdown(
            f'<div style="max-height:200px;overflow-y:auto;margin-bottom:6px">{_bubbles}</div>',
            unsafe_allow_html=True,
        )

    with st.form("agent_form", clear_on_submit=True):
        prompt_input = st.text_area(
            "prompt",
            placeholder="Ask agent… e.g. evaluate, remove beam A1",
            label_visibility="collapsed",
            height=58,
        )
        submitted = st.form_submit_button("Ask Agent", use_container_width=True)

    if st.button("Reset to default", use_container_width=True, key="btn_reset"):
        if DEFAULT_LAYOUT_PATH.exists():
            _write_json(EDITED_LAYOUT_PATH, _read_json(DEFAULT_LAYOUT_PATH))
        elif EDITED_LAYOUT_PATH.exists():
            EDITED_LAYOUT_PATH.unlink()
        st.session_state.viewer_nonce += 1
        for k in ("eval_result", "eval_alts", "agent_log", "state_history",
                  "grid_options", "selected_grid", "output_log",
                  "cost_flexibility", "last_comparison"):
            st.session_state[k] = [] if isinstance(st.session_state.get(k), list) else None
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# CENTER — Dominant 2D Floor Plan
# ══════════════════════════════════════════════════════════════════════════════

with col_plan:

    # JS bridge: postMessage from SVG iframe → URL param → Streamlit rerun
    components.html("""
<script>
  (function() {
    if (window._selBridgeReady) return;
    window._selBridgeReady = true;
    window.parent.addEventListener('message', function(ev) {
      if (!ev.data || ev.data.type !== 'selectElement') return;
      var eid = ev.data.elementId || '';
      var url = new URL(window.parent.location.href);
      var prev = url.searchParams.get('_sel') || '';
      if (eid === prev) return;
      if (eid) { url.searchParams.set('_sel', eid); }
      else      { url.searchParams.delete('_sel'); }
      window.parent.history.replaceState(null, '', url.toString());
      window.parent.dispatchEvent(new PopStateEvent('popstate', {state: null}));
      setTimeout(function() {
        window.parent.dispatchEvent(new PopStateEvent('popstate', {state: null}));
      }, 40);
    });
  })();
</script>""", height=1)

    # ── Compact toolbar ────────────────────────────────────────────────────────
    _tv1, _tv2, _tv3, _tv4, _tv5 = st.columns([1.4, 1.4, 1.4, 1.4, 2], gap="small")
    with _tv1:
        _labels_on = st.toggle("IDs", value=st.session_state.labels_on,
                               key="labels_toggle", help="Show element IDs")
        if _labels_on != st.session_state.labels_on:
            st.session_state.labels_on = _labels_on
            st.session_state.viewer_nonce += 1
            st.rerun()
    with _tv2:
        _compare_on = st.toggle("Diff", value=st.session_state.compare_mode,
                                key="compare_toggle", help="Before/after 3D",
                                disabled=not BEFORE_LAYOUT_PATH.exists())
        if _compare_on != st.session_state.compare_mode:
            st.session_state.compare_mode = _compare_on
            st.session_state.viewer_nonce += 1
            st.rerun()
    with _tv3:
        _auto_eval = st.checkbox("Auto", value=st.session_state.get("auto_eval", True),
                                 key="chk_auto_eval", help="Auto-evaluate on change")
        if _auto_eval != st.session_state.get("auto_eval", True):
            st.session_state.auto_eval = _auto_eval
    with _tv4:
        _snap_n = len(st.session_state.get("snapshots", [])) + 1
        if st.button(f"Save #{_snap_n}", key="btn_snap", use_container_width=True,
                     help="Save snapshot"):
            st.session_state.snapshots.append({
                "label":            f"Change {_snap_n}",
                "layout_json":      json.dumps(layout_obj),
                "eval_result":      st.session_state.eval_result,
                "cost_flexibility": st.session_state.cost_flexibility,
                "before_json":      (BEFORE_LAYOUT_PATH.read_text(encoding="utf-8")
                                     if BEFORE_LAYOUT_PATH.exists() else json.dumps(layout_obj)),
            })
            st.rerun()

    _preview_opt_file = ""
    if st.session_state.grid_options:
        with _tv5:
            _opt_names = ["Working layout"] + [
                f"{o['label']} ({o.get('failures',0)} fail · ${o.get('cost',0):,.0f})"
                for o in st.session_state.grid_options
            ]
            _prev_sel = st.radio("Preview", _opt_names, horizontal=True,
                                 label_visibility="collapsed", key="preview_radio")
            if _prev_sel != "Working layout":
                _prev_idx = _opt_names.index(_prev_sel) - 1
                _preview_opt_file = f"team_01_option_{_prev_idx + 1}.json"

    # Snapshot pills
    _snaps = st.session_state.get("snapshots", [])
    if _snaps:
        _pills = " ".join(
            f'<span class="snap-pill{" snap-pill-active" if i == len(_snaps)-1 else ""}">'
            f'{s["label"]}</span>'
            for i, s in enumerate(_snaps)
        )
        st.markdown(_pills, unsafe_allow_html=True)

    # ── 2D Floor Plan — dominant, full-height ──────────────────────────────────
    _plan_layout = layout_obj
    if _preview_opt_file:
        _opt_path = REPO_ROOT / _preview_opt_file
        if _opt_path.exists():
            try:
                _plan_layout = _normalize_layout(
                    json.loads(_opt_path.read_text(encoding="utf-8"))
                )
            except Exception:
                pass
    components.html(
        _render_floor_plan_html(
            _plan_layout,
            eval_result=st.session_state.eval_result,
            highlight=st.session_state.selected_el,
            labels=st.session_state.labels_on,
            height_px=620,
            is_light=_is_light,
        ),
        height=622,
        scrolling=False,
    )

    # ── 3D View — collapsed expander below plan ────────────────────────────────
    with st.expander("3D Structural View", expanded=False):
        if _viewer_is_reachable():
            components.iframe(
                _viewer_url(
                    highlight=st.session_state.selected_el,
                    compare=st.session_state.compare_mode,
                    labels=st.session_state.labels_on,
                    option_file=_preview_opt_file,
                ),
                height=320, scrolling=False,
            )
        else:
            st.caption("3D viewer offline — run `python -m http.server 8000` from repo root.")


# ══════════════════════════════════════════════════════════════════════════════
# RIGHT — Element Detail + Evaluation + Cost
# ══════════════════════════════════════════════════════════════════════════════

with col_analysis:

    # Agent form is in left panel; wire submitted / prompt_input here
    if submitted and prompt_input.strip():
        with st.spinner("Agent reasoning…"):
            response = _run_agent_chat(
                prompt_input.strip(), layout_obj, st.session_state.eval_result,
            )

        if response == "GENERATE_GRID":
            with st.spinner("Generating structural grid options…"):
                st.session_state.grid_options = _run_grid_options(layout_obj, st.session_state.material)
            for _i, _opt in enumerate(st.session_state.grid_options, 1):
                _op = REPO_ROOT / f"team_01_option_{_i}.json"
                _op.write_text(json.dumps(_opt["layout"], indent=2, ensure_ascii=False), encoding="utf-8")
            response = (
                f"Generated {len(st.session_state.grid_options)} structural grid option(s). "
                "Review the Grid Options in the left panel."
            )
        elif response == "EVALUATE":
            from nodes.modify import apply_material_override
            _mat_now = st.session_state.get("material", "RCC")
            _sdl_now = st.session_state.get("sdl_kNm2", 3.5)
            _ll_now  = st.session_state.get("live_load_kNm2", 2.0)
            _ls      = apply_material_override(json.dumps(layout_obj), _mat_now)
            BEFORE_LAYOUT_PATH.write_text(json.dumps(layout_obj), encoding="utf-8")
            _write_json(EDITED_LAYOUT_PATH, json.loads(_ls))
            st.session_state.viewer_nonce += 1
            with st.spinner("Evaluating structure…"):
                _ev = _run_evaluate(_ls, sdl=_sdl_now, ll=_ll_now)
            if _ev:
                st.session_state.eval_result = _ev
                st.session_state.eval_alts   = _get_failure_alternatives(_ev, _mat_now)
            _s = (_ev or {}).get("summary", {})
            response = (
                f"Evaluation: **{'PASS' if _s.get('overall_PASS') else 'FAIL'}** — "
                f"{_s.get('beam_failures', 0)} beam failure(s), "
                f"{_s.get('column_failures', 0)} column failure(s)."
            )

        st.session_state.output_log.append(response)
        st.session_state.history.append({"prompt": prompt_input, "response": response})
        label = prompt_input[:28] + ("…" if len(prompt_input) > 28 else "")
        st.session_state.state_history.append({
            "label":       label,
            "layout_json": _load_working_layout(),
            "eval_result": st.session_state.eval_result,
        })
        st.rerun()

    _mat_now = st.session_state.material
    _sdl_now = st.session_state.sdl_kNm2
    _ll_now  = st.session_state.live_load_kNm2
    er       = st.session_state.eval_result

    # ── Selected element detail (SENSI-style) ──────────────────────────────────
    _sel = st.session_state.selected_el
    _structure_r = layout_obj.get("structure", [])
    _sel_obj = next((e for e in _structure_r if e["id"] == _sel), None) if _sel else None

    if _sel_obj:
        st.markdown(
            _el_detail_html(_sel_obj, er),
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div style="font-size:.7rem;color:#3a7070;padding:6px 0 4px">'
            'Click an element in the plan to inspect it</div>',
            unsafe_allow_html=True,
        )

    # ── Material & Loads ───────────────────────────────────────────────────────
    with st.expander("Material & Loads", expanded=False):
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
            st.session_state.material    = mat_choice
            st.session_state.grid_options = []
            st.rerun()

        sdl_options = {1.5: "Timber 1.5", 2.5: "Light 2.5", 3.5: "Standard 3.5", 5.0: "Heavy 5.0"}
        sdl_val = st.select_slider(
            "SDL kN/m²", options=list(sdl_options.keys()),
            value=st.session_state.sdl_kNm2,
            format_func=lambda v: f"{sdl_options[v]}",
        )
        if sdl_val != st.session_state.sdl_kNm2:
            st.session_state.sdl_kNm2 = sdl_val

        ll_options = {2.0: "Residential", 3.0: "Office", 5.0: "Retail/Public"}
        ll_val = st.select_slider(
            "LL kN/m²", options=list(ll_options.keys()),
            value=st.session_state.live_load_kNm2,
            format_func=lambda v: f"{ll_options[v]}",
        )
        if ll_val != st.session_state.live_load_kNm2:
            st.session_state.live_load_kNm2 = ll_val

    # ── Structural Grid ────────────────────────────────────────────────────────
    with st.expander("Structural Grid", expanded=False):
        _cg, _cr = st.columns(2)
        with _cg:
            gen_clicked = st.button("Generate", use_container_width=True, key="btn_gen")
        with _cr:
            rec_clicked = st.button("↺ Refresh", use_container_width=True, key="btn_rec")

        if gen_clicked or rec_clicked:
            with st.spinner("Computing grid options…"):
                st.session_state.grid_options = _run_grid_options(layout_obj, st.session_state.material)
            for _i, _opt in enumerate(st.session_state.grid_options, 1):
                _op = REPO_ROOT / f"team_01_option_{_i}.json"
                _op.write_text(json.dumps(_opt["layout"], indent=2, ensure_ascii=False), encoding="utf-8")
            st.rerun()

        for opt in st.session_state.grid_options:
            _gl     = opt["label"]
            _gs     = opt["spacing"]
            _gf     = opt.get("failures", 0)
            _gc     = opt.get("cost", 0)
            _active = st.session_state.selected_grid == _gl
            _fcls   = "fail-ct" if _gf > 0 else "pass-ct"
            _ccls   = "grid-card grid-card-active" if _active else "grid-card"
            st.markdown(
                f'<div class="{_ccls}">'
                f'<span class="grid-label">{_gl}</span>'
                f'<span class="grid-spacing" style="margin-left:6px">{_gs}m</span>'
                f'<div class="grid-stats">'
                f'<span class="{_fcls}">{_gf} fail</span>'
                f' &bull; ${_gc:,.0f}'
                f'</div></div>',
                unsafe_allow_html=True,
            )
            if st.button(f"Apply {_gl}", key=f"grid_{_gl}", use_container_width=True):
                _opt_layout = opt.get("layout", {})
                _bstr = EDITED_LAYOUT_PATH.read_text(encoding="utf-8") if EDITED_LAYOUT_PATH.exists() else json.dumps(layout_obj)
                BEFORE_LAYOUT_PATH.write_text(_bstr, encoding="utf-8")
                _write_json(EDITED_LAYOUT_PATH, _opt_layout)
                st.session_state.selected_grid    = _gl
                st.session_state.viewer_nonce    += 1
                st.session_state.eval_result      = opt.get("evaluation")
                st.session_state.eval_alts        = _get_failure_alternatives(
                    opt.get("evaluation") or {}, st.session_state.material
                )
                st.session_state.cost_flexibility = None
                st.session_state.last_comparison  = None
                st.rerun()

    # ── Evaluation summary ─────────────────────────────────────────────────────
    st.markdown('<div class="panel-hdr">Evaluation</div>', unsafe_allow_html=True)

    if st.button("▶ Run Evaluation", use_container_width=True, key="btn_eval"):
        from nodes.modify import apply_material_override
        layout_str     = json.dumps(layout_obj)
        layout_str_mat = apply_material_override(layout_str, _mat_now)
        BEFORE_LAYOUT_PATH.write_text(layout_str, encoding="utf-8")
        _write_json(EDITED_LAYOUT_PATH, json.loads(layout_str_mat))
        st.session_state.viewer_nonce += 1
        with st.spinner("Evaluating…"):
            ev = _run_evaluate(layout_str_mat, sdl=_sdl_now, ll=_ll_now)
        if ev:
            st.session_state.eval_result = ev
            st.session_state.eval_alts   = _get_failure_alternatives(ev, _mat_now)
        st.rerun()

    if er is None:
        st.caption("Run evaluation or apply a grid.")
    else:
        _sm   = er.get("summary", {})
        _bf   = _sm.get("beam_failures", 0)
        _cf_c = _sm.get("column_failures", 0)
        _ok   = _sm.get("overall_PASS", False)
        _tot  = max(len(er.get("beams", [])) + len(er.get("columns", [])), 1)
        _score = round(1 - (_bf + _cf_c) / _tot, 2)

        _cls  = "eval-pass" if _ok else "eval-fail"
        _txt  = "PASS" if _ok else "FAIL"
        _sc_c = "eval-pass" if _score >= 0.9 else ("eval-fail" if _score < 0.7 else "")
        st.markdown(
            f'<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:4px">'
            f'<span class="{_cls}" style="font-size:1.4rem;font-weight:800">{_txt}</span>'
            f'<span class="{_sc_c}" style="font-size:1.1rem;font-weight:700">{_score:.2f}</span>'
            f'</div>'
            f'<div style="font-size:.68rem;color:#5a9090">'
            f'{_bf} beam fail · {_cf_c} col fail · {_mat_now}</div>',
            unsafe_allow_html=True,
        )

        # Failing items (compact)
        _fbeams = [b for b in er.get("beams", [])
                   if not b.get("bend_PASS") or not b.get("shear_PASS")
                   or not b.get("defl_TL_PASS") or not b.get("defl_LL_PASS")]
        _fcols  = [c for c in er.get("columns", [])
                   if not c.get("stress_PASS") or not c.get("buckling_PASS")]

        if not _fbeams and not _fcols:
            st.markdown('<span class="pass-badge">All checks passed ✓</span>',
                        unsafe_allow_html=True)
        else:
            _items_html = ""
            for b in _fbeams[:4]:
                _chks = [k for k, f in [("bend", not b.get("bend_PASS")),
                                         ("shear", not b.get("shear_PASS")),
                                         ("defl", not b.get("defl_TL_PASS") or not b.get("defl_LL_PASS"))] if f]
                _items_html += (
                    f'<div class="crit-item" style="cursor:pointer" '
                    f'onclick="window.parent.postMessage({{type:\'selectElement\',elementId:\'{b["id"]}\'}},\'*\')">'
                    f'<b>{b["id"]}</b> {b.get("span_m",0):.1f}m'
                    f'<span style="float:right;color:#ff6060">{", ".join(_chks)}</span></div>'
                )
            for c in _fcols[:3]:
                _chks = [k for k, f in [("stress", not c.get("stress_PASS")),
                                         ("buck", not c.get("buckling_PASS"))] if f]
                _items_html += (
                    f'<div class="crit-item" style="cursor:pointer" '
                    f'onclick="window.parent.postMessage({{type:\'selectElement\',elementId:\'{c["id"]}\'}},\'*\')">'
                    f'<b>{c["id"]}</b> {c.get("section_mm","?")}'
                    f'<span style="float:right;color:#ff6060">{", ".join(_chks)}</span></div>'
                )
            st.markdown(_items_html, unsafe_allow_html=True)

        # Suggested fixes
        alts = st.session_state.eval_alts
        if alts:
            st.markdown('<div class="panel-hdr" style="margin-top:6px">Fixes</div>',
                        unsafe_allow_html=True)
            for i, alt in enumerate(alts[:4]):
                if st.button(alt[:52] + ("…" if len(alt) > 52 else ""),
                             key=f"alt_{i}", use_container_width=True):
                    before_str = json.dumps(layout_obj)
                    BEFORE_LAYOUT_PATH.write_text(before_str, encoding="utf-8")
                    with st.spinner(f"Applying…"):
                        new_str, new_ev = _apply_alternative(alt, before_str, _mat_now, _sdl_now, _ll_now)
                    if new_str != before_str:
                        _write_json(EDITED_LAYOUT_PATH, json.loads(new_str))
                        st.session_state.viewer_nonce    += 1
                        st.session_state.cost_flexibility = None
                        st.session_state.state_history.append({
                            "label":       alt[:30], "layout_json": json.loads(new_str),
                            "eval_result": new_ev,
                        })
                        with st.spinner("Summarising…"):
                            _cf_res  = _run_cost_flex(before_str, new_str)
                            _cmp_txt = _run_comparison(before_str, new_str)
                        if _cf_res:
                            st.session_state.cost_flexibility = _cf_res
                        if _cmp_txt:
                            st.session_state.output_log.append(_cmp_txt)
                            st.session_state.last_comparison = _cmp_txt
                    if new_ev is not None:
                        st.session_state.eval_result = new_ev
                        st.session_state.eval_alts   = _get_failure_alternatives(new_ev, _mat_now)
                    st.rerun()

    # ── Cost & Change ──────────────────────────────────────────────────────────
    _cf       = st.session_state.get("cost_flexibility")
    _last_cmp = st.session_state.get("last_comparison")

    if _cf is not None:
        st.markdown('<div class="panel-hdr">Cost & Change</div>', unsafe_allow_html=True)
        _net  = _cf.get("net_cost_usd", 0)
        _flex = _cf.get("flexibility_score", 0)
        _dis  = _cf.get("disruption_score", 0)
        _r1, _r2, _r3 = st.columns(3)
        _r1.metric("Net", f"${_net:+,.0f}")
        _r2.metric("Flex", f"{_flex:.1f}/10")
        _r3.metric("Disrupt", f"{_dis}/10")
        if _last_cmp:
            st.markdown(
                f'<div class="agent-response" style="margin-top:6px">'
                f'{_last_cmp[:400]}{"…" if len(_last_cmp) > 400 else ""}</div>',
                unsafe_allow_html=True,
            )
    elif er is not None:
        if st.button("Analyse cost & flexibility", use_container_width=True, key="btn_cf"):
            _bs = (BEFORE_LAYOUT_PATH.read_text(encoding="utf-8")
                   if BEFORE_LAYOUT_PATH.exists() else json.dumps(layout_obj))
            with st.spinner("Analysing…"):
                _cf_res = _run_cost_flex(_bs, json.dumps(layout_obj))
            if _cf_res:
                st.session_state.cost_flexibility = _cf_res
            st.rerun()

    # ── History & log (collapsed) ──────────────────────────────────────────────
    _snaps_cost = st.session_state.get("snapshots", [])
    if _snaps_cost:
        with st.expander(f"Snapshots ({len(_snaps_cost)})", expanded=False):
            for _sn in _snaps_cost:
                _scf  = _sn.get("cost_flexibility")
                _sev  = (_sn.get("eval_result") or {}).get("summary", {})
                _fail = _sev.get("beam_failures", 0) + _sev.get("column_failures", 0)
                with st.expander(f"{_sn['label']} · {'✓' if _fail == 0 else f'✗ {_fail}'}", expanded=False):
                    if _scf:
                        _sc1, _sc2 = st.columns(2)
                        _sc1.metric("Net", f"${_scf.get('net_cost_usd', 0):+,.0f}")
                        _sc2.metric("Flex", f"{_scf.get('flexibility_score', 0):.1f}/10")
                    else:
                        st.caption("No cost data saved.")

    with st.expander("State History", expanded=False):
        if not st.session_state.state_history:
            st.caption("No states recorded.")
        else:
            for i, snap in enumerate(reversed(st.session_state.state_history[-8:])):
                real_i = len(st.session_state.state_history) - 1 - i
                st.markdown(
                    f'<span class="state-pill">{real_i + 1}. {snap["label"]}</span>',
                    unsafe_allow_html=True,
                )
                if st.button(f"Restore #{real_i + 1}", key=f"restore_{real_i}"):
                    _write_json(EDITED_LAYOUT_PATH, snap["layout_json"])
                    st.session_state.viewer_nonce += 1
                    st.session_state.eval_result   = snap.get("eval_result")
                    st.session_state.eval_alts     = _get_failure_alternatives(
                        snap.get("eval_result") or {}, st.session_state.material)
                    st.session_state.grid_options  = []
                    st.rerun()

    with st.expander("Output Log", expanded=False):
        for msg in reversed(st.session_state.output_log[-8:]):
            st.markdown(
                f'<div class="log-entry">{msg[:280]}{"…" if len(msg) > 280 else ""}</div>',
                unsafe_allow_html=True,
            )
