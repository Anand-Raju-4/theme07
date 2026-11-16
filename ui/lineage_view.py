"""
Lineage Visualization Engine for Streamlit UI
===============================================

Provides clean, layered, and understandable Graphviz representations:
1. End-to-End Data Flow (Data Asset Lineage)
2. Blast Radius (Impact-only Lineage for any selected Change ID)
3. Full System Architecture (Pipelines + Notebooks + Tables)

Fixes:
- Sanitizes all Graphviz node IDs (removes colons ':' so Graphviz doesn't interpret them as ports)
- Uses smooth splines to prevent weird overlapping and disconnected edges
- Groups nodes into logical clusters
"""

from __future__ import annotations

import graphviz
from typing import Any


def safe_id(nid: str) -> str:
    """
    Sanitize node ID for Graphviz dot syntax.
    Graphviz treats colons ':' as port separators on nodes (e.g. 'node:port').
    Replacing with double underscores prevents phantom unlinked port nodes.
    """
    return (
        str(nid)
        .replace(":", "__")
        .replace(".", "_")
        .replace("/", "__")
        .replace(" ", "_")
        .replace("-", "_")
        .replace("%", "pct")
        .replace("[", "")
        .replace("]", "")
    )


# ── Color Palette ──────────────────────────────────────────

LAYER_COLORS = {
    "source_table": {"fill": "#E3F2FD", "border": "#1976D2", "font": "#0D47A1"},
    "bronze": {"fill": "#EFEBE9", "border": "#5D4037", "font": "#3E2723"},
    "silver": {"fill": "#ECEFF1", "border": "#455A64", "font": "#263238"},
    "gold": {"fill": "#FFF9C4", "border": "#FBC02D", "font": "#F57F17"},
    "notebook": {"fill": "#FFF3E0", "border": "#E65100", "font": "#BF360C"},
    "pipeline": {"fill": "#F3E5F5", "border": "#7B1FA2", "font": "#4A148C"},
    "pipeline_activity": {"fill": "#F3E5F5", "border": "#8E24AA", "font": "#4A148C"},
    "semantic_table": {"fill": "#EDE7F6", "border": "#512DA8", "font": "#311B92"},
    "measure": {"fill": "#E8EAF6", "border": "#283593", "font": "#1A237E"},
    "report_visual": {"fill": "#FCE4EC", "border": "#C2185B", "font": "#880E4F"},
    "report": {"fill": "#F8BBD0", "border": "#AD1457", "font": "#880E4F"},
}

SEVERITY_COLORS = {
    "BREAKS": {"fill": "#FFCDD2", "border": "#B71C1C", "font": "#B71C1C"},
    "DEGRADES": {"fill": "#FFE082", "border": "#E65100", "font": "#BF360C"},
    "NO IMPACT": {"fill": "#C8E6C9", "border": "#1B5E20", "font": "#1B5E20"},
    "SAFE TO LOAD": {"fill": "#C8E6C9", "border": "#1B5E20", "font": "#1B5E20"},
}


def _clean_node_label(node: dict[str, Any]) -> str:
    """Format a clean, readable label with icons and layer subtitles."""
    ntype = node.get("type", "")
    name = node.get("name", "")

    if ntype == "source_table":
        return f"🗄️ {name}\\n[Source System]"
    elif ntype == "lakehouse_table":
        if "bronze." in name:
            short = name.replace("bronze.", "")
            return f"🥉 {short}\\n[Bronze Lakehouse]"
        elif "silver." in name:
            short = name.replace("silver.", "")
            return f"🥈 {short}\\n[Silver Lakehouse]"
        elif "gold." in name:
            short = name.replace("gold.", "")
            return f"🥇 {short}\\n[Gold Mart]"
        return f"📦 {name}\\n[Delta Table]"
    elif ntype == "notebook":
        return f"⚡ {name}\\n[Databricks Notebook]"
    elif ntype == "pipeline":
        return f"🔄 {name}\\n[ADF Pipeline]"
    elif ntype == "pipeline_activity":
        short = name.split("/")[-1]
        return f"⚙️ {short}\\n[Activity]"
    elif ntype == "semantic_table":
        return f"📐 {name}\\n[Semantic Table]"
    elif ntype == "measure":
        return f"📏 [{name}]\\n[DAX Measure]"
    elif ntype == "report_visual":
        parts = name.split("/")
        vis = parts[-1]
        rep = parts[0] if len(parts) > 1 else ""
        return f"📊 {vis}\\n({rep})"
    elif ntype == "report":
        return f"📈 {name}\\n[Power BI Report]"

    return name


