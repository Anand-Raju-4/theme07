# ui/upload_page.py

import json
from pathlib import Path
import streamlit as st
import requests
import pandas as pd

STARTER_KIT_DIR = Path("starter_kit/schemas")


def render_upload_page():

    st.header("📤 Upload Schema Versions")

    st.markdown(
        "Upload the **before** and **after** source schema JSON files, or use the pre-packaged sample dataset."
    )

    # ── Quick Demo Button ────────────────────────────────────
    col_demo, _ = st.columns([2, 3])
    with col_demo:
        if st.button("⚡ Quick Load Starter Kit (10 Changes Sample Data)", type="secondary"):
            try:
                before_path = STARTER_KIT_DIR / "sources_before.json"
                after_path = STARTER_KIT_DIR / "sources_after.json"
                seeds_path = STARTER_KIT_DIR / "seeded_changes.json"

                if before_path.exists() and after_path.exists():
                    st.session_state["before_schema"] = json.loads(before_path.read_text(encoding="utf-8"))
                    st.session_state["after_schema"] = json.loads(after_path.read_text(encoding="utf-8"))
                    st.session_state["seeded_changes"] = json.loads(seeds_path.read_text(encoding="utf-8")) if seeds_path.exists() else None
                    st.session_state["dataset_name"] = "Starter Kit (Contoso Lakehouse)"
                    st.success("✅ Loaded Starter Kit Schemas & Seeded Changes (SC01-SC10)!")
                else:
                    st.error("Starter kit schema files not found on disk.")
            except Exception as e:
                st.error(f"Failed to load starter kit: {e}")

    st.divider()

    # ── File Uploaders ───────────────────────────────────────
    col_before, col_after = st.columns(2)

    with col_before:
        before_file = st.file_uploader(
            "Source Schema — Before Change (JSON)",
            type="json",
            key="upload_before",
        )

    with col_after:
        after_file = st.file_uploader(
            "Source Schema — After Change (JSON)",
            type="json",
            key="upload_after",
        )

    seeds_file = st.file_uploader(
        "Seeded Changes Metadata (Optional - associates change IDs like SC01-SC10)",
        type="json",
        key="upload_seeds",
    )

    if before_file and after_file:
        try:
            st.session_state["before_schema"] = json.load(before_file)
            st.session_state["after_schema"] = json.load(after_file)
            st.session_state["dataset_name"] = "Custom Upload"
        except json.JSONDecodeError as exc:
            st.error(f"Invalid JSON in schema files: {exc}")
            return

        if seeds_file:
            try:
                st.session_state["seeded_changes"] = json.load(seeds_file)
            except json.JSONDecodeError as exc:
                st.error(f"Invalid seeded changes JSON: {exc}")
                return
        else:
            # Check if default starter kit seeds match
            default_seeds = STARTER_KIT_DIR / "seeded_changes.json"
            if default_seeds.exists() and "seeded_changes" not in st.session_state:
                try:
                    st.session_state["seeded_changes"] = json.loads(default_seeds.read_text(encoding="utf-8"))
                except Exception:
                    pass

    # ── Preview & Instant Diff ───────────────────────────────
    if "before_schema" in st.session_state and "after_schema" in st.session_state:

        before_schema = st.session_state["before_schema"]
        after_schema = st.session_state["after_schema"]
        seeded_changes = st.session_state.get("seeded_changes")

        st.info(f"📁 Active Dataset: **{st.session_state.get('dataset_name', 'Loaded Schemas')}**")

        # Preview JSON in tabs
        tab_before, tab_after, tab_seeds = st.tabs(["📄 Before Schema", "📄 After Schema", "🏷️ Seeded Changes"])
        with tab_before:
            st.json(before_schema)
        with tab_after:
            st.json(after_schema)
        with tab_seeds:
            if seeded_changes:
                st.json(seeded_changes)
            else:
                st.info("No seed file loaded. Change IDs will be auto-assigned (e.g. CHG-01, CHG-02).")

        # Run schema diff via API
        api_base = st.session_state.get("api_base", "http://localhost:8000")

        with st.spinner("Detecting schema diff via API..."):
            try:
                payload = {
                    "before": before_schema,
                    "after": after_schema,
                    "seeded_changes": seeded_changes,
                }
                resp = requests.post(
                    f"{api_base}/api/schema-diff",
                    json=payload,
                    timeout=30,
                )

                if resp.status_code == 200:
                    diff_result = resp.json()
                    st.session_state["schema_diff"] = diff_result

                    st.divider()
                    st.subheader(
                        f"🔍 Detected {diff_result['total_changes']} Schema Changes"
                    )

                    if diff_result["changes"]:
                        df = pd.DataFrame(diff_result["changes"])
                        st.dataframe(df, use_container_width=True)
                        st.success("👉 Go to **🔬 Run Analysis** in the sidebar to trace downstream impacts!")
                    else:
                        st.info("No schema differences detected between before and after.")
                else:
                    st.error(f"API error ({resp.status_code}): {resp.text}")

            except requests.ConnectionError:
                st.error("Cannot reach the FastAPI backend at " + api_base + ". Make sure 'python run.py' is running.")
            except Exception as exc:
                st.error(f"Unexpected error: {exc}")
