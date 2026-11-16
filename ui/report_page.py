# ui/report_page.py

import pandas as pd
import requests
import streamlit as st
from ui.lineage_view import (
    render_data_pipeline_lineage,
    render_blast_radius_lineage,
    render_full_architecture_lineage,
)


def render_report_page():

    st.header("📊 Schema Drift Impact Report")

    if "analysis_result" not in st.session_state:
        st.warning("⬅️ Run the analysis first from the **🔬 Run Analysis** page.")
        return

    result = st.session_state["analysis_result"]
    api_base = st.session_state.get("api_base", "http://localhost:8000")

    impacts = result.get("impacts", [])
    change_summaries = result.get("change_summaries", [])

    impact_df = pd.DataFrame(impacts) if impacts else pd.DataFrame()
    summary_df = pd.DataFrame(change_summaries) if change_summaries else pd.DataFrame()

    # ==========================
    # 1. KPI CARDS
    # ==========================
    summary = result.get("summary", {})

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("🔢 Total Changes", summary.get("total_changes", 0))
    col2.metric("🛑 Hold the Load", summary.get("hold_the_load", 0))
    col3.metric("⚠️ Safe with Warning", summary.get("safe_with_warning", 0))
    col4.metric("✅ Safe to Load", summary.get("safe_to_load", 0))
    col5.metric("📦 Impacted Assets", summary.get("total_impacted_objects", 0))

    st.divider()

    # ==========================
    # 2. STRUCTURED REPORT TABS
    # ==========================
    tab_impacts, tab_gate, tab_drift, tab_high_risk = st.tabs([
        "🚨 Downstream Impact Analysis",
        "⚖️ Pipeline Decision Gate",
        "🔍 Detected Schema Drift",
        "🚨 Critical Findings Deep-Dive",
    ])

    # ── Tab 1: Downstream Impact Analysis ──
    with tab_impacts:
        st.subheader("📦 Downstream Assets Impacted by Schema Drift")
        st.caption("Shows which Lakehouse tables, Databricks notebooks, Semantic Models, and Power BI Visuals are affected.")

        if not impact_df.empty:
            # Filter out pure source-level placeholder rows if there are actual downstream impacts
            real_impacts = impact_df[impact_df["object_type"] != "source_table"]
            display_data = real_impacts if not real_impacts.empty else impact_df

            display_cols = [
                "change_id",
                "object",
                "object_type",
                "impact",
                "severity",
                "decision",
                "proposed_fix",
                "evidence",
            ]
            available_cols = [c for c in display_cols if c in display_data.columns]

            def color_impact(val):
                if val == "BREAKS":
                    return "background-color: #ffcdd2; font-weight: bold"
                elif val == "DEGRADES":
                    return "background-color: #fff9c4"
                elif val in {"NO IMPACT", "SAFE TO LOAD"}:
                    return "background-color: #c8e6c9"
                return ""

            styled_impact = display_data[available_cols].style.map(
                color_impact,
                subset=["impact"] if "impact" in available_cols else [],
            )
            st.dataframe(styled_impact, use_container_width=True)
        else:
            st.info("No downstream impacts detected.")

    # ── Tab 2: Decision Gate ──
    with tab_gate:
        st.subheader("⚖️ Pipeline Load Gate Decisions")
        st.caption("Change-level policy verdict determining whether ingestion pipelines should proceed, warn, or hold.")

        if not summary_df.empty:
            display_cols = [
                "change_id",
                "source",
                "change_type",
                "column_before",
                "column_after",
                "impact",
                "severity",
                "decision",
                "affected_object_count",
            ]
            available_cols = [c for c in display_cols if c in summary_df.columns]

            def highlight_decision(val):
                if val == "HOLD THE LOAD":
                    return "background-color: #ffcdd2; font-weight: bold; color: #b71c1c"
                elif val == "SAFE WITH WARNING":
                    return "background-color: #fff9c4; font-weight: bold; color: #e65100"
                elif val == "SAFE TO LOAD":
                    return "background-color: #c8e6c9; font-weight: bold; color: #1b5e20"
                return ""

            styled_gate = summary_df[available_cols].style.map(
                highlight_decision,
                subset=["decision"] if "decision" in available_cols else [],
            )
            st.dataframe(styled_gate, use_container_width=True)

    # ── Tab 3: Schema Drift Summary ──
    with tab_drift:
        st.subheader("🔍 Schema Diffs Detected")
        st.caption("Source-level column modifications comparing Before vs. After schemas.")
        if "schema_diff" in st.session_state and st.session_state["schema_diff"].get("changes"):
            diff_df = pd.DataFrame(st.session_state["schema_diff"]["changes"])
            st.dataframe(diff_df, use_container_width=True)
        elif not summary_df.empty:
            cols = [c for c in ["change_id", "source", "change_type", "column_before", "column_after"] if c in summary_df.columns]
            st.dataframe(summary_df[cols], use_container_width=True)

    # ── Tab 4: High Risk Findings Deep Dive ──
    with tab_high_risk:
        st.subheader("🚨 Critical & High-Risk Findings")
        if not impact_df.empty and "severity" in impact_df.columns:
            high_risk_df = impact_df[impact_df["severity"] == "HIGH"]
            if not high_risk_df.empty:
                for _, row in high_risk_df.iterrows():
                    with st.expander(f"🛑 {row.get('change_id', '')} — {row.get('object', '')} ({row.get('object_type', '')})"):
                        rcol1, rcol2 = st.columns(2)
                        with rcol1:
                            st.markdown(f"**Impact:** `{row.get('impact', '')}`")
                            st.markdown(f"**Severity:** `{row.get('severity', '')}`")
                            st.markdown(f"**Pipeline Gate:** `{row.get('decision', '')}`")
                        with rcol2:
                            st.markdown(f"**Evidence:** {row.get('evidence', '')}")
                            st.markdown(f"**Proposed Fix:** {row.get('proposed_fix', '')}")
            else:
                st.success("✅ No high-severity breaking changes detected.")

    st.divider()

    # ==========================
    # 3. END-TO-END DATA LINEAGE
    # ==========================
    lineage = result.get("lineage", {})

    if lineage:
        st.subheader("🔗 End-to-End Data Lineage")
        st.markdown(
            "Visualise how schema changes propagate downstream through "
            "**Bronze ➔ Silver ➔ Gold ➔ Power BI Semantic Models ➔ Report Visuals**."
        )

        view_mode = st.radio(
            "Select Lineage Perspective",
            [
                "🌟 Layered Data Pipeline (Clean Architecture)",
                "🎯 Blast Radius (Impact Highlighted)",
                "⚙️ Full Orchestration Graph (53 Nodes)",
            ],
            horizontal=True,
        )

        if "Layered Data Pipeline" in view_mode:
            st.caption("Clean forward flow: Sources ➔ Bronze ➔ Silver ➔ Gold ➔ Semantic Models ➔ Report Visuals")
            graph = render_data_pipeline_lineage(lineage)
            st.graphviz_chart(graph, use_container_width=True)

        elif "Blast Radius" in view_mode:
            st.caption("Trace the exact downstream path affected by a schema change. Red = Breaks, Yellow = Degrades.")

            change_options = ["ALL"] + [
                f"{cs.get('change_id')}: {cs.get('source')} ({cs.get('column_before') or ''} ➔ {cs.get('column_after') or ''})"
                for cs in change_summaries
                if cs.get("change_id")
            ]

            selected_option = st.selectbox(
                "Filter Blast Radius by Schema Change",
                options=change_options,
                index=0,
            )

            selected_id = "ALL" if selected_option == "ALL" else selected_option.split(":")[0].strip()

            graph = render_blast_radius_lineage(lineage, impacts, selected_change_id=selected_id)
            st.graphviz_chart(graph, use_container_width=True)

        else:
            st.caption("Complete technical topology including ADF pipelines, activities, notebooks, and semantic tables.")
            graph = render_full_architecture_lineage(lineage)
            st.graphviz_chart(graph, use_container_width=True)

    st.divider()

    # ==========================
    # 4. DOWNLOAD REPORT
    # ==========================
    st.subheader("⬇️ Export Compliance Report")

    try:
        resp = requests.get(f"{api_base}/api/report", timeout=30)
        if resp.status_code == 200:
            st.download_button(
                "📥 Download Impact Report (CSV)",
                data=resp.content,
                file_name="impact_report.csv",
                mime="text/csv",
            )
        else:
            st.info("Report CSV not yet available.")
    except Exception as exc:
        st.warning(f"Report export unavailable: {exc}")
