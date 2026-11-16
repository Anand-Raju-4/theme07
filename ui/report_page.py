import graphviz
import os
import pandas as pd
import streamlit as st


def render_report_page():

    st.header("📊 Schema Drift Impact Report")

    if "result" not in st.session_state:
        st.warning("Run analysis first")
        return

    result = st.session_state["result"]

    schema_changes = result.get("schema_changes", [])
    impacts = result.get("impacts", [])

    schema_df = pd.DataFrame(schema_changes)
    impact_df = pd.DataFrame(impacts)

    # ==========================
    # KPI CARDS
    # ==========================

    total_changes = len(schema_df)

    high_risk = len(
        impact_df[
            impact_df["severity"] == "high"
        ]
    ) if not impact_df.empty else 0

    affected_assets = (
        impact_df["object"].nunique()
        if not impact_df.empty
        else 0
    )

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "Schema Changes",
        total_changes
    )

    col2.metric(
        "High Risk Issues",
        high_risk
    )

    col3.metric(
        "Affected Assets",
        affected_assets
    )

    st.divider()

    # ==========================
    # SCHEMA CHANGES
    # ==========================

    st.subheader("🔍 Detected Schema Changes")

    if not schema_df.empty:

        display_columns = [
            "change_id",
            "source",
            "change_type",
            "column_before",
            "column_after"
        ]

        available_cols = [
            col for col in display_columns
            if col in schema_df.columns
        ]

        st.dataframe(
            schema_df[available_cols],
            use_container_width=True
        )

    # ==========================
    # SEVERITY CHART
    # ==========================

    if (
        not impact_df.empty
        and "severity" in impact_df.columns
    ):

        st.subheader("📈 Severity Distribution")

        severity_counts = (
            impact_df["severity"]
            .value_counts()
        )

        st.bar_chart(severity_counts)

    # ==========================
    # IMPACT TABLE
    # ==========================

    st.subheader("⚠️ Impact Analysis")

    if not impact_df.empty:

        display_cols = [
            "change_id",
            "object",
            "object_type",
            "impact",
            "severity",
            "decision"
        ]

        available_cols = [
            col for col in display_cols
            if col in impact_df.columns
        ]

        st.dataframe(
            impact_df[available_cols],
            use_container_width=True
        )

    # ==========================
    # HIGH RISK SECTION
    # ==========================

    if (
        not impact_df.empty
        and "severity" in impact_df.columns
    ):

        high_risk_df = impact_df[
            impact_df["severity"] == "high"
        ]

        if not high_risk_df.empty:

            st.subheader("🚨 High Risk Findings")

            for _, row in high_risk_df.iterrows():

                with st.expander(
                    f"{row['change_id']} - {row['object']}"
                ):

                    st.write(
                        f"**Impact:** {row['impact']}"
                    )

                    st.write(
                        f"**Decision:** {row['decision']}"
                    )

                    st.write(
                        f"**Evidence:** {row['evidence']}"
                    )

                    st.write(
                        f"**Proposed Fix:** {row['proposed_fix']}"
                    )


    # ==========================
    # LINEAGE GRAPH
    # ==========================

    lineage = result.get("lineage", {})

    if lineage:

        st.subheader("🔗 End-to-End Data Lineage")

        graph = graphviz.Digraph()

        graph.attr(rankdir="LR")
        graph.attr(
            "node",
            shape="box",
            style="rounded,filled"
        )

        node_colors = {
            "source_table": "#90CAF9",
            "lakehouse_table": "#A5D6A7",
            "notebook": "#FFE082",
            "pipeline": "#FFAB91",
            "pipeline_activity": "#FFCC80",
            "semantic_model": "#CE93D8",
            "semantic_table": "#B39DDB",
            "measure": "#D1C4E9",
            "report": "#F48FB1",
            "report_visual": "#F8BBD0"
        }

        # Add nodes
        for node in lineage.get("nodes", []):

            graph.node(
                node["id"],
                node["name"],
                fillcolor=node_colors.get(
                    node["type"],
                    "#ECEFF1"
                )
            )

        # Add edges
        for edge in lineage.get("edges", []):

            graph.edge(
                edge["source"],
                edge["target"]
            )

        st.graphviz_chart(
            graph,
            use_container_width=True
        )

        # ==========================
        # DOWNLOAD
        # ==========================

        report_path = "outputs/impact_analysis.json"

        if os.path.exists(report_path):

            with open(report_path, "rb") as file:

                st.download_button(
                    "⬇ Download Impact Report",
                    file,
                    "impact_analysis.json"
                )