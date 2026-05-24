import streamlit as st
import json
import time

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="PermanenceOS | Agent Interface",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CUSTOM STYLES (For that clean, architectural look) ---
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; border: 1px solid #eeeeee; }
    .pass-bg { background-color: #d4edda; color: #155724; padding: 10px; border-radius: 5px; text-align: center; font-weight: bold; }
    .fail-bg { background-color: #f8d7da; color: #721c24; padding: 10px; border-radius: 5px; text-align: center; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# --- SIDEBAR: CONTROLS & UPLOAD ---
with st.sidebar:
    st.title("PermanenceOS")
    st.write("---")
    uploaded_file = st.file_uploader("Upload Layout JSON", type=['json'])
    
    st.subheader("Prompt History")
    st.info("1. Original Layout\n2. Remove Columns\n3. Update Beam Width")

# --- MAIN LAYOUT ---
col_geom, col_reason = st.columns([2, 1])

with col_geom:
    st.subheader("Geometric Viewport")
    # Placeholder for your grid visualization (e.g., Plotly, Pydeck, or Matplotlib)
    st.image("https://via.placeholder.com/800x500.png?text=3D+Grid+Viewport+Placeholder", use_container_width=True)
    
    # --- METRIC DASHBOARD ---
    st.write("### Metric Dashboard")
    m1, m2, m3 = st.columns(3)
    
    with m1:
        # Example of the "PASS" logic from your sketches
        st.markdown('<div class="pass-bg">STRUCTURAL CHECK: PASS</div>', unsafe_allow_html=True)
        st.caption("Load Factor: 1.15")
    
    with m2:
        st.metric("Cycle Count", "4", help="Current Agent Iteration")
        
    with m3:
        st.metric("Estimated Cost", "$12,400", delta="+2.5%")

with col_reason:
    st.subheader("Agent Reasoning")
    
    # Container for the log (matching your "Agent Log > Cycle 4" sketch)
    with st.container(border=True):
        st.markdown("**Agent Log > Cycle 4**")
        st.code("""
> Task: Verify load after beam update.
> Result: Pass. Beam width validated.
> Next: Check secondary structural support.
        """, language="markdown")

    # User Input Area
    user_prompt = st.chat_input("Ask PermanenceOS Agent...")
    if user_prompt:
        st.write(f"**User:** {user_prompt}")
        with st.spinner("Agent is reasoning through LangGraph..."):
            time.sleep(1) # Simulate processing
            st.success("Modification Complete.")

# --- FOOTER: STATE HISTORY ---
st.write("---")
st.subheader("State History")
st.write("Original ➔ Columns Removed ➔ **Beam Updated**")