def _table_layer(table_name: str) -> str:
    if "bronze." in table_name:
        return "bronze"
    elif "silver." in table_name:
        return "silver"
    elif "gold." in table_name:
        return "gold"
    return "lakehouse_table"


# ── View 1: Clean Data Pipeline Flow ────────────────────────

def render_data_pipeline_lineage(lineage: dict[str, Any]) -> graphviz.Digraph:
    """
    Renders a clean, structured left-to-right data pipeline graph.
    Only shows data assets (Sources -> Bronze -> Silver -> Gold -> Semantic -> Visuals).
    Properly links all edges with sanitized IDs.
    """
    dot = graphviz.Digraph("DataPipelineLineage")
    dot.attr(rankdir="LR", splines="true", nodesep="0.4", ranksep="0.8")
    dot.attr("node", shape="box", style="rounded,filled", fontname="Segoe UI, sans-serif", fontsize="10")
    dot.attr("edge", color="#546E7A", fontname="Segoe UI, sans-serif", fontsize="8", arrowsize="0.8")

    nodes_by_id = {n["id"]: n for n in lineage.get("nodes", [])}
    edges = lineage.get("edges", [])

    # Filter out pure orchestration nodes for the clean data flow
    ignored_types = {"pipeline", "pipeline_activity", "report", "notebook"}
    relevant_nodes = {nid: n for nid, n in nodes_by_id.items() if n.get("type") not in ignored_types}

    # Group by layer
    sources = []
    bronze = []
    silver = []
    gold = []
    semantics = []
    measures = []
    visuals = []

    for nid, node in relevant_nodes.items():
        ntype = node.get("type", "")
        nname = node.get("name", "")
        if ntype == "source_table":
            sources.append((nid, node))
        elif ntype == "lakehouse_table":
            layer = _table_layer(nname)
            if layer == "bronze":
                bronze.append((nid, node))
            elif layer == "silver":
                silver.append((nid, node))
            elif layer == "gold":
                gold.append((nid, node))
        elif ntype == "semantic_table":
            semantics.append((nid, node))
        elif ntype == "measure":
            measures.append((nid, node))
        elif ntype == "report_visual":
            visuals.append((nid, node))

    clusters = [
        ("cluster_sources", "1. Source Systems", "#E3F2FD", "#1565C0", sources, "source_table"),
        ("cluster_bronze", "2. Bronze Raw Storage", "#EFEBE9", "#4E342E", bronze, "bronze"),
        ("cluster_silver", "3. Silver Conformed", "#ECEFF1", "#37474F", silver, "silver"),
        ("cluster_gold", "4. Gold Dimensional Marts", "#FFF9C4", "#F57F17", gold, "gold"),
        ("cluster_semantic", "5. Power BI Semantic Model", "#EDE7F6", "#4527A0", semantics + measures, "semantic_table"),
        ("cluster_visuals", "6. Report Visuals", "#FCE4EC", "#AD1457", visuals, "report_visual"),
    ]

    for cluster_name, label, bgcolor, bordercolor, items, fallback_type in clusters:
        with dot.subgraph(name=cluster_name) as c:
            c.attr(label=label, style="rounded,filled", fillcolor=bgcolor, color=bordercolor, fontcolor=bordercolor, fontname="Segoe UI Bold", fontsize="11")
            for nid, node in items:
                ntype = node.get("type", "")
                palette = LAYER_COLORS.get(ntype, LAYER_COLORS.get(fallback_type, {}))
                c.node(
                    safe_id(nid),
                    label=_clean_node_label(node),
                    fillcolor=palette.get("fill", "#FFFFFF"),
                    color=palette.get("border", "#9E9E9E"),
                    fontcolor=palette.get("font", "#000000"),
                    penwidth="1.5",
                )

    allowed_rels = {
        "ingested_to",
        "transformed_to",
        "modelled_as",
        "column_used_by_measure",
        "measure_dependency",
        "used_by_visual",
        "column_used_by_visual",
    }

    for e in edges:
        src = e.get("source")
        tgt = e.get("target")
        rel = e.get("relationship")

        if src in relevant_nodes and tgt in relevant_nodes and rel in allowed_rels:
            dot.edge(safe_id(src), safe_id(tgt))

    return dot


# ── View 2: Blast Radius (Impact Lineage Only) ───────────────

