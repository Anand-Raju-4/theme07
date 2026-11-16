# ui/upload_page.py

import streamlit as st
import json

def render_upload_page():

    st.header("Upload Schema Versions")

    before_file = st.file_uploader(
        "Source Schema Before Change",
        type="json"
    )

    after_file = st.file_uploader(
        "Source Schema After Change",
        type="json"
    )

    if before_file and after_file:

        before_schema = json.load(before_file)
        after_schema = json.load(after_file)

        st.session_state["before_schema"] = before_schema
        st.session_state["after_schema"] = after_schema

        st.success("Schemas Uploaded Successfully")

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Before")
            st.json(before_schema)

        with col2:
            st.subheader("After")
            st.json(after_schema)