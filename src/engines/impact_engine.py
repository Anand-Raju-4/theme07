
# """
# Schema Drift Impact Analyzer - Impact Engine
# =============================================

# Uses the actual schema_diff.json format:
# [
#     {
#         "change_id": "SC01",
#         "source": "crm.customers",
#         "change_type": "rename",
#         "column_before": "email",
#         "column_after": "email_address",
#         "description": "email -> email_address"
#     }
# ]

# Uses column-level lineage:
# - transformed_to
# - read_by
# - ingested_to
# - modelled_as
# - column_used_by_measure
# - column_used_by_visual
# - measure_dependency
# - used_by_visual
# - contains_visual

# The engine deliberately avoids generic graph traversal.
# Only verified column dependencies are propagated.
# """

# from __future__ import annotations

# import argparse
# import json
# import re
# from collections import defaultdict, deque
# from pathlib import Path
# from typing import Any


# # ============================================================
# # 1. NORMALISATION
# # ============================================================

# def norm(value: Any) -> str:
#     return str(value or "").strip().lower()


# def canonical_change_type(value: Any) -> str:
#     value = norm(value).replace("-", "_").replace(" ", "_")

#     aliases = {
#         "added": "add",
#         "column_added": "add",
#         "add_column": "add",
#         "dropped": "drop",
#         "column_dropped": "drop",
#         "drop_column": "drop",
#         "renamed": "rename",
#         "column_renamed": "rename",
#         "typechange": "type_change",
#         "datatype_change": "type_change",
#         "data_type_change": "type_change",
#         "column_type_changed": "type_change",
#         "modify_type": "type_change",
#     }

#     return aliases.get(value, value)


# def normalise_change(raw: dict) -> dict:
#     """
#     Convert the real schema-diff fields into a consistent internal format.
#     """

#     change_type = canonical_change_type(raw.get("change_type"))

#     column_before = (
#         raw.get("column_before")
#         or raw.get("old_column")
#         or raw.get("previous_column")
#     )

#     column_after = (
#         raw.get("column_after")
#         or raw.get("new_column")
#         or raw.get("target_column")
#     )

#     description = str(
#         raw.get("description")
#         or raw.get("detail")
#         or ""
#     )

#     # Recover column names from descriptions if necessary.
#     if not column_before and change_type in {"rename", "drop", "type_change"}:
#         match = re.search(
#             r"([A-Za-z_][\w]*)\s*(?:->|→|dropped|:)",
#             description,
#             flags=re.IGNORECASE,
#         )
#         if match:
#             column_before = match.group(1)

#     if not column_after and change_type == "rename":
#         match = re.search(
#             r"(?:->|→)\s*([A-Za-z_][\w]*)",
#             description,
#         )
#         if match:
#             column_after = match.group(1)

#     column = column_before or column_after

#     return {
#         **raw,
#         "change_id": str(raw.get("change_id") or "UNKNOWN"),
#         "source": str(raw.get("source") or raw.get("source_table") or ""),
#         "change_type": change_type,
#         "column": column,
#         "old_column": column_before,
#         "new_column": column_after,
#         "type_before": raw.get("type_before"),
#         "type_after": raw.get("type_after"),
#         "description": description,
#     }


# def normalise_changes(data: Any) -> list[dict]:
#     if isinstance(data, list):
#         raw_changes = data
#     elif isinstance(data, dict):
#         raw_changes = (
#             data.get("changes")
#             or data.get("schema_changes")
#             or data.get("detected_changes")
#             or []
#         )
#     else:
#         raw_changes = []

#     return [
#         normalise_change(item)
#         for item in raw_changes
#         if isinstance(item, dict)
#     ]


# # ============================================================
# # 2. LINEAGE HELPERS
# # ============================================================

# def get_node_id(node: dict) -> str:
#     return str(
#         node.get("id")
#         or node.get("node_id")
#         or node.get("name")
#         or ""
#     )


# def get_node_name(node: dict, fallback: str) -> str:
#     return str(
#         node.get("name")
#         or node.get("object")
#         or node.get("table")
#         or fallback
#     )


# def get_node_type(node: dict) -> str:
#     return str(
#         node.get("type")
#         or node.get("object_type")
#         or node.get("node_type")
#         or "unknown"
#     )


# def get_relationship(edge: dict) -> str:
#     return norm(
#         edge.get("relationship")
#         or edge.get("type")
#         or edge.get("label")
#     )


# def get_column_set(edge: dict, *field_names: str) -> set[str]:
#     result = set()

#     for field in field_names:
#         value = edge.get(field)

#         if isinstance(value, str):
#             result.add(value.strip())

#         elif isinstance(value, list):
#             result.update(
#                 str(item).strip()
#                 for item in value
#                 if item is not None
#             )

#         elif isinstance(value, dict):
#             result.update(str(item).strip() for item in value)

#     return {item for item in result if item}


# def get_dependencies(edge: dict) -> dict[str, list[str]]:
#     """
#     The lineage extractor stores dependencies as:

#         output_column: [input_column_1, input_column_2]

#     Example:
#         cost_amount: [cost_price, quantity]
#     """

#     raw = edge.get("column_dependencies") or {}

#     if not isinstance(raw, dict):
#         return {}

#     result = {}

#     for output_column, input_columns in raw.items():
#         if isinstance(input_columns, str):
#             input_columns = [input_columns]

#         if not isinstance(input_columns, list):
#             continue

#         result[str(output_column)] = [
#             str(item)
#             for item in input_columns
#             if item is not None
#         ]

#     return result


# def build_graph(lineage: dict):
#     raw_nodes = lineage.get("nodes", [])
#     raw_edges = lineage.get("edges", [])

#     if isinstance(raw_nodes, dict):
#         nodes = {
#             str(key): (
#                 value if isinstance(value, dict)
#                 else {"name": str(value)}
#             )
#             for key, value in raw_nodes.items()
#         }
#     else:
#         nodes = {}

#         for node in raw_nodes:
#             if isinstance(node, dict):
#                 node_id = get_node_id(node)
#                 if node_id:
#                     nodes[node_id] = node

#     edges = [
#         edge for edge in raw_edges
#         if isinstance(edge, dict)
#     ]

#     outgoing = defaultdict(list)
#     incoming = defaultdict(list)

#     for edge in edges:
#         source = str(edge.get("source") or "")
#         target = str(edge.get("target") or "")

#         if source and target:
#             outgoing[source].append(edge)
#             incoming[target].append(edge)

#     return nodes, edges, outgoing, incoming


# # ============================================================
# # 3. SOURCE TABLE RESOLUTION
# # ============================================================

# def source_candidates(source: str) -> list[str]:
#     """
#     Example:
#         crm.customers
#         -> source_table:crm.customers
#         -> lakehouse_table:bronze.crm_customers

#     Supports source nodes and Bronze table fallback.
#     """

#     source = source.strip()
#     candidates = [
#         f"source_table:{source}",
#         f"source:{source}",
#         source,
#     ]

#     if "." in source:
#         system, table = source.split(".", 1)
#         bronze_table = f"bronze.{system}_{table}"

