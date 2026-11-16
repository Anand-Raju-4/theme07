import streamlit as st

from ui.upload_page import render_upload_page
from ui.analysis_page import render_analysis_page
from ui.report_page import render_report_page

st.set_page_config(
    page_title="Schema Drift Impact Analyzer",
    page_icon="📊",
    layout="wide"
)

st.title("Schema Drift Impact Analyzer")

menu = st.sidebar.radio(
    "Navigation",
    [
        "Upload Schemas",
        "Run Analysis",
        "Reports"
    ]
)

if menu == "Upload Schemas":
    render_upload_page()

elif menu == "Run Analysis":
    render_analysis_page()

elif menu == "Reports":
    render_report_page()