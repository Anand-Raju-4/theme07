# ui/analysis_page.py

import streamlit as st

from src.analysis.analyzer import run_analysis

def render_analysis_page():

    st.header("Impact Analysis")

    if "before_schema" not in st.session_state:
        st.warning("Upload schemas first")
        return

    if st.button("Run Analysis"):

        result = run_analysis(
            st.session_state["before_schema"],
            st.session_state["after_schema"]
        )

        st.session_state["result"] = result

        st.success("Analysis Complete")

        st.dataframe(result["schema_changes"])