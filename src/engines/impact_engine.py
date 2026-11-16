"""Deterministic downstream impact analysis for IBD 2.0 Theme 07.

Public API:
    analyze_impacts(schema_changes, lineage) -> list[dict]

The engine combines schema-diff records with evidence in the lineage graph.
It does not hardcode seeded change IDs or expected outcomes. Rename analysis
uses the old column name supplied by schema_diff.py and explicit lineage
references. This is static analysis, not execution of source pipelines.
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Any


_BREAKING_TYPES = {"drop", "rename"}
_COMPATIBLE_WIDENING = {
    ("decimal", "decimal"),
    ("integer", "long"),
    ("int", "bigint"),
    ("float", "double"),
}


def _normal_type(value: str | None) -> str:
    """Normalize a type name while retaining its base type."""
    if not value:
        return ""
    value = value.strip().lower()
    return value.split("(", 1)[0].strip()


def _is_compatible_type_change(before: str | None, after: str | None) -> bool:
    old, new = _normal_type(before), _normal_type(after)
    if old == new and old:
        # Same base type with a precision/scale change, e.g. decimal(18,2)
        # to decimal(20,4), is treated as a widening candidate.
        if old == "decimal":
            try:
                old_precision, old_scale = map(
                    int, before.lower().split("(", 1)[1].rstrip(")").split(",")
                )
                new_precision, new_scale = map(
                    int, after.lower().split("(", 1)[1].rstrip(")").split(",")
                )
                return new_precision >= old_precision and new_scale >= old_scale
            except (AttributeError, ValueError, IndexError):
                return before == after
        return before == after
    return (old, new) in _COMPATIBLE_WIDENING


def _node_index(lineage: dict[str, Any]) -> dict[str, dict[str, Any]]:
    nodes = lineage.get("nodes", [])
    if not isinstance(nodes, list):
        raise ValueError("lineage['nodes'] must be a list")
    result = {}
    for node in nodes:
        if not isinstance(node, dict) or not node.get("id"):
            raise ValueError(f"Invalid lineage node: {node!r}")
        result[node["id"]] = node
    return result


def _edge_index(lineage: dict[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    edges = lineage.get("edges", [])
    if not isinstance(edges, list):
        raise ValueError("lineage['edges'] must be a list")
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        if not isinstance(edge, dict) or not edge.get("source") or not edge.get("target"):
            raise ValueError(f"Invalid lineage edge: {edge!r}")
        outgoing[edge["source"]].append(edge)
    return outgoing, edges


def _source_node_id(source: str) -> str:
    return f"source_table:{source}"


def _edge_mentions_column(edge: dict[str, Any], column: str | None) -> bool:
    if not column:
        return False
    for key in ("columns", "selected_columns", "referenced_columns"):
        values = edge.get(key)
        if isinstance(values, list) and column in values:
            return True
    return False


def _find_direct_consumers(
    source: str,
    column: str | None,
    outgoing: dict[str, list[dict[str, Any]]],
) -> tuple[list[str], list[str], bool]:
    """Return (direct nodes, evidence, explicit_ingestion_dependency).

    Explicit SQL projections in the ingestion config are a hard dependency:
    if the source no longer supplies a projected column, ingestion fails.
    Otherwise the engine looks for a column reference in notebook/table edges.
    """
    source_id = _source_node_id(source)
    ingestion_edges = [
        edge for edge in outgoing.get(source_id, [])
        if edge.get("relationship") == "ingested_to"
    ]
    direct_nodes: list[str] = []
    evidence: list[str] = []
    explicit_ingestion_dependency = False

    for edge in ingestion_edges:
        selected = edge.get("selected_columns")
        if column and isinstance(selected, list) and column in selected:
            explicit_ingestion_dependency = True
            direct_nodes.append(edge["target"])
            evidence.append(edge.get("evidence", "Ingestion projection references changed column"))

        bronze_id = edge["target"]
        for consumer_edge in outgoing.get(bronze_id, []):
            if consumer_edge.get("relationship") not in {"read_by", "transformed_to"}:
                continue
            if _edge_mentions_column(consumer_edge, column):
                direct_nodes.append(consumer_edge["target"])
                evidence.append(consumer_edge.get("evidence", "Lineage edge references changed column"))

    # Preserve order while removing duplicates.
    return list(dict.fromkeys(direct_nodes)), list(dict.fromkeys(evidence)), explicit_ingestion_dependency


def _downstream_nodes(
    start_nodes: list[str],
    outgoing: dict[str, list[dict[str, Any]]],
    nodes: dict[str, dict[str, Any]],
) -> list[str]:
    """Walk forward through the directed lineage graph from affected nodes."""
    queue = deque(start_nodes)
    visited: set[str] = set()
    ordered: list[str] = []
    allowed = {
        "writes_to", "transformed_to", "modelled_as", "column_used_by_measure",
        "column_used_by_visual", "measure_dependency", "used_by_visual",
        "defined_in", "serves_report", "contains_visual", "belongs_to_model",
    }
    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        if current in nodes:
            ordered.append(current)
        for edge in outgoing.get(current, []):
            if edge.get("relationship") in allowed and edge["target"] not in visited:
                queue.append(edge["target"])
    return ordered


def _classify(change: dict[str, Any], explicit_ingestion_dependency: bool,
              direct_consumers: list[str], permissive_source: bool = False) -> tuple[str, str, str, str]:
    kind = str(change.get("change_type", "")).lower()
    before_type = change.get("type_before")
    after_type = change.get("type_after")

    if kind in _BREAKING_TYPES and (explicit_ingestion_dependency or direct_consumers):
        if permissive_source:
            return (
                "degrades", "medium", "SAFE WITH WARNING",
                "A permissive schema-based ingestion may retain the row but produce null/missing values for the renamed or removed field.",
            )
        return (
            "breaks", "high", "HOLD THE LOAD",
            "The changed or removed column is explicitly selected or consumed downstream.",
        )
    if kind == "type change":
        if _is_compatible_type_change(before_type, after_type):
            return (
                "no impact", "none", "SAFE TO LOAD",
                "The type change is a compatible widening candidate and no incompatible use was detected.",
            )
        if explicit_ingestion_dependency or direct_consumers:
            if permissive_source:
                return (
                    "degrades", "medium", "SAFE WITH WARNING",
                    "Permissive schema parsing may coerce incompatible values to null; validate the parsed values before loading.",
                )
            return (
                "breaks", "high", "HOLD THE LOAD",
                "A downstream consumer references the column after an incompatible type change; validate or cast before loading.",
            )
        return (
            "no impact", "none", "SAFE TO LOAD",
            "No downstream dependency was found for this type change.",
        )
    if kind == "add":
        return (
            "no impact", "none", "SAFE TO LOAD",
            "No existing downstream dependency requires the newly added column.",
        )
    return (
        "no impact", "none", "SAFE TO LOAD",
        "No downstream dependency was found in the available lineage evidence.",
    )


def _proposed_fix(change: dict[str, Any], impact: str) -> str:
    kind = str(change.get("change_type", "")).lower()
    old = change.get("column_before")
    new = change.get("column_after")
    if impact == "no impact":
        return "No change required; retain the new schema and monitor the next pipeline run."
    if kind == "rename":
        return (
            f"Update downstream references from '{old}' to '{new}', "
            "update explicit schemas and ingestion mappings, then validate in a sandbox."
        )
    if kind == "drop":
        return (
            f"Restore '{old}' or remove it from ingestion projections and downstream transformations; "
            "validate all dependent notebooks before release."
        )
    if kind == "type change":
        return (
            f"Validate values in '{old}', add an explicit safe cast/validation step, "
            "and update dependent transformations before loading."
        )
    return "Review the affected lineage path and validate the proposed schema before loading."


def analyze_impacts(
    schema_changes: list[dict[str, Any]],
    lineage: dict[str, Any],
    ingestion_config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Analyze every schema change and emit one row per affected downstream object.

    A change with no identified consumers still emits one `no impact` row
    against its source object. Rows contain the required report fields plus
    evidence, decision, and rationale for traceability.
    """
    if not isinstance(schema_changes, list):
        raise ValueError("schema_changes must be a list")
    if not isinstance(lineage, dict):
        raise ValueError("lineage must be an object")

    nodes = _node_index(lineage)
    outgoing, _ = _edge_index(lineage)
    ingestion_by_source = {}
    if ingestion_config is not None:
        if not isinstance(ingestion_config, dict):
            raise ValueError("ingestion_config must be an object")
        for entry in ingestion_config.get("sources", []):
            if isinstance(entry, dict) and entry.get("source"):
                ingestion_by_source[entry["source"]] = entry
    results: list[dict[str, Any]] = []

    for change in schema_changes:
        if not isinstance(change, dict):
            raise ValueError(f"Invalid schema change: {change!r}")
        source = change.get("source")
        if not isinstance(source, str) or not source:
            raise ValueError(f"Schema change is missing a valid source: {change!r}")

        column = change.get("column_before") or change.get("column_after")
        direct, evidence, explicit_ingestion = _find_direct_consumers(
            source, column, outgoing
        )
        source_config = ingestion_by_source.get(source, {})
        permissive_source = str(source_config.get("mode", "")).upper() == "PERMISSIVE"
        impact, severity, decision, rationale = _classify(
            change, explicit_ingestion, direct, permissive_source
        )
        affected = _downstream_nodes(direct, outgoing, nodes) if impact != "no impact" else []

        if not affected:
            affected = [_source_node_id(source)]
        proposed_fix = _proposed_fix(change, impact)

        for object_id in affected:
            node = nodes.get(object_id, {
                "id": object_id,
                "name": source,
                "type": "source_table",
                "metadata": {},
            })
            row_evidence = list(evidence)
            if not row_evidence:
                row_evidence.append(rationale)
            results.append({
                "change_id": change.get("change_id"),
                "change_type": change.get("change_type"),
                "source": source,
                "object": node.get("name", object_id),
                "object_type": node.get("type", "unknown"),
                "impact": impact,
                "severity": severity,
                "proposed_fix": proposed_fix,
                "evidence": " | ".join(row_evidence),
                "rationale": rationale,
                "decision": decision,
            })

    return results


def main() -> None:
    """Run impact analysis from the project's generated JSON artifacts."""
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Analyze downstream schema-drift impact.")
    parser.add_argument("--changes", default="outputs/schema_diff.json")
    parser.add_argument("--lineage", default="outputs/lineage.json")
    parser.add_argument(
        "--config", default="starter_kit/project/config/ingest_config.json"
    )
    parser.add_argument("--output", default="outputs/impact_analysis.json")
    args = parser.parse_args()

    def read_json(path: str) -> Any:
        with Path(path).open("r", encoding="utf-8") as handle:
            return json.load(handle)

    changes = read_json(args.changes)
    lineage = read_json(args.lineage)
    config = read_json(args.config) if args.config else None
    rows = analyze_impacts(changes, lineage, config)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    summaries = {}
    for row in rows:
        summaries.setdefault(row.get("change_id") or "UNSEEDED", row)
    print(f"Analyzed {len(changes)} schema changes; generated {len(rows)} impact rows.")
    for change_id, row in summaries.items():
        print(
            f"{change_id} | {row['impact'].upper()} | {row['severity'].upper()} | "
            f"{row['decision']}"
        )
    print(f"Saved: {output}")


if __name__ == "__main__":
    main()
