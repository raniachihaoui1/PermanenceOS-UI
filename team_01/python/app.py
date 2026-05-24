from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from nodes.structural_grid import build_structural_grid_with_options


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LAYOUT_PATH = REPO_ROOT / "layout_input" / "layout_schema.json"
EDITED_LAYOUT_PATH = REPO_ROOT / "team_01_edited_layout.json"
VIEWER_BASE_URL = "http://127.0.0.1:8000/layout_viewer.html"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _normalize_layout(payload: object) -> dict:
    if isinstance(payload, dict):
        if isinstance(payload.get("layout"), dict):
            return payload["layout"]
        return payload

    if isinstance(payload, list):
        if not payload:
            raise ValueError("Uploaded JSON list is empty")
        first = payload[0]
        if isinstance(first, dict):
            if isinstance(first.get("layout"), dict):
                return first["layout"]
            return first
        raise ValueError("First list item must be a layout object")

    raise ValueError("Layout JSON must be an object or a non-empty list of objects")


def _load_working_layout() -> dict:
    if EDITED_LAYOUT_PATH.exists():
        return _normalize_layout(_read_json(EDITED_LAYOUT_PATH))
    return _normalize_layout(_read_json(DEFAULT_LAYOUT_PATH))


def _viewer_is_reachable() -> bool:
    try:
        with urllib.request.urlopen(VIEWER_BASE_URL, timeout=0.8) as response:
            return response.status == 200
    except Exception:
        return False


def _ensure_session() -> None:
    if "viewer_nonce" not in st.session_state:
        st.session_state.viewer_nonce = 0
    if "history" not in st.session_state:
        st.session_state.history = []


st.set_page_config(page_title="PermanenceOS | Three.js + Grid", layout="wide")
_ensure_session()

st.title("PermanenceOS")
st.caption("Upload a layout, visualize it in Three.js, then run create-grid and refresh automatically.")

with st.sidebar:
    st.header("Layout")
    uploaded = st.file_uploader("Upload layout JSON", type=["json"])
    selected_material = st.selectbox("Grid material", options=["RCC", "STEEL", "TIMBER"], index=0)

    if uploaded is not None:
        try:
            payload = json.loads(uploaded.getvalue().decode("utf-8"))
            layout = _normalize_layout(payload)
            _write_json(EDITED_LAYOUT_PATH, layout)
            st.session_state.viewer_nonce += 1
            st.success(
                f"Loaded layout '{layout.get('layoutId', 'unnamed')}' into {EDITED_LAYOUT_PATH.name}"
            )
        except Exception as exc:
            st.error(f"Invalid JSON: {exc}")

    if st.button("Reset to default layout"):
        _write_json(EDITED_LAYOUT_PATH, _read_json(DEFAULT_LAYOUT_PATH))
        st.session_state.viewer_nonce += 1
        st.success("Reset complete")

    st.divider()
    st.subheader("Prompt History")
    if st.session_state.history:
        for idx, item in enumerate(st.session_state.history, start=1):
            st.write(f"{idx}. {item['prompt']}")
    else:
        st.caption("No prompts yet")

left_col, right_col = st.columns([3, 2])

with left_col:
    st.subheader("Three.js View")
    if _viewer_is_reachable():
        viewer_url = f"{VIEWER_BASE_URL}?v={st.session_state.viewer_nonce}"
        components.iframe(viewer_url, height=760, scrolling=False)
    else:
        st.warning("Three.js viewer server is not running. Start: python -m http.server 8000")
        st.write(VIEWER_BASE_URL)

    layout_obj = _load_working_layout()
    rooms_count = len(layout_obj.get("rooms", []))
    structure_count = len(layout_obj.get("structure", []))
    m1, m2 = st.columns(2)
    m1.metric("Rooms", rooms_count)
    m2.metric("Structure", structure_count)

with right_col:
    st.subheader("Agent")
    st.write("For now this app supports one action: create a grid.")

    prompt = st.chat_input("Try: create a grid")
    if prompt:
        normalized = prompt.strip().lower()

        if "create" in normalized and "grid" in normalized:
            working_layout = _load_working_layout()
            bundle = build_structural_grid_with_options(
                working_layout,
                prompt,
                material=selected_material,
            )
            updated_layout = bundle["recommended"]["layout"]
            _write_json(EDITED_LAYOUT_PATH, updated_layout)
            st.session_state.viewer_nonce += 1

            response = (
                f"Created and tagged a structural grid using {selected_material}. "
                f"Applied {bundle['recommended']['label']} at spacing {bundle['recommended']['spacing']}m. "
                "The Three.js viewport has been refreshed with the updated JSON."
            )
            st.success(response)
            st.session_state.history.append({"prompt": prompt, "response": response})
        else:
            response = (
                "I can run create-grid right now. "
                "Please ask: create a grid"
            )
            st.info(response)
            st.session_state.history.append({"prompt": prompt, "response": response})

        st.write("Latest response")
        st.write(st.session_state.history[-1]["response"])