#         candidates.extend([
#             f"lakehouse_table:{bronze_table}",
#             bronze_table,
#         ])

#     return candidates


# def resolve_source(source: str, nodes: dict) -> str | None:
#     for candidate in source_candidates(source):
#         if candidate in nodes:
#             return candidate

#     source_normalised = norm(source)

#     # Search by exact suffix or source-table identity.
#     for node_id, node in nodes.items():
#         node_id_normalised = norm(node_id)
#         node_name = norm(get_node_name(node, node_id))

#         if (
#             node_id_normalised.endswith(":" + source_normalised)
#             or node_name == source_normalised
#         ):
#             return node_id

#     # Last-resort Bronze table match.
#     if "." in source:
#         system, table = source.split(".", 1)
#         expected = norm(f"bronze.{system}_{table}")

#         for node_id in nodes:
#             if expected in norm(node_id):
#                 return node_id

#     return None


# # ============================================================
# # 4. TYPE COMPATIBILITY
# # ============================================================

# def decimal_shape(data_type: Any):
#     if not data_type:
#         return None

#     match = re.search(
#         r"decimal\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)",
#         str(data_type),
#         flags=re.IGNORECASE,
#     )

#     if not match:
#         return None

#     precision = int(match.group(1))
#     scale = int(match.group(2))

#     return precision, scale


# def is_compatible_widening(change: dict) -> bool:
#     before = decimal_shape(change.get("type_before"))
#     after = decimal_shape(change.get("type_after"))

#     if not before or not after:
#         return False

#     before_precision, before_scale = before
#     after_precision, after_scale = after

#     before_integer_digits = before_precision - before_scale
#     after_integer_digits = after_precision - after_scale

#     return (
#         after_scale >= before_scale
#         and after_integer_digits >= before_integer_digits
#     )


# # ============================================================
# # 5. IMPACT CLASSIFICATION
# # ============================================================

# def impact_rank(value: str) -> int:
#     return {
#         "NO IMPACT": 0,
#         "DEGRADES": 1,
#         "BREAKS": 2,
#     }.get(value, 0)


# def severity_rank(value: str) -> int:
#     return {
#         "NONE": 0,
#         "LOW": 1,
#         "MEDIUM": 2,
#         "HIGH": 3,
#         "CRITICAL": 4,
#     }.get(value, 0)


# def classify_change(
#     change: dict,
#     dependency_kind: str = "direct",
#     ingestion_context: dict | None = None,
# ) -> tuple[str, str]:

#     change_type = change["change_type"]
#     ingestion_context = ingestion_context or {}

#     # A renamed field in a JSON source using an explicit schema
#     # and PERMISSIVE parsing may not fail ingestion.
#     # Instead, old consumers may receive missing/null values.
#     # Therefore classify this as degradation.
#     if (
#         change_type == "rename"
#         and norm(ingestion_context.get("reader")) == "json"
#         and norm(ingestion_context.get("mode")) == "permissive"
#         and bool(ingestion_context.get("has_explicit_schema"))
#     ):
#         return "DEGRADES", "MEDIUM"

#     # Adding a column does not break existing consumers.
#     if change_type == "add":
#         return "NO IMPACT", "NONE"

#     # Compatible decimal widening.
#     if (
#         change_type == "type_change"
#         and is_compatible_widening(change)
#     ):
#         return "NO IMPACT", "NONE"

#     if change_type == "type_change":
#         before = norm(change.get("type_before"))
#         after = norm(change.get("type_after"))

#         # Boolean -> string may cause semantic degradation.
#         if before in {"boolean", "bool"} and after in {
#             "string", "varchar", "text"
#         }:
#             return "DEGRADES", "MEDIUM"

#         # Incompatible arithmetic types.
#         if dependency_kind == "derived":
#             return "BREAKS", "HIGH"

#         return "DEGRADES", "MEDIUM"

#     if change_type == "drop":
#         return "BREAKS", "HIGH"

#     if change_type == "rename":
#         # Renamed join keys can cause missing matches.
#         if dependency_kind == "join_key":
#             return "DEGRADES", "MEDIUM"

#     return "BREAKS", "HIGH"



# # ============================================================
# # 6. PROPOSED FIX
# # ============================================================

# def proposed_fix(change: dict) -> str:
#     kind = change["change_type"]
#     old = change.get("old_column")
#     new = change.get("new_column")

#     if kind == "rename":
#         return (
#             f"Update references from '{old}' to '{new}' in the "
#             "affected ingestion, notebook and downstream model."
#         )

#     if kind == "drop":
#         return (
#             f"Restore '{old}' or remove/update its downstream references "
#             "before allowing the load."
#         )

#     if kind == "type_change":
#         return (
#             f"Validate the new type of '{old}'. Add an explicit cast or "
#             "update dependent calculations where necessary."
#         )

#     if kind == "add":
#         return (
#             f"Optionally map the new column '{new}' into downstream models."
#         )

#     return "Review the dependency and validate the affected pipeline."


# # ============================================================
# # 7. RESULT COLLECTION
# # ============================================================

# def add_impact(
#     results: dict,
#     change: dict,
#     node_id: str,
#     node: dict,
#     impact: str,
#     severity: str,
#     evidence: str,
#     dependency_kind: str = "direct",
# ):
#     key = (change["change_id"], node_id)

#     row = {
#         "change_id": change["change_id"],
#         "change_type": change["change_type"],
#         "object": get_node_name(node, node_id),
#         "object_type": get_node_type(node),
#         "impact": impact,
#         "severity": severity,
#         "proposed_fix": proposed_fix(change),
#         "evidence": evidence,
#         "node_id": node_id,
#         "dependency_kind": dependency_kind,
#     }

#     if key not in results:
#         results[key] = row
#         return

#     current = results[key]

#     if impact_rank(impact) > impact_rank(current["impact"]):
#         current["impact"] = impact

#     if severity_rank(severity) > severity_rank(current["severity"]):
#         current["severity"] = severity

#     if evidence and evidence not in current["evidence"]:
#         current["evidence"] += "; " + evidence


# # ============================================================
# # 8. COLUMN DEPENDENCY MAPPING
# # ============================================================

# def map_output_columns(
#     edge: dict,
#     input_column: str,
# ) -> tuple[set[str], str]:

#     dependencies = get_dependencies(edge)
#     outputs = set()

#     for output_column, input_columns in dependencies.items():
#         if input_column in input_columns:
#             outputs.add(output_column)

#     join_columns = get_column_set(edge, "join_columns")

#     if input_column in join_columns:
#         return outputs, "join_key"

#     if outputs:
#         for output_column in outputs:
#             inputs = dependencies[output_column]

#             # A calculated output depending on multiple columns, or
#             # a differently named output, is treated as derived.
#             if (
#                 len(inputs) > 1
#                 or output_column != input_column
#             ):
#                 return outputs, "derived"

#         return outputs, "direct"

#     # Fallback for edges with explicit column lists but incomplete
#     # column_dependencies metadata.
#     explicit_columns = get_column_set(
#         edge,
#         "selected_columns",
#         "referenced_columns",
#         "columns",
#         "source_columns",
#         "input_columns",
#     )

