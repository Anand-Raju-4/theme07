"""Deterministic lineage extraction for IBD 2.0 Theme 07.

Reads the supplied ingestion config, PySpark notebooks, pipeline JSON and
Power BI semantic-model metadata. Produces a graph-shaped dictionary with
nodes and evidence-backed edges. This is static analysis: it does not execute
notebooks or connect to Databricks/Power BI.

Public API:
    build_lineage(project_root) -> dict
    save_lineage(lineage, output_path) -> Path

The project_root is the starter-kit project directory containing config/,
notebooks/, pipelines/ and powerbi/.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Any


def load_json(path: str | Path) -> Any:
    """Load JSON using UTF-8."""
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _node_id(kind: str, name: str) -> str:
    return f"{kind}:{name}"


class _GraphBuilder:
    """Collect unique nodes and edges while retaining source evidence."""

    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    def add_node(self, kind: str, name: str, **metadata: Any) -> str:
        node_id = _node_id(kind, name)
        node = self.nodes.setdefault(
            node_id,
            {"id": node_id, "name": name, "type": kind, "metadata": {}},
        )
        for key, value in metadata.items():
            if value is not None:
                node["metadata"][key] = value
        return node_id

    def add_edge(
        self,
        source: str,
        target: str,
        relationship: str,
        evidence: str,
        **metadata: Any,
    ) -> None:
        key = (source, target, relationship, evidence)
        edge = self.edges.setdefault(
            key,
            {
                "source": source,
                "target": target,
                "relationship": relationship,
                "evidence": evidence,
            },
        )
        for name, value in metadata.items():
            if value is not None:
                edge[name] = value

    def result(self) -> dict[str, Any]:
        return {
            "nodes": sorted(self.nodes.values(), key=lambda item: item["id"]),
            "edges": sorted(
                self.edges.values(),
                key=lambda item: (
                    item["source"], item["target"],
                    item["relationship"], item["evidence"],
                ),
            ),
        }


def _literal_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None

def _literal_string_list(node: ast.AST) -> list[str]:
    """Extract a literal string or a list/tuple of literal strings."""
    value = _literal_string(node)
    if value is not None:
        return [value.split(".")[-1].strip("`[]\"")]
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        values = [_literal_string(item) for item in node.elts]
        return [value.split(".")[-1].strip("`[]\"") for value in values if value is not None]
    return []


def _expression_columns(node: ast.AST) -> set[str]:
    """Extract likely input-column references from a PySpark expression."""
    found: set[str] = set()

    def visit(current: ast.AST) -> None:
        if isinstance(current, ast.Constant) and isinstance(current.value, str):
            found.add(current.value.split(".")[-1])
            return
        if not isinstance(current, ast.Call):
            for child in ast.iter_child_nodes(current):
                visit(child)
            return
        attr = current.func.attr if isinstance(current.func, ast.Attribute) else ""
        name = current.func.id if isinstance(current.func, ast.Name) else attr
        if name == "lit":
            return
        if name == "col" and current.args:
            value = _literal_string(current.args[0])
            if value:
                found.add(value.split(".")[-1])
            return
        if name == "concat_ws":
            # First argument is the delimiter, not a column name.
            for arg in current.args[1:]:
                visit(arg)
            return
        for arg in current.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                found.add(arg.value.split(".")[-1])
            else:
                visit(arg)
        for keyword in current.keywords:
            visit(keyword.value)

    visit(node)
    return found


def _extract_notebook_facts(path: Path) -> dict[str, Any]:
    """Extract Spark reads/writes, join keys and input-to-output dependencies.

    This is static analysis. It handles common literal PySpark patterns, not
    arbitrary dynamically generated DataFrame expressions.
    """
    source = _read_text(path)
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise ValueError(f"Cannot parse notebook {path.name}: {exc}") from exc

    reads: list[dict[str, Any]] = []
    writes: list[dict[str, Any]] = []
    select_columns: set[str] = set()
    with_column_outputs: set[str] = set()
    expression_dependencies: dict[str, set[str]] = {}
    join_columns: set[str] = set()
    local_dataframe_columns: dict[str, set[str]] = {}
    referenced_columns: set[str] = set()

    # Infer local lookup DataFrame columns, e.g. regions = createDataFrame(..., [cols]).
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if not isinstance(value, ast.Call):
            continue
        attr = value.func.attr if isinstance(value.func, ast.Attribute) else ""
        if attr != "createDataFrame" or not value.args:
            continue
        columns = _literal_string_list(value.args[-1])
        if not columns:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                local_dataframe_columns[target.id] = set(columns)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        attr = func.attr if isinstance(func, ast.Attribute) else ""
        line = getattr(node, "lineno", None)

        if attr == "table" and node.args:
            table_name = _literal_string(node.args[0])
            if table_name:
                reads.append({"table": table_name, "line": line})
        elif attr == "saveAsTable" and node.args:
            table_name = _literal_string(node.args[0])
            if table_name:
                writes.append({"table": table_name, "line": line})
        elif attr == "select":
            for arg in node.args:
                select_columns.update(_literal_string_list(arg))
        elif attr == "col" and node.args:
            value = _literal_string(node.args[0])
            if value:
                referenced_columns.add(value.split(".")[-1])
        elif attr == "join":
            # PySpark join(other, on, how); on may be a string/list or keyword.
            if len(node.args) >= 2:
                keys = set(_literal_string_list(node.args[1]))
                join_columns.update(keys)
                referenced_columns.update(keys)
            for keyword in node.keywords:
                if keyword.arg == "on":
                    keys = set(_literal_string_list(keyword.value))
                    join_columns.update(keys)
                    referenced_columns.update(keys)
        elif attr == "withColumn" and len(node.args) >= 2:
            output_name = _literal_string(node.args[0])
            if output_name:
                output_name = output_name.split(".")[-1]
                with_column_outputs.add(output_name)
                dependencies = _expression_columns(node.args[1])
                if dependencies:
                    expression_dependencies.setdefault(output_name, set()).update(dependencies)
                    referenced_columns.update(dependencies)
        elif attr in {"filter", "where", "dropDuplicates", "orderBy", "groupBy"}:
            for arg in node.args:
                referenced_columns.update(_literal_string_list(arg))

    output_columns = set(select_columns) | set(with_column_outputs)
    lookup_columns: set[str] = set()
    for columns in local_dataframe_columns.values():
        lookup_columns.update(columns)

    column_dependencies: dict[str, list[str]] = {}
    for output in sorted(output_columns):
        if output in expression_dependencies:
            dependencies = expression_dependencies[output]
        elif output in lookup_columns and output not in join_columns:
            # A selected lookup-side attribute (e.g. region_name) is obtained
            # by matching the source-side join key (e.g. region_code).
            dependencies = set(join_columns)
        elif output in select_columns:
            dependencies = {output}
        else:
            dependencies = set()
        if dependencies:
            column_dependencies[output] = sorted(dependencies)

    referenced_columns.update(join_columns)
    return {
        "notebook": path.stem,
        "path": path.as_posix(),
        "reads": sorted(reads, key=lambda item: (item["table"], item["line"] or 0)),
        "writes": sorted(writes, key=lambda item: (item["table"], item["line"] or 0)),
        # Keep these legacy fields so the current impact engine remains compatible.
        "selected_columns": sorted(output_columns),
        "referenced_columns": sorted(referenced_columns),
        "join_columns": sorted(join_columns),
        "column_dependencies": column_dependencies,
        "source_text": source,
    }

def _sql_select_columns(query: str) -> list[str] | None:
    """Return explicitly selected SQL columns; None means SELECT * / unknown."""
    match = re.search(r"\bselect\s+(.*?)\s+from\b", query, flags=re.I | re.S)
    if not match:
        return None
    projection = match.group(1).strip()
    if projection == "*" or re.search(r"\b\w+\.\*", projection):
        return None
    columns = []
    for item in projection.split(","):
        # Remove aliases and qualifiers; retain the final identifier.
        item = re.split(r"\s+as\s+", item, flags=re.I)[0].strip()
        item = item.split(".")[-1].strip().strip("`[]\"")
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", item):
            columns.append(item)
    return sorted(set(columns))


def _extract_ingestion(
    root: Path,
    graph: _GraphBuilder,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    config_path = root / "config" / "ingest_config.json"
    config = load_json(config_path)
    source_configs: dict[str, dict[str, Any]] = {}
    source_to_target: dict[str, str] = {}

    for entry in config.get("sources", []):
        source = entry.get("source")
        target = entry.get("target")
        if not source or not target:
            continue

        source_configs[source] = entry
        source_to_target[source] = target
        source_id = graph.add_node("source_table", source, reader=entry.get("reader"))
        target_id = graph.add_node("lakehouse_table", target, layer="bronze")
        columns = _sql_select_columns(entry.get("query", "")) if entry.get("query") else None
        graph.add_edge(
            source_id,
            target_id,
            "ingested_to",
            f"config/ingest_config.json: source={source}; target={target}",
            notebook="nb01_bronze_ingest",
            selected_columns=columns,
            write_mode=entry.get("write_mode"),
        )

    return source_configs, source_to_target


def _extract_notebooks(
    root: Path,
    graph: _GraphBuilder,
) -> dict[str, dict[str, Any]]:
    notebook_dir = root / "notebooks"
    facts_by_name: dict[str, dict[str, Any]] = {}

    for path in sorted(notebook_dir.glob("*.py")):
        facts = _extract_notebook_facts(path)
        facts_by_name[facts["notebook"]] = facts
        notebook_id = graph.add_node(
            "notebook",
            facts["notebook"],
            path=facts["path"],
        )

        for read in facts["reads"]:
            table_id = graph.add_node("lakehouse_table", read["table"])
            graph.add_edge(
                table_id,
                notebook_id,
                "read_by",
                f"{path.name}:{read['line']} spark.table('{read['table']}')",
                columns=sorted(set(facts["referenced_columns"]) | set(facts["selected_columns"])),
                referenced_columns=facts["referenced_columns"],
                join_columns=facts["join_columns"],
            )

        for write in facts["writes"]:
            table_id = graph.add_node("lakehouse_table", write["table"])
            graph.add_edge(
                notebook_id,
                table_id,
                "writes_to",
                f"{path.name}:{write['line']} saveAsTable('{write['table']}')",
                columns=facts["selected_columns"],
                column_dependencies=facts["column_dependencies"],
            )

        # Link read tables directly to written tables. This is useful for
        # impact traversal while retaining notebook-level evidence edges.
        for read in facts["reads"]:
            for write in facts["writes"]:
                graph.add_edge(
                    _node_id("lakehouse_table", read["table"]),
                    _node_id("lakehouse_table", write["table"]),
                    "transformed_to",
                    f"{path.name}: reads {read['table']} and writes {write['table']}",
                    notebook=facts["notebook"],
                    referenced_columns=facts["referenced_columns"],
                    selected_columns=facts["selected_columns"],
                    join_columns=facts["join_columns"],
                    column_dependencies=facts["column_dependencies"],
                )

    return facts_by_name


def _extract_pipeline(root: Path, graph: _GraphBuilder) -> None:
    pipeline_dir = root / "pipelines"
    for path in sorted(pipeline_dir.glob("*.json")):
        pipeline = load_json(path)
        pipeline_name = pipeline.get("name", path.stem)
        pipeline_id = graph.add_node(
            "pipeline", pipeline_name, trigger=pipeline.get("trigger")
        )
        activity_ids: dict[str, str] = {}
        activities = pipeline.get("activities", [])

        for activity in activities:
            activity_name = activity.get("name")
            if not activity_name:
                continue
            activity_id = graph.add_node(
                "pipeline_activity",
                f"{pipeline_name}/{activity_name}",
                activity_name=activity_name,
                activity_type=activity.get("type", "Notebook"),
            )
            activity_ids[activity_name] = activity_id
            graph.add_edge(
                pipeline_id,
                activity_id,
                "contains_activity",
                f"{path.name}: activity '{activity_name}'",
            )

            notebook_name = activity.get("notebook")
            if notebook_name:
                notebook_id = graph.add_node("notebook", notebook_name)
                graph.add_edge(
                    activity_id,
                    notebook_id,
                    "executes",
                    f"{path.name}: activity '{activity_name}' executes notebook '{notebook_name}'",
                    params=activity.get("params", {}),
                )

            dataset = activity.get("dataset")
            if dataset:
                dataset_id = graph.add_node("semantic_model", dataset)
                graph.add_edge(
                    activity_id,
                    dataset_id,
                    "refreshes",
                    f"{path.name}: activity '{activity_name}' refreshes dataset '{dataset}'",
                )

        for activity in activities:
            target_name = activity.get("name")
            target_id = activity_ids.get(target_name)
            if not target_id:
                continue
            for dependency in activity.get("dependsOn", []):
                parent_name = dependency.get("activity") if isinstance(dependency, dict) else dependency
                parent_id = activity_ids.get(parent_name)
                if parent_id:
                    graph.add_edge(
                        parent_id,
                        target_id,
                        "pipeline_dependency",
                        f"{path.name}: '{target_name}' dependsOn '{parent_name}'",
                    )


def _measure_dependencies(expression: str) -> tuple[list[str], list[str]]:
    """Return (table.column references, measure references) from a DAX expression."""
    table_columns = sorted(set(re.findall(
        r"([A-Za-z_][A-Za-z0-9_]*)\[([A-Za-z_][A-Za-z0-9_ ]*)\]",
        expression,
    )))
    measures = sorted(set(re.findall(r"\[([A-Za-z_][A-Za-z0-9_ %]*)\]", expression)))
    measures = [name.strip() for name in measures if name.strip()]
    return [f"{table}[{column}]" for table, column in table_columns], measures


def _extract_powerbi(root: Path, graph: _GraphBuilder) -> None:
    model_dir = root / "powerbi"
    for path in sorted(model_dir.glob("*.json")):
        model = load_json(path)
        model_name = model.get("semantic_model", path.stem)
        model_id = graph.add_node(
            "semantic_model", model_name, workspace=model.get("workspace"),
            storage_mode=model.get("storage_mode"),
        )

        table_ids: dict[str, str] = {}
        for table in model.get("tables", []):
            table_name = table.get("name")
            source_name = table.get("source")
            if not table_name:
                continue
            table_id = graph.add_node(
                "semantic_table", table_name,
                source=source_name,
                columns=table.get("columns", []),
            )
            table_ids[table_name] = table_id
            if source_name:
                source_id = graph.add_node("lakehouse_table", source_name, layer="gold")
                graph.add_edge(
                    source_id,
                    table_id,
                    "modelled_as",
                    f"{path.name}: semantic table '{table_name}' sources '{source_name}'",
                    columns=table.get("columns", []),
                )
            graph.add_edge(
                table_id,
                model_id,
                "belongs_to_model",
                f"{path.name}: table '{table_name}' belongs to '{model_name}'",
            )

        measure_ids: dict[str, str] = {}
        for measure in model.get("measures", []):
            measure_name = measure.get("name")
            expression = measure.get("expression", "")
            if not measure_name:
                continue
            measure_id = graph.add_node(
                "measure", measure_name, expression=expression
            )
            measure_ids[measure_name] = measure_id
            graph.add_edge(
                measure_id,
                model_id,
                "defined_in",
                f"{path.name}: measure '{measure_name}'",
            )
            column_refs, measure_refs = _measure_dependencies(expression)
            for reference in column_refs:
                table_name = reference.split("[", 1)[0]
                if table_name in table_ids:
                    graph.add_edge(
                        table_ids[table_name], measure_id,
                        "column_used_by_measure",
                        f"{path.name}: {measure_name} expression references {reference}",
                        column=reference,
                    )
            for reference in measure_refs:
                if reference != measure_name and reference in measure_ids:
                    graph.add_edge(
                        measure_ids[reference], measure_id,
                        "measure_dependency",
                        f"{path.name}: {measure_name} expression references [{reference}]",
                    )

        for report in model.get("reports", []):
            report_name = report.get("name")
            if not report_name:
                continue
            report_id = graph.add_node(
                "report", report_name,
                owner=report.get("owner"),
                audience=report.get("audience"),
            )
            graph.add_edge(
                model_id,
                report_id,
                "serves_report",
                f"{path.name}: report '{report_name}' uses semantic model '{model_name}'",
            )

            for visual in report.get("visuals", []):
                visual_name = visual.get("title", "Untitled visual")
                visual_id = graph.add_node(
                    "report_visual",
                    f"{report_name}/{visual_name}",
                    report=report_name,
                    fields=visual.get("fields", []),
                )
                graph.add_edge(
                    report_id,
                    visual_id,
                    "contains_visual",
                    f"{path.name}: report '{report_name}' contains visual '{visual_name}'",
                )
                for field in visual.get("fields", []):
                    measure_match = re.fullmatch(r"\[([^\]]+)\]", field.strip())
                    if measure_match:
                        measure_name = measure_match.group(1).strip()
                        if measure_name in measure_ids:
                            graph.add_edge(
                                measure_ids[measure_name], visual_id,
                                "used_by_visual",
                                f"{path.name}: visual '{visual_name}' uses measure [{measure_name}]",
                            )
                        continue
                    column_match = re.fullmatch(
                        r"([A-Za-z_][A-Za-z0-9_]*)\[([^\]]+)\]",
                        field.strip(),
                    )
                    if column_match:
                        table_name, column_name = column_match.groups()
                        if table_name in table_ids:
                            graph.add_edge(
                                table_ids[table_name], visual_id,
                                "column_used_by_visual",
                                f"{path.name}: visual '{visual_name}' uses {field}",
                                column=column_name,
                            )


def build_lineage(project_root: str | Path) -> dict[str, Any]:
    """Build lineage from starter-kit project assets.

    Args:
        project_root: Directory containing config/, notebooks/, pipelines/,
            and powerbi/ subdirectories.

    Returns:
        {"nodes": [...], "edges": [...]} with deterministic ordering.
    """
    root = Path(project_root).resolve()
    required_dirs = ["config", "notebooks", "pipelines", "powerbi"]
    missing = [name for name in required_dirs if not (root / name).is_dir()]
    if missing:
        raise FileNotFoundError(
            f"Project root {root} is missing required directories: {', '.join(missing)}"
        )

    graph = _GraphBuilder()
    _extract_ingestion(root, graph)
    _extract_notebooks(root, graph)
    _extract_pipeline(root, graph)
    _extract_powerbi(root, graph)
    return graph.result()


def save_lineage(lineage: dict[str, Any], output_path: str | Path) -> Path:
    """Write graph JSON and return its path."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lineage, indent=2), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract notebook, pipeline and Power BI lineage."
    )
    parser.add_argument(
        "--project-root",
        default="starter_kit/project",
        help="Starter-kit project directory",
    )
    parser.add_argument(
        "--output",
        default="outputs/lineage.json",
        help="Output JSON path",
    )
    args = parser.parse_args()

    lineage = build_lineage(args.project_root)
    output = save_lineage(lineage, args.output)
    print(f"Lineage extracted: {len(lineage['nodes'])} nodes, {len(lineage['edges'])} edges.")
    print(f"Saved: {output}")


if __name__ == "__main__":
    main()