def render_blast_radius_lineage(
    lineage: dict[str, Any],
    impact_rows: list[dict[str, Any]],
    selected_change_id: str | None = None,
) -> graphviz.Digraph:
    """
    Renders ONLY the path of impacted nodes for a specific schema change (or all changes).
    Highlights nodes with severity colors (Red for Breaks, Yellow for Degrades).
    Uses safe_id to guarantee all nodes connect without port confusion.
    """
    dot = graphviz.Digraph("BlastRadiusLineage")
    dot.attr(rankdir="LR", splines="true", nodesep="0.4", ranksep="0.8")
    dot.attr("node", shape="box", style="rounded,filled", fontname="Segoe UI, sans-serif", fontsize="10")
    dot.attr("edge", fontname="Segoe UI, sans-serif", fontsize="8", penwidth="2")

    nodes_by_id = {n["id"]: n for n in lineage.get("nodes", [])}
    nodes_by_name = {n["name"]: n for n in lineage.get("nodes", [])}

    # Filter impact rows by selected change_id if specified
    active_impacts = impact_rows
    if selected_change_id and selected_change_id != "ALL":
        active_impacts = [r for r in impact_rows if r.get("change_id") == selected_change_id]

    # Map impacted object names to severity/impact
    impact_map: dict[str, dict[str, str]] = {}
    for row in active_impacts:
        obj_name = row.get("object", "")
        impact = str(row.get("impact", "")).upper()
        severity = str(row.get("severity", "")).upper()
        impact_map[obj_name] = {"impact": impact, "severity": severity, "change_id": row.get("change_id", "")}

    # Collect impacted node IDs
    impacted_node_ids = set()
    for obj_name in impact_map:
        if obj_name in nodes_by_name:
            impacted_node_ids.add(nodes_by_name[obj_name]["id"])
        for nid in nodes_by_id:
            if nid.endswith(f":{obj_name}") or nid == obj_name:
                impacted_node_ids.add(nid)

    # If no impacted nodes found, return empty placeholder
    if not impacted_node_ids:
        dot.node("no_impact", "✅ No downstream impact identified for this change\\n(Safe to load)", fillcolor="#C8E6C9", color="#2E7D32")
        return dot

    # Add impacted nodes to graph with high-visibility styling
    for nid in impacted_node_ids:
        node = nodes_by_id.get(nid, {"name": nid, "type": "unknown"})
        name = node.get("name", nid)
        info = impact_map.get(name, impact_map.get(nid, {}))
        impact = info.get("impact", "BREAKS")

        colors = SEVERITY_COLORS.get(impact, SEVERITY_COLORS["BREAKS"])
        badge = "🛑 BREAKS" if impact == "BREAKS" else "⚠️ DEGRADES" if impact == "DEGRADES" else "🟢 SAFE"

        label = f"{_clean_node_label(node)}\\n━━━━━━━━━━━━━━\\n{badge}"
        dot.node(
            safe_id(nid),
            label=label,
            fillcolor=colors["fill"],
            color=colors["border"],
            fontcolor=colors.get("font", "#000000"),
            penwidth="2.5",
        )

    # Find edges that connect impacted nodes
    has_breaks = any(v.get("impact") == "BREAKS" for v in impact_map.values())
    edge_color = "#C62828" if has_breaks else "#EF6C00"

    for e in lineage.get("edges", []):
        src = e.get("source")
        tgt = e.get("target")
        if src in impacted_node_ids and tgt in impacted_node_ids:
            dot.edge(safe_id(src), safe_id(tgt), color=edge_color)

    return dot


# ── View 3: Full Architecture Graph ──────────────────────────

def render_full_architecture_lineage(lineage: dict[str, Any]) -> graphviz.Digraph:
    """
    Renders all 53 nodes with subgraphs/clusters for pipelines, notebooks, and models
    so nodes connect cleanly without port errors.
    """
    dot = graphviz.Digraph("FullArchitectureLineage")
    dot.attr(rankdir="LR", splines="true", nodesep="0.4", ranksep="0.8")
    dot.attr("node", shape="box", style="rounded,filled", fontname="Segoe UI, sans-serif", fontsize="9")
    dot.attr("edge", fontname="Segoe UI, sans-serif", fontsize="8", color="#90A4AE", arrowsize="0.7")

    nodes_by_id = {n["id"]: n for n in lineage.get("nodes", [])}

    # Add all nodes styled by layer
    for nid, node in nodes_by_id.items():
        ntype = node.get("type", "")
        nname = node.get("name", "")
        layer_key = _table_layer(nname) if ntype == "lakehouse_table" else ntype
        palette = LAYER_COLORS.get(layer_key, LAYER_COLORS.get(ntype, {"fill": "#ECEFF1", "border": "#607D8B"}))

        dot.node(
            safe_id(nid),
            label=_clean_node_label(node),
            fillcolor=palette.get("fill", "#ECEFF1"),
            color=palette.get("border", "#607D8B"),
            fontcolor=palette.get("font", "#000000"),
        )

    # Add all edges with safe_id
    for e in lineage.get("edges", []):
        dot.edge(safe_id(e["source"]), safe_id(e["target"]))

    return dot
