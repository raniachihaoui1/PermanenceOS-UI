from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from _runtime.bootstrap import bootstrap
from graph import run_agent


TEAM_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[2]
EDITED_LAYOUT_PATH = TEAM_DIR / f"{TEAM_DIR.name}_edited_layout.json"
DEFAULT_LAYOUT_PATH = REPO_ROOT / "layout_input" / "layout_schema.json"


def _read_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def _ensure_session_state() -> None:
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []


def _load_current_layout() -> dict | list | None:
    if EDITED_LAYOUT_PATH.exists():
        try:
            return _read_json(EDITED_LAYOUT_PATH)
        except Exception:
            return None
    if DEFAULT_LAYOUT_PATH.exists():
        try:
            return _read_json(DEFAULT_LAYOUT_PATH)
        except Exception:
            return None
    return None


def _run_agent_once(prompt: str) -> str:
    ctx = bootstrap()
    try:
        return run_agent(prompt, ctx)
    finally:
        ctx.mcp_client.close()


st.set_page_config(page_title="PermanenceOS Agent GUI", layout="wide", initial_sidebar_state="expanded")
_ensure_session_state()

st.title("PermanenceOS Agent GUI")
st.caption("Interactive UI for team_01 CLI agent")

with st.sidebar:
    st.header("Controls")

    uploaded_file = st.file_uploader("Upload starting layout JSON", type=["json"])
    if uploaded_file is not None:
        try:
            uploaded_layout = json.loads(uploaded_file.getvalue().decode("utf-8"))
            EDITED_LAYOUT_PATH.write_text(json.dumps(uploaded_layout, indent=2), encoding="utf-8")
            st.success(f"Loaded layout into {EDITED_LAYOUT_PATH.name}")
        except Exception as exc:
            st.error(f"Invalid JSON upload: {exc}")

    if st.button("Reset to repo layout_schema.json"):
        if DEFAULT_LAYOUT_PATH.exists():
            base_layout = _read_json(DEFAULT_LAYOUT_PATH)
            EDITED_LAYOUT_PATH.write_text(json.dumps(base_layout, indent=2), encoding="utf-8")
            st.success("Reset complete")
        else:
            st.error("layout_input/layout_schema.json not found")

    st.divider()
    st.subheader("Prompt History")
    if st.session_state.chat_history:
        for idx, item in enumerate(st.session_state.chat_history, start=1):
            st.write(f"{idx}. {item['user']}")
    else:
        st.caption("No prompts yet")

left_col, right_col = st.columns([1, 1])

with left_col:
    st.subheader("Current Layout Snapshot")
    layout_obj = _load_current_layout()
    if layout_obj is None:
        st.warning("No readable layout file found.")
    else:
        st.json(layout_obj)

        if isinstance(layout_obj, dict):
            rooms_count = len(layout_obj.get("rooms", []))
            windows_count = len(layout_obj.get("windows", []))
            structure_count = len(layout_obj.get("structure", []))
        else:
            rooms_count = 0
            windows_count = 0
            structure_count = 0

        m1, m2, m3 = st.columns(3)
        m1.metric("Rooms", rooms_count)
        m2.metric("Windows", windows_count)
        m3.metric("Structure", structure_count)

with right_col:
    st.subheader("Agent")

    for msg in st.session_state.chat_history:
        with st.chat_message("user"):
            st.write(msg["user"])
        with st.chat_message("assistant"):
            st.write(msg["assistant"])

    user_prompt = st.chat_input("Enter instruction (e.g. add a window to Bedroom 1)")
    if user_prompt:
        with st.chat_message("user"):
            st.write(user_prompt)

        with st.chat_message("assistant"):
            with st.spinner("Running LangGraph + MCP..."):
                try:
                    answer = _run_agent_once(user_prompt)
                    st.write(answer)
                except Exception as exc:
                    answer = f"Error: {exc}"
                    st.error(answer)

        st.session_state.chat_history.append({"user": user_prompt, "assistant": answer})

st.divider()
st.subheader("Download")
if EDITED_LAYOUT_PATH.exists():
    st.download_button(
        label=f"Download {EDITED_LAYOUT_PATH.name}",
        data=EDITED_LAYOUT_PATH.read_text(encoding="utf-8"),
        file_name=EDITED_LAYOUT_PATH.name,
        mime="application/json",
    )
else:
    st.caption("No edited layout generated yet")