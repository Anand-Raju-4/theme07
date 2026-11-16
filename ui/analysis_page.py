# ui/analysis_page.py

import streamlit as st
import requests
import pandas as pd


def render_analysis_page():

    st.header("🔬 Full Impact Analysis")

    if "before_schema" not in st.session_state:
        st.warning("⬅️ Upload schemas first from the Upload page.")
        return

    st.markdown(
        "This runs the **complete pipeline**: "
        "Schema Diff → Lineage → Impact → Severity → Decision"
    )

    api_base = st.session_state.get("api_base", "http://localhost:8000")

    if st.button("🚀 Run Full Analysis", type="primary"):

        with st.spinner("Running full impact analysis pipeline..."):
            try:
                payload = {
                    "before": st.session_state["before_schema"],
                    "after": st.session_state["after_schema"],
                    "seeded_changes": st.session_state.get("seeded_changes"),
                    "project_root": "starter_kit/project",
                }

                resp = requests.post(
                    f"{api_base}/api/analyze",
                    json=payload,
                    timeout=120,
                )

                if resp.status_code == 200:
                    result = resp.json()
                    st.session_state["analysis_result"] = result

                    st.success("✅ Analysis complete!")

                    # ── Summary KPIs ──
                    summary = result["summary"]
                    c1, c2, c3, c4, c5 = st.columns(5)
                    c1.metric("Total Changes", summary["total_changes"])
                    c2.metric("Breaking", summary["breaks"])
                    c3.metric("Degrading", summary["degrades"])
                    c4.metric("No Impact", summary["no_impact"])
                    c5.metric("Impacted Objects", summary["total_impacted_objects"])

                    st.divider()

                    # ── Decision Summary ──
                    dc1, dc2, dc3 = st.columns(3)
                    dc1.metric(
                        "🛑 Hold the Load",
                        summary["hold_the_load"],
                    )
                    dc2.metric(
                        "⚠️ Safe with Warning",
                        summary["safe_with_warning"],
                    )
                    dc3.metric(
                        "✅ Safe to Load",
                        summary["safe_to_load"],
                    )

                    st.divider()

                    # ── Change Summaries Table ──
                    st.subheader("📋 Change-Level Decisions")
                    if result["change_summaries"]:
                        df = pd.DataFrame(result["change_summaries"])
                        st.dataframe(df, use_container_width=True)

                else:
                    error_detail = resp.json().get("detail", resp.text)
                    st.error(f"API error ({resp.status_code}): {error_detail}")

            except requests.ConnectionError:
                st.error(
                    "Cannot reach the FastAPI backend. "
                    "Make sure it is running."
                )
            except Exception as exc:
                st.error(f"Unexpected error: {exc}")

    # Show previous result if available
    elif "analysis_result" in st.session_state:
        result = st.session_state["analysis_result"]
        summary = result["summary"]

        st.info("Showing previous analysis result. Click 'Run Full Analysis' to re-run.")

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Total Changes", summary["total_changes"])
        c2.metric("Breaking", summary["breaks"])
        c3.metric("Degrading", summary["degrades"])
        c4.metric("No Impact", summary["no_impact"])
        c5.metric("Impacted Objects", summary["total_impacted_objects"])

        st.divider()

        st.subheader("📋 Change-Level Decisions")
        if result["change_summaries"]:
            df = pd.DataFrame(result["change_summaries"])
            st.dataframe(df, use_container_width=True)