#     if input_column in explicit_columns:
#         return {input_column}, "direct"

#     return set(), ""


# def edge_mentions_column(edge: dict, column: str) -> bool:
#     columns = get_column_set(
#         edge,
#         "selected_columns",
#         "referenced_columns",
#         "columns",
#         "source_columns",
#         "input_columns",
#         "join_columns",
#     )

#     if column in columns:
#         return True

#     # Some ingestion edges expose their SQL/config evidence as text.
#     evidence = norm(edge.get("evidence"))

#     return bool(
#         evidence
#         and re.search(
#             rf"(?<![a-z0-9_]){re.escape(norm(column))}(?![a-z0-9_])",
#             evidence,
#         )
#     )


# # ============================================================
# # 9. REPORT IMPACT PROPAGATION
# # ============================================================

# def add_containing_reports(
#     change: dict,
#     visual_id: str,
#     nodes: dict,
#     incoming: dict,
#     results: dict,
#     ingestion_context: dict | None = None
# ):
#     """
#     contains_visual edges are commonly directed:
#         report -> visual

#     When a visual is affected, mark its containing report too.
#     """

#     for edge in incoming.get(visual_id, []):
#         if get_relationship(edge) not in {
#             "contains_visual",
#             "has_visual",
#         }:
#             continue

#         report_id = str(edge.get("source") or "")

#         if report_id not in nodes:
#             continue

#         impact, severity = classify_change(change, ingestion_context=ingestion_context)

#         add_impact(
#             results,
#             change,
#             report_id,
#             nodes[report_id],
#             impact,
#             severity,
#             "Report contains a visual affected by the changed column.",
#         )


# # ============================================================
# # 10. MAIN COLUMN-LEVEL TRAVERSAL
# # ============================================================

# def analyse_one_change(
#     change: dict,
#     nodes: dict,
#     outgoing: dict,
#     incoming: dict,
#     results: dict,
# ):
#     change_type = change["change_type"]

#     # Additions do not invalidate existing dependencies.
#     if change_type == "add":
#         return

#     # Compatible widening is not considered an impact in this baseline.
#     if (
#         change_type == "type_change"
#         and is_compatible_widening(change)
#     ):
#         return

#     column = change.get("old_column") or change.get("column")

#     if not column:
#         return

#     source_id = resolve_source(change["source"], nodes)

#     if not source_id:
#         # If a critical change occurs on an unmapped source, warn rather than silently claiming safe
#         if change["change_type"] in {"drop", "type_change", "rename"}:
#             add_impact(
#                 results,
#                 change,
#                 f"unmapped:{change['source']}",
#                 {"name": change["source"], "type": "source_table"},
#                 "DEGRADES",
#                 "MEDIUM",
#                 f"Source '{change['source']}' is not registered in the project lineage. Downstream impact cannot be verified.",
#                 dependency_kind="unmapped_source",
#             )
#         return

#     source_metadata = nodes[source_id].get("metadata", {})

#     ingestion_context = {
#         "reader": source_metadata.get("reader"),
#         "mode": source_metadata.get("mode"),
#         "schema_file": source_metadata.get("schema_file"),
#         "has_explicit_schema": source_metadata.get(
#             "has_explicit_schema",
#             bool(source_metadata.get("schema_file")),
#         ),
#     }

#     # Queue state: node ID, current column, dependency kind.
#     queue = deque([(source_id, column, "direct")])
#     visited = set()
#     impacted_visuals = set()

#     while queue:
#         current_id, current_column, previous_kind = queue.popleft()

#         state = (current_id, current_column)

#         if state in visited:
#             continue

#         visited.add(state)

#         for edge in outgoing.get(current_id, []):
#             relationship = get_relationship(edge)
#             target_id = str(edge.get("target") or "")

#             if target_id not in nodes:
#                 continue

#             target_node = nodes[target_id]

#             # ------------------------------------------------
#             # SOURCE -> BRONZE ingestion
#             # ------------------------------------------------
#             if relationship == "ingested_to":
#                 selected = get_column_set(
#                     edge,
#                     "selected_columns",
#                     "columns",
#                     "referenced_columns",
#                 )

#                 # If the ingestion edge has an explicit projection,
#                 # only follow the changed column when selected.
#                 if selected and current_column not in selected:
#                     continue

#                 # If the edge has no column metadata, follow it
#                 # conservatively rather than silently missing the impact.
#                 if (
#                     not selected
#                     and edge.get("evidence")
#                     and not edge_mentions_column(edge, current_column)
#                 ):
#                     # No explicit evidence either: retain the path because
#                     # the ingestion may use SELECT *.
#                     pass

#                 impact, severity = classify_change(
#                     change, previous_kind, ingestion_context
#                 )

#                 add_impact(
#                     results,
#                     change,
#                     target_id,
#                     target_node,
#                     impact,
#                     severity,
#                     f"Ingestion dependency from '{change['source']}' "
#                     f"carries column '{current_column}'.",
#                     previous_kind,
#                 )

#                 queue.append((target_id, current_column, previous_kind))
#                 continue

#             # ------------------------------------------------
#             # TABLE -> TABLE transformation
#             # ------------------------------------------------
#             if relationship == "transformed_to":
#                 outputs, dependency_kind = map_output_columns(
#                     edge, current_column
#                 )

#                 if not outputs:
#                     continue

#                 impact, severity = classify_change(
#                     change, dependency_kind, ingestion_context
#                 )

#                 add_impact(
#                     results,
#                     change,
#                     target_id,
#                     target_node,
#                     impact,
#                     severity,
#                     (
#                         f"Column '{current_column}' contributes to "
#                         f"{', '.join(sorted(outputs))}."
#                     ),
#                     dependency_kind,
#                 )

#                 for output_column in outputs:
#                     queue.append(
#                         (target_id, output_column, dependency_kind)
#                     )

#                 continue

#             # ------------------------------------------------
#             # TABLE -> NOTEBOOK read dependency
#             # ------------------------------------------------
#             if relationship == "read_by":
#                 if not edge_mentions_column(edge, current_column):
#                     continue

#                 impact, severity = classify_change(
#                     change, previous_kind, ingestion_context
#                 )

#                 add_impact(
#                     results,
#                     change,
#                     target_id,
#                     target_node,
#                     impact,
#                     severity,
#                     f"Notebook reads or references '{current_column}'.",
#                     previous_kind,
#                 )

#                 continue

#             # ------------------------------------------------
#             # GOLD TABLE -> SEMANTIC MODEL
#             # ------------------------------------------------
#             if relationship == "modelled_as":
#                 outputs, dependency_kind = map_output_columns(
#                     edge, current_column
#                 )

#                 if not outputs:
#                     continue

#                 impact, severity = classify_change(
#                     change, dependency_kind, ingestion_context
#                 )

#                 add_impact(
#                     results,
#                     change,
#                     target_id,
#                     target_node,
#                     impact,
#                     severity,
#                     f"Semantic model exposes '{current_column}'.",
#                     dependency_kind,
#                 )

#                 for output_column in outputs:
#                     queue.append(
#                         (target_id, output_column, dependency_kind)
#                     )

