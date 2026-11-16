import streamlit as st

from ui.upload_page import render_upload_page
from ui.analysis_page import render_analysis_page
from ui.report_page import render_report_page

API_BASE = "http://localhost:8000"

st.set_page_config(
    page_title="Schema Drift Impact Analyzer",
    page_icon="📊",
    layout="wide"
)

st.title("📊 Schema Drift Impact Analyzer")

# Store API base URL in session state for all pages
if "api_base" not in st.session_state:
    st.session_state["api_base"] = API_BASE

# Sidebar
st.sidebar.markdown("### ⚙️ API Backend")
api_url = st.sidebar.text_input(
    "FastAPI URL",
    value=st.session_state["api_base"],
    help="The FastAPI backend must be running.",
)
st.session_state["api_base"] = api_url

# Health check indicator
try:
    import requests
    resp = requests.get(f"{api_url}/api/health", timeout=3)
    if resp.status_code == 200:
        st.sidebar.success("✅ Backend connected")
    else:
        st.sidebar.error("❌ Backend returned an error")
except Exception:
    st.sidebar.error("❌ Backend unreachable — start the API first")

st.sidebar.divider()

menu = st.sidebar.radio(
    "Navigation",
    [
        "📤 Upload Schemas",
        "🔬 Run Analysis",
        "📋 Reports"
    ]
)

if menu == "📤 Upload Schemas":
    render_upload_page()

elif menu == "🔬 Run Analysis":
    render_analysis_page()

elif menu == "📋 Reports":
    render_report_page()
