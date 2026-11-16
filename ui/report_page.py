# ui/report_page.py

import streamlit as st

def render_report_page():

    st.header("Generated Reports")

    if "result" not in st.session_state:
        st.warning("Run analysis first")
        return

    result = st.session_state["result"]

    st.json(result)

    with open(
        "outputs/impact_analysis.json",
        "rb"
    ) as file:

        st.download_button(
            "Download Impact Report",
            file,
            "impact_analysis.json"
        )