#                 continue

#             # ------------------------------------------------
#             # SEMANTIC COLUMN -> MEASURE
#             # ------------------------------------------------
#             if relationship == "column_used_by_measure":
#                 edge_column = str(edge.get("column") or "")

#                 if edge_column != current_column:
#                     continue

#                 impact, severity = classify_change(
#                     change, previous_kind, ingestion_context
#                 )

#                 add_impact(
#                     results,
#                     change,
#                     target_id,
#                     target_node,
#                     impact,
#                     severity,
#                     f"Measure directly uses semantic column '{current_column}'.",
#                 )

#                 queue.append((target_id, current_column, "measure"))
#                 continue

#             # ------------------------------------------------
#             # SEMANTIC COLUMN -> VISUAL
#             # ------------------------------------------------
#             if relationship == "column_used_by_visual":
#                 edge_column = str(edge.get("column") or "")

#                 if edge_column != current_column:
#                     continue

#                 impact, severity = classify_change(
#                     change, previous_kind, ingestion_context
#                 )

#                 add_impact(
#                     results,
#                     change,
#                     target_id,
#                     target_node,
#                     impact,
#                     severity,
#                     f"Visual directly uses semantic column '{current_column}'.",
#                 )

#                 impacted_visuals.add(target_id)
#                 continue

#             # ------------------------------------------------
#             # MEASURE -> VISUAL
#             # ------------------------------------------------
#             if relationship in {
#                 "measure_dependency",
#                 "used_by_visual",
#                 "measure_used_by_visual",
#             }:
#                 if previous_kind != "measure":
#                     continue

#                 impact, severity = classify_change(
#                     change, previous_kind, ingestion_context
#                 )

#                 add_impact(
#                     results,
#                     change,
#                     target_id,
#                     target_node,
#                     impact,
#                     severity,
#                     "Visual depends on an impacted measure.",
#                 )

#                 impacted_visuals.add(target_id)
#                 continue

#     # Reports are affected only when a particular visual is affected.
#     for visual_id in impacted_visuals:
#         add_containing_reports(
#             change,
#             visual_id,
#             nodes,
#             incoming,
#             results,
#         )


# # ============================================================
# # 11. PUBLIC API
# # ============================================================

# def build_impact_report(schema_changes: Any, lineage: dict) -> dict:
#     changes = normalise_changes(schema_changes)

#     nodes, edges, outgoing, incoming = build_graph(lineage)

#     results = {}

#     for change in changes:
#         analyse_one_change(
#             change,
#             nodes,
#             outgoing,
#             incoming,
#             results,
#         )

#     impact_rows = list(results.values())

#     impact_rows.sort(
#         key=lambda row: (
#             row["change_id"],
#             row["object_type"],
#             row["object"],
#         )
#     )

#     summaries = []

#     for change in changes:
#         rows = [
#             row for row in impact_rows
#             if row["change_id"] == change["change_id"]
#         ]

#         if not rows:
#             overall_impact = "NO IMPACT"
#             overall_severity = "NONE"
#         else:
#             overall_impact = max(
#                 (row["impact"] for row in rows),
#                 key=impact_rank,
#             )

#             overall_severity = max(
#                 (row["severity"] for row in rows),
#                 key=severity_rank,
#             )

#         if overall_impact == "BREAKS":
#             decision = "HOLD THE LOAD"
#         elif overall_impact == "DEGRADES":
#             decision = "SAFE WITH WARNING"
#         else:
#             decision = "SAFE TO LOAD"

#         summaries.append({
#             "change_id": change["change_id"],
#             "source": change["source"],
#             "change_type": change["change_type"],
#             "column_before": change.get("old_column"),
#             "column_after": change.get("new_column"),
#             "impact": overall_impact,
#             "severity": overall_severity,
#             "decision": decision,
#             "affected_object_count": len(rows),
#         })

#     return {
#         "summary": {
#             "total_changes": len(changes),
#             "total_impacted_objects": len(impact_rows),
#             "breaks": sum(
#                 item["impact"] == "BREAKS"
#                 for item in summaries
#             ),
#             "degrades": sum(
#                 item["impact"] == "DEGRADES"
#                 for item in summaries
#             ),
#             "no_impact": sum(
#                 item["impact"] == "NO IMPACT"
#                 for item in summaries
#             ),
#         },
#         "change_summaries": summaries,
#         "impacts": impact_rows,
#     }

# def analyze_impacts(schema_changes: Any, lineage: dict) -> list[dict]:
#     """
#     Backward-compatible API.

#     Existing tests expect analyze_impacts() to return a list of
#     impact rows, with lowercase impact and severity values.
#     """

#     report = build_impact_report(schema_changes, lineage)

#     rows = [
#         dict(row)
#         for row in report["impacts"]
#     ]

#     # Return one explicit NO IMPACT row for changes that do not
#     # affect any downstream object. This preserves the previous API.
#     if not rows:
#         changes = normalise_changes(schema_changes)

#         for change in changes:
#             rows.append({
#                 "change_id": change["change_id"],
#                 "change_type": change["change_type"],
#                 "object": change["source"],
#                 "object_type": "source_table",
#                 "impact": "no impact",
#                 "severity": "none",
#                 "proposed_fix": proposed_fix(change),
#                 "evidence": "No dependent downstream column was identified.",
#                 "node_id": change["source"],
#                 "dependency_kind": "none",
#             })

#     # Existing tests expect lowercase values.
#     for row in rows:
#         row["impact"] = norm(row["impact"])
#         row["severity"] = norm(row["severity"])

#         if row["impact"] == "breaks":
#             row["decision"] = "HOLD THE LOAD"

#         elif row["impact"] == "degrades":
#             row["decision"] = "SAFE WITH WARNING"

#         else:
#             row["decision"] = "SAFE TO LOAD"

#     return rows

# def save_impact_analysis(
#     analysis: dict,
#     output_path: str | Path,
# ):
#     output_path = Path(output_path)
#     output_path.parent.mkdir(parents=True, exist_ok=True)

#     with output_path.open("w", encoding="utf-8") as file:
#         json.dump(
#             analysis,
#             file,
#             indent=2,
#             ensure_ascii=False,
#         )


# # ============================================================
# # 12. COMMAND LINE
# # ============================================================

# def main():
#     parser = argparse.ArgumentParser(
#         description="Column-level schema drift impact analysis"
#     )

#     parser.add_argument(
#         "--changes",
#         default="outputs/schema_diff.json",
#     )

#     parser.add_argument(
#         "--lineage",
#         default="outputs/lineage.json",
#     )

#     parser.add_argument(
#         "--output",
#         default="outputs/impact_analysis.json",
#     )

#     args = parser.parse_args()

#     changes_path = Path(args.changes)
#     lineage_path = Path(args.lineage)

#     if not changes_path.exists():
#         raise FileNotFoundError(
#             f"Schema diff not found: {changes_path}"
#         )

#     if not lineage_path.exists():
#         raise FileNotFoundError(
#             f"Lineage not found: {lineage_path}"
#         )

#     with changes_path.open("r", encoding="utf-8") as file:
#         schema_changes = json.load(file)

#     with lineage_path.open("r", encoding="utf-8") as file:
#         lineage = json.load(file)

#     analysis = build_impact_report(schema_changes, lineage)

#     save_impact_analysis(analysis, args.output)

#     print("\nSCHEMA DRIFT IMPACT ANALYSIS")
#     print("=" * 65)

#     print(f"Total changes:       {analysis['summary']['total_changes']}")
#     print(f"Impacted objects:    {analysis['summary']['total_impacted_objects']}")
#     print(f"Breaking changes:    {analysis['summary']['breaks']}")
#     print(f"Degrading changes:   {analysis['summary']['degrades']}")
#     print(f"No-impact changes:   {analysis['summary']['no_impact']}")

#     print("\nCHANGE-WISE DECISIONS")
#     print("-" * 65)

#     for item in analysis["change_summaries"]:
#         print(
#             f"{item['change_id']} | "
#             f"{item['column_before']} -> {item['column_after']} | "
#             f"{item['impact']} | "
#             f"{item['severity']} | "
#             f"{item['decision']} | "
#             f"Objects: {item['affected_object_count']}"
#         )

#     print("\nIMPACTED OBJECTS")
#     print("-" * 65)

#     for item in analysis["impacts"]:
#         print(
#             f"{item['change_id']} | "
#             f"{item['object']} | "
#             f"{item['impact']} | "
#             f"{item['evidence']}"
#         )

#     print(f"\nSaved: {args.output}")


# if __name__ == "__main__":
#     main()


"""
Schema Drift Impact Analyzer - Impact Engine
=============================================

Uses the actual schema_diff.json format:
[
    {
        "change_id": "SC01",
        "source": "crm.customers",
        "change_type": "rename",
        "column_before": "email",
        "column_after": "email_address",
        "description": "email -> email_address"
    }
]

Uses column-level lineage:
- transformed_to
- read_by
- ingested_to
- modelled_as
- column_used_by_measure
- column_used_by_visual
- measure_dependency
- used_by_visual
- contains_visual

The engine deliberately avoids generic graph traversal.
Only verified column dependencies are propagated.
"""

from __future__ import annotations
import graphviz
import pandas as pd
import streamlit as st
import os
import argparse
import json
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Any


# ============================================================
# 1. NORMALISATION
# ============================================================

def norm(value: Any) -> str:
    return str(value or "").strip().lower()


def canonical_change_type(value: Any) -> str:
    value = norm(value).replace("-", "_").replace(" ", "_")

    aliases = {
        "added": "add",
        "column_added": "add",
        "add_column": "add",
        "dropped": "drop",
        "column_dropped": "drop",
        "drop_column": "drop",
        "renamed": "rename",
        "column_renamed": "rename",
        "typechange": "type_change",
        "datatype_change": "type_change",
        "data_type_change": "type_change",
        "column_type_changed": "type_change",
        "modify_type": "type_change",
    }

    return aliases.get(value, value)


def normalise_change(raw: dict) -> dict:
    """
    Convert the real schema-diff fields into a consistent internal format.
    """

    change_type = canonical_change_type(raw.get("change_type"))

    column_before = (
        raw.get("column_before")
        or raw.get("old_column")
        or raw.get("previous_column")
    )

    column_after = (
        raw.get("column_after")
        or raw.get("new_column")
        or raw.get("target_column")
    )

    description = str(
        raw.get("description")
        or raw.get("detail")
        or ""
    )

    # Recover column names from descriptions if necessary.
    if not column_before and change_type in {"rename", "drop", "type_change"}:
        match = re.search(
            r"([A-Za-z_][\w]*)\s*(?:->|â†’|dropped|:)",
            description,
            flags=re.IGNORECASE,
        )
        if match:
            column_before = match.group(1)

    if not column_after and change_type == "rename":
        match = re.search(
            r"(?:->|â†’)\s*([A-Za-z_][\w]*)",
            description,
        )
        if match:
            column_after = match.group(1)

    column = column_before or column_after

    return {
        **raw,
        "change_id": str(raw.get("change_id") or "UNKNOWN"),
        "source": str(raw.get("source") or raw.get("source_table") or ""),
        "change_type": change_type,
        "column": column,
        "old_column": column_before,
        "new_column": column_after,
        "type_before": raw.get("type_before"),
        "type_after": raw.get("type_after"),
        "description": description,
    }


def normalise_changes(data: Any) -> list[dict]:
    if isinstance(data, list):
        raw_changes = data
    elif isinstance(data, dict):
        raw_changes = (
            data.get("changes")
            or data.get("schema_changes")
            or data.get("detected_changes")
            or []
        )
    else:
        raw_changes = []

    return [
        normalise_change(item)
        for item in raw_changes
        if isinstance(item, dict)
    ]


# ============================================================
# 2. LINEAGE HELPERS
# ============================================================

def get_node_id(node: dict) -> str:
    return str(
        node.get("id")
        or node.get("node_id")
        or node.get("name")
        or ""
    )


def get_node_name(node: dict, fallback: str) -> str:
    return str(
        node.get("name")
        or node.get("object")
        or node.get("table")
        or fallback
    )


def get_node_type(node: dict) -> str:
    return str(
        node.get("type")
        or node.get("object_type")
        or node.get("node_type")
        or "unknown"
    )


def get_relationship(edge: dict) -> str:
    return norm(
        edge.get("relationship")
        or edge.get("type")
        or edge.get("label")
    )


def get_column_set(edge: dict, *field_names: str) -> set[str]:
    result = set()

    for field in field_names:
        value = edge.get(field)

        if isinstance(value, str):
            result.add(value.strip())

        elif isinstance(value, list):
            result.update(
                str(item).strip()
                for item in value
                if item is not None
            )

        elif isinstance(value, dict):
            result.update(str(item).strip() for item in value)

    return {item for item in result if item}


def get_dependencies(edge: dict) -> dict[str, list[str]]:
    """
    The lineage extractor stores dependencies as:

        output_column: [input_column_1, input_column_2]

    Example:
        cost_amount: [cost_price, quantity]
    """

    raw = edge.get("column_dependencies") or {}

    if not isinstance(raw, dict):
        return {}

    result = {}

    for output_column, input_columns in raw.items():
        if isinstance(input_columns, str):
            input_columns = [input_columns]

        if not isinstance(input_columns, list):
            continue

        result[str(output_column)] = [
            str(item)
            for item in input_columns
            if item is not None
        ]

    return result


def build_graph(lineage: dict):
    raw_nodes = lineage.get("nodes", [])
    raw_edges = lineage.get("edges", [])

    if isinstance(raw_nodes, dict):
        nodes = {
            str(key): (
                value if isinstance(value, dict)
                else {"name": str(value)}
            )
            for key, value in raw_nodes.items()
        }
    else:
        nodes = {}

        for node in raw_nodes:
            if isinstance(node, dict):
                node_id = get_node_id(node)
                if node_id:
                    nodes[node_id] = node

    edges = [
        edge for edge in raw_edges
        if isinstance(edge, dict)
    ]

    outgoing = defaultdict(list)
    incoming = defaultdict(list)

    for edge in edges:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")

        if source and target:
            outgoing[source].append(edge)
            incoming[target].append(edge)

    return nodes, edges, outgoing, incoming


# ============================================================
# 3. SOURCE TABLE RESOLUTION
# ============================================================

def source_candidates(source: str) -> list[str]:
    """
    Example:
        crm.customers
        -> source_table:crm.customers
        -> lakehouse_table:bronze.crm_customers

    Supports source nodes and Bronze table fallback.
    """

    source = source.strip()
    candidates = [
        f"source_table:{source}",
        f"source:{source}",
        source,
    ]

    if "." in source:
        system, table = source.split(".", 1)
        bronze_table = f"bronze.{system}_{table}"

        candidates.extend([
            f"lakehouse_table:{bronze_table}",
            bronze_table,
        ])

    return candidates


def resolve_source(source: str, nodes: dict) -> str | None:
    for candidate in source_candidates(source):
        if candidate in nodes:
            return candidate

    source_normalised = norm(source)

    # Search by exact suffix or source-table identity.
    for node_id, node in nodes.items():
        node_id_normalised = norm(node_id)
        node_name = norm(get_node_name(node, node_id))

        if (
            node_id_normalised.endswith(":" + source_normalised)
            or node_name == source_normalised
        ):
            return node_id

    # Last-resort Bronze table match.
    if "." in source:
        system, table = source.split(".", 1)
        expected = norm(f"bronze.{system}_{table}")

        for node_id in nodes:
            if expected in norm(node_id):
                return node_id

    return None


# ============================================================
# 4. TYPE COMPATIBILITY
# ============================================================

def decimal_shape(data_type: Any):
    if not data_type:
        return None

    match = re.search(
        r"decimal\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)",
        str(data_type),
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    precision = int(match.group(1))
    scale = int(match.group(2))

    return precision, scale


def is_compatible_widening(change: dict) -> bool:
    before = decimal_shape(change.get("type_before"))
    after = decimal_shape(change.get("type_after"))

    if not before or not after:
        return False

    before_precision, before_scale = before
    after_precision, after_scale = after

    before_integer_digits = before_precision - before_scale
    after_integer_digits = after_precision - after_scale

    return (
        after_scale >= before_scale
        and after_integer_digits >= before_integer_digits
    )


# ============================================================
# 5. IMPACT CLASSIFICATION
# ============================================================

def impact_rank(value: str) -> int:
    return {
        "NO IMPACT": 0,
        "DEGRADES": 1,
        "BREAKS": 2,
    }.get(value, 0)


def severity_rank(value: str) -> int:
    return {
        "NONE": 0,
        "LOW": 1,
        "MEDIUM": 2,
        "HIGH": 3,
        "CRITICAL": 4,
    }.get(value, 0)


def classify_change(
    change: dict,
    dependency_kind: str = "direct",
) -> tuple[str, str]:

    change_type = change["change_type"]

    # Adding a column does not break existing consumers unless a
    # specific downstream dependency is identified.
    if change_type == "add":
        return "NO IMPACT", "NONE"

    # Compatible decimal widening.
    if (
        change_type == "type_change"
        and is_compatible_widening(change)
    ):
        return "NO IMPACT", "NONE"

    if change_type == "type_change":
        before = norm(change.get("type_before"))
        after = norm(change.get("type_after"))

        # Boolean -> string may cause conversion or semantic degradation.
        if before in {"boolean", "bool"} and after in {
            "string", "varchar", "text"
        }:
            return "DEGRADES", "MEDIUM"

        # Incompatible arithmetic types, such as decimal -> varchar.
        if dependency_kind == "derived":
            return "BREAKS", "HIGH"

        return "DEGRADES", "MEDIUM"

    if change_type == "drop":
        return "BREAKS", "HIGH"

    if change_type == "rename":
        # Evidence-backed exception: a JSON PERMISSIVE reader with an
        # explicit schema can retain the old declared field as null when
        # the upstream producer renames it. Downstream logic may continue,
        # but values are degraded. This is deliberately not a global rule
        # for every rename.
        if change.get("_permissive_schema_ingestion") is True:
            return "DEGRADES", "MEDIUM"

        # Renamed join keys can cause missing matches.
        if dependency_kind == "join_key":
            return "DEGRADES", "MEDIUM"

    return "BREAKS", "HIGH"


# ============================================================
# 6. PROPOSED FIX
# ============================================================

def proposed_fix(change: dict) -> str:
    kind = change["change_type"]
    old = change.get("old_column")
    new = change.get("new_column")

    if kind == "rename":
        return (
            f"Update references from '{old}' to '{new}' in the "
            "affected ingestion, notebook and downstream model."
        )

    if kind == "drop":
        return (
            f"Restore '{old}' or remove/update its downstream references "
            "before allowing the load."
        )

    if kind == "type_change":
        return (
            f"Validate the new type of '{old}'. Add an explicit cast or "
            "update dependent calculations where necessary."
        )

    if kind == "add":
        return (
            f"Optionally map the new column '{new}' into downstream models."
        )

    return "Review the dependency and validate the affected pipeline."


# ============================================================
# 7. RESULT COLLECTION
# ============================================================

def add_impact(
    results: dict,
    change: dict,
    node_id: str,
    node: dict,
    impact: str,
    severity: str,
    evidence: str,
    dependency_kind: str = "direct",
):
    key = (change["change_id"], node_id)

    row = {
        "change_id": change["change_id"],
        "change_type": change["change_type"],
        "object": get_node_name(node, node_id),
        "object_type": get_node_type(node),
        "impact": impact,
        "severity": severity,
        "proposed_fix": proposed_fix(change),
        "evidence": evidence,
        "node_id": node_id,
        "dependency_kind": dependency_kind,
    }

    if key not in results:
        results[key] = row
        return

    current = results[key]

    if impact_rank(impact) > impact_rank(current["impact"]):
        current["impact"] = impact

    if severity_rank(severity) > severity_rank(current["severity"]):
        current["severity"] = severity

    if evidence and evidence not in current["evidence"]:
        current["evidence"] += "; " + evidence


# ============================================================
# 8. COLUMN DEPENDENCY MAPPING
# ============================================================

def map_output_columns(
    edge: dict,
    input_column: str,
) -> tuple[set[str], str]:

    dependencies = get_dependencies(edge)
    outputs = set()

    for output_column, input_columns in dependencies.items():
        if input_column in input_columns:
            outputs.add(output_column)

    join_columns = get_column_set(edge, "join_columns")

    if input_column in join_columns:
        return outputs, "join_key"

    if outputs:
        for output_column in outputs:
            inputs = dependencies[output_column]

            # A calculated output depending on multiple columns, or
            # a differently named output, is treated as derived.
            if (
                len(inputs) > 1
                or output_column != input_column
            ):
                return outputs, "derived"

        return outputs, "direct"

    # Fallback for edges with explicit column lists but incomplete
    # column_dependencies metadata.
    explicit_columns = get_column_set(
        edge,
        "selected_columns",
        "referenced_columns",
        "columns",
        "source_columns",
        "input_columns",
    )

    if input_column in explicit_columns:
        return {input_column}, "direct"

    return set(), ""


def edge_mentions_column(edge: dict, column: str) -> bool:
    columns = get_column_set(
        edge,
        "selected_columns",
        "referenced_columns",
        "columns",
        "source_columns",
        "input_columns",
        "join_columns",
    )

    if column in columns:
        return True

    # Some ingestion edges expose their SQL/config evidence as text.
    evidence = norm(edge.get("evidence"))

    return bool(
        evidence
        and re.search(
            rf"(?<![a-z0-9_]){re.escape(norm(column))}(?![a-z0-9_])",
            evidence,
        )
    )


def is_permissive_schema_ingestion(edge: dict, column: str) -> bool:
    """True only when metadata proves a JSON PERMISSIVE reader has an explicit schema.

    With an explicit Spark JSON schema in PERMISSIVE mode, a renamed source
    field can be absent from incoming records while the declared old field
    remains present as null. This is a degradation, not automatically a
    structural ingestion failure.
    """
    reader = norm(edge.get("reader"))
    mode = norm(edge.get("mode"))
    schema_available = edge.get("schema_available") is True
    schema_columns = get_column_set(edge, "schema_columns")

    return (
        reader == "json"
        and mode == "permissive"
        and schema_available
        and column in schema_columns
    )


# ============================================================
# 9. REPORT IMPACT PROPAGATION
# ============================================================

def add_containing_reports(
    change: dict,
    visual_id: str,
    nodes: dict,
    incoming: dict,
    results: dict,
):
    """
    contains_visual edges are commonly directed:
        report -> visual

    When a visual is affected, mark its containing report too.
    """

    for edge in incoming.get(visual_id, []):
        if get_relationship(edge) not in {
            "contains_visual",
            "has_visual",
        }:
            continue

        report_id = str(edge.get("source") or "")

        if report_id not in nodes:
            continue

        impact, severity = classify_change(change)

        add_impact(
            results,
            change,
            report_id,
            nodes[report_id],
            impact,
            severity,
            "Report contains a visual affected by the changed column.",
        )


# ============================================================
# 10. MAIN COLUMN-LEVEL TRAVERSAL
# ============================================================

def analyse_one_change(
    change: dict,
    nodes: dict,
    outgoing: dict,
    incoming: dict,
    results: dict,
):
    change_type = change["change_type"]

    # Additions do not invalidate existing dependencies.
    if change_type == "add":
        return

    # Compatible widening is not considered an impact in this baseline.
    if (
        change_type == "type_change"
        and is_compatible_widening(change)
    ):
        return

    column = change.get("old_column") or change.get("column")

    if not column:
        return

    source_id = resolve_source(change["source"], nodes)

    if not source_id:
        print(
            f"WARNING: Source '{change['source']}' "
            f"could not be resolved for {change['change_id']}"
        )
        return

    # Mark this change as degradation-only only when the source-to-Bronze
    # edge proves JSON + PERMISSIVE + a readable explicit schema containing
    # the old column. JDBC/SELECT */overwrite-schema paths remain unchanged.
    for ingestion_edge in outgoing.get(source_id, []):
        if (
            get_relationship(ingestion_edge) == "ingested_to"
            and is_permissive_schema_ingestion(ingestion_edge, column)
        ):
            change["_permissive_schema_ingestion"] = True
            break

    # Queue state: node ID, current column, dependency kind.
    queue = deque([(source_id, column, "direct")])
    visited = set()
    impacted_visuals = set()

    while queue:
        current_id, current_column, previous_kind = queue.popleft()

        state = (current_id, current_column)

        if state in visited:
            continue

        visited.add(state)

        for edge in outgoing.get(current_id, []):
            relationship = get_relationship(edge)
            target_id = str(edge.get("target") or "")

            if target_id not in nodes:
                continue

            target_node = nodes[target_id]

            # ------------------------------------------------
            # SOURCE -> BRONZE ingestion
            # ------------------------------------------------
            if relationship == "ingested_to":
                selected = get_column_set(
                    edge,
                    "selected_columns",
                    "columns",
                    "referenced_columns",
                )

                # If the ingestion edge has an explicit projection,
                # only follow the changed column when selected.
                if selected and current_column not in selected:
                    continue

                # If the edge has no column metadata, follow it
                # conservatively rather than silently missing the impact.
                if (
                    not selected
                    and edge.get("evidence")
                    and not edge_mentions_column(edge, current_column)
                ):
                    # No explicit evidence either: retain the path because
                    # the ingestion may use SELECT *.
                    pass

                impact, severity = classify_change(
                    change, previous_kind
                )

                add_impact(
                    results,
                    change,
                    target_id,
                    target_node,
                    impact,
                    severity,
                    f"Ingestion dependency from '{change['source']}' "
                    f"carries column '{current_column}'.",
                    previous_kind,
                )

                queue.append((target_id, current_column, previous_kind))
                continue

            # ------------------------------------------------
            # TABLE -> TABLE transformation
            # ------------------------------------------------
            if relationship == "transformed_to":
                outputs, dependency_kind = map_output_columns(
                    edge, current_column
                )

                if not outputs:
                    continue

                impact, severity = classify_change(
                    change, dependency_kind
                )

                add_impact(
                    results,
                    change,
                    target_id,
                    target_node,
                    impact,
                    severity,
                    (
                        f"Column '{current_column}' contributes to "
                        f"{', '.join(sorted(outputs))}."
                    ),
                    dependency_kind,
                )

                for output_column in outputs:
                    queue.append(
                        (target_id, output_column, dependency_kind)
                    )

                continue

            # ------------------------------------------------
            # TABLE -> NOTEBOOK read dependency
            # ------------------------------------------------
            if relationship == "read_by":
                if not edge_mentions_column(edge, current_column):
                    continue

                impact, severity = classify_change(
                    change, previous_kind
                )

                add_impact(
                    results,
                    change,
                    target_id,
                    target_node,
                    impact,
                    severity,
                    f"Notebook reads or references '{current_column}'.",
                    previous_kind,
                )

                continue

            # ------------------------------------------------
            # GOLD TABLE -> SEMANTIC MODEL
            # ------------------------------------------------
            if relationship == "modelled_as":
                outputs, dependency_kind = map_output_columns(
                    edge, current_column
                )

                if not outputs:
                    continue

                impact, severity = classify_change(
                    change, dependency_kind
                )

                add_impact(
                    results,
                    change,
                    target_id,
                    target_node,
                    impact,
                    severity,
                    f"Semantic model exposes '{current_column}'.",
                    dependency_kind,
                )

                for output_column in outputs:
                    queue.append(
                        (target_id, output_column, dependency_kind)
                    )

                continue

            # ------------------------------------------------
            # SEMANTIC COLUMN -> MEASURE
            # ------------------------------------------------
            if relationship == "column_used_by_measure":
                edge_column = str(edge.get("column") or "")

                if edge_column != current_column:
                    continue

                impact, severity = classify_change(
                    change, previous_kind
                )

                add_impact(
                    results,
                    change,
                    target_id,
                    target_node,
                    impact,
                    severity,
                    f"Measure directly uses semantic column '{current_column}'.",
                )

                queue.append((target_id, current_column, "measure"))
                continue

            # ------------------------------------------------
            # SEMANTIC COLUMN -> VISUAL
            # ------------------------------------------------
            if relationship == "column_used_by_visual":
                edge_column = str(edge.get("column") or "")

                if edge_column != current_column:
                    continue

                impact, severity = classify_change(
                    change, previous_kind
                )

                add_impact(
                    results,
                    change,
                    target_id,
                    target_node,
                    impact,
                    severity,
                    f"Visual directly uses semantic column '{current_column}'.",
                )

                impacted_visuals.add(target_id)
                continue

            # ------------------------------------------------
            # MEASURE -> VISUAL
            # ------------------------------------------------
            if relationship in {
                "measure_dependency",
                "used_by_visual",
                "measure_used_by_visual",
            }:
                if previous_kind != "measure":
                    continue

                impact, severity = classify_change(
                    change, previous_kind
                )

                add_impact(
                    results,
                    change,
                    target_id,
                    target_node,
                    impact,
                    severity,
                    "Visual depends on an impacted measure.",
                )

                impacted_visuals.add(target_id)
                continue

    # Reports are affected only when a particular visual is affected.
    for visual_id in impacted_visuals:
        add_containing_reports(
            change,
            visual_id,
            nodes,
            incoming,
            results,
        )


# ============================================================
# 11. PUBLIC API
# ============================================================

def build_impact_report(schema_changes: Any, lineage: dict) -> dict:
    changes = normalise_changes(schema_changes)

    nodes, edges, outgoing, incoming = build_graph(lineage)

    results = {}

    for change in changes:
        analyse_one_change(
            change,
            nodes,
            outgoing,
            incoming,
            results,
        )

    impact_rows = list(results.values())

    impact_rows.sort(
        key=lambda row: (
            row["change_id"],
            row["object_type"],
            row["object"],
        )
    )

    summaries = []

    for change in changes:
        rows = [
            row for row in impact_rows
            if row["change_id"] == change["change_id"]
        ]

        if not rows:
            overall_impact = "NO IMPACT"
            overall_severity = "NONE"
        else:
            overall_impact = max(
                (row["impact"] for row in rows),
                key=impact_rank,
            )

            overall_severity = max(
                (row["severity"] for row in rows),
                key=severity_rank,
            )

        if overall_impact == "BREAKS":
            decision = "HOLD THE LOAD"
        elif overall_impact == "DEGRADES":
            decision = "SAFE WITH WARNING"
        else:
            decision = "SAFE TO LOAD"

        summaries.append({
            "change_id": change["change_id"],
            "source": change["source"],
            "change_type": change["change_type"],
            "column_before": change.get("old_column"),
            "column_after": change.get("new_column"),
            "impact": overall_impact,
            "severity": overall_severity,
            "decision": decision,
            "affected_object_count": len(rows),
        })

    return {
        "summary": {
            "total_changes": len(changes),
            "total_impacted_objects": len(impact_rows),
            "breaks": sum(
                item["impact"] == "BREAKS"
                for item in summaries
            ),
            "degrades": sum(
                item["impact"] == "DEGRADES"
                for item in summaries
            ),
            "no_impact": sum(
                item["impact"] == "NO IMPACT"
                for item in summaries
            ),
        },
        "change_summaries": summaries,
        "impacts": impact_rows,
    }

def analyze_impacts(schema_changes: Any, lineage: dict) -> list[dict]:
    """
    Backward-compatible API.

    Existing tests expect analyze_impacts() to return a list of
    impact rows, with lowercase impact and severity values.
    """

    report = build_impact_report(schema_changes, lineage)

    rows = [
        dict(row)
        for row in report["impacts"]
    ]

    # Return one explicit NO IMPACT row for changes that do not
    # affect any downstream object. This preserves the previous API.
    if not rows:
        changes = normalise_changes(schema_changes)

        for change in changes:
            rows.append({
                "change_id": change["change_id"],
                "change_type": change["change_type"],
                "object": change["source"],
                "object_type": "source_table",
                "impact": "no impact",
                "severity": "none",
                "proposed_fix": proposed_fix(change),
                "evidence": "No dependent downstream column was identified.",
                "node_id": change["source"],
                "dependency_kind": "none",
            })

    # Existing tests expect lowercase values.
    for row in rows:
        row["impact"] = norm(row["impact"])
        row["severity"] = norm(row["severity"])

        if row["impact"] == "breaks":
            row["decision"] = "HOLD THE LOAD"

        elif row["impact"] == "degrades":
            row["decision"] = "SAFE WITH WARNING"

        else:
            row["decision"] = "SAFE TO LOAD"

    return rows

def save_impact_analysis(
    analysis: dict,
    output_path: str | Path,
):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as file:
        json.dump(
            analysis,
            file,
            indent=2,
            ensure_ascii=False,
        )


# ============================================================
# 12. COMMAND LINE
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Column-level schema drift impact analysis"
    )

    parser.add_argument(
        "--changes",
        default="outputs/schema_diff.json",
    )

    parser.add_argument(
        "--lineage",
        default="outputs/lineage.json",
    )

    parser.add_argument(
        "--output",
        default="outputs/impact_analysis.json",
    )

    args = parser.parse_args()

    changes_path = Path(args.changes)
    lineage_path = Path(args.lineage)

    if not changes_path.exists():
        raise FileNotFoundError(
            f"Schema diff not found: {changes_path}"
        )

    if not lineage_path.exists():
        raise FileNotFoundError(
            f"Lineage not found: {lineage_path}"
        )

    with changes_path.open("r", encoding="utf-8") as file:
        schema_changes = json.load(file)

    with lineage_path.open("r", encoding="utf-8") as file:
        lineage = json.load(file)

    analysis = build_impact_report(schema_changes, lineage)

    save_impact_analysis(analysis, args.output)

    print("\nSCHEMA DRIFT IMPACT ANALYSIS")
    print("=" * 65)

    print(f"Total changes:       {analysis['summary']['total_changes']}")
    print(f"Impacted objects:    {analysis['summary']['total_impacted_objects']}")
    print(f"Breaking changes:    {analysis['summary']['breaks']}")
    print(f"Degrading changes:   {analysis['summary']['degrades']}")
    print(f"No-impact changes:   {analysis['summary']['no_impact']}")

    print("\nCHANGE-WISE DECISIONS")
    print("-" * 65)

    for item in analysis["change_summaries"]:
        print(
            f"{item['change_id']} | "
            f"{item['column_before']} -> {item['column_after']} | "
            f"{item['impact']} | "
            f"{item['severity']} | "
            f"{item['decision']} | "
            f"Objects: {item['affected_object_count']}"
        )

    print("\nIMPACTED OBJECTS")
    print("-" * 65)

    for item in analysis["impacts"]:
        print(
            f"{item['change_id']} | "
            f"{item['object']} | "
            f"{item['impact']} | "
            f"{item['evidence']}"
        )

    print(f"\nSaved: {args.output}")


if __name__ == "__main__":
    main()