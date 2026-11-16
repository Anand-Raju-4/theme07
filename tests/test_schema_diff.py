from pathlib import Path

import pytest

from src.engines.lineage_engine import build_lineage, save_lineage

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "starter_kit" / "project"


@pytest.fixture(scope="module")
def lineage():
    return build_lineage(PROJECT)


def test_builds_non_empty_graph(lineage):
    assert lineage["nodes"]
    assert lineage["edges"]


def test_ingestion_config_connects_sources_to_bronze(lineage):
    edges = lineage["edges"]
    assert any(
        edge["source"] == "source_table:erp.orders"
        and edge["target"] == "lakehouse_table:bronze.erp_orders"
        and edge["relationship"] == "ingested_to"
        for edge in edges
    )


def test_notebook_reads_and_writes_are_detected(lineage):
    edges = lineage["edges"]
    assert any(
        edge["source"] == "lakehouse_table:bronze.erp_orders"
        and edge["target"] == "notebook:nb03_silver_orders"
        and edge["relationship"] == "read_by"
        for edge in edges
    )
    assert any(
        edge["source"] == "notebook:nb03_silver_orders"
        and edge["target"] == "lakehouse_table:silver.orders"
        and edge["relationship"] == "writes_to"
        for edge in edges
    )


def test_powerbi_gold_tables_map_to_semantic_tables(lineage):
    assert any(
        edge["source"] == "lakehouse_table:gold.fact_sales"
        and edge["target"] == "semantic_table:fact_sales"
        and edge["relationship"] == "modelled_as"
        for edge in lineage["edges"]
    )


def test_reports_visuals_and_measures_are_connected(lineage):
    edges = lineage["edges"]
    assert any(
        edge["source"] == "measure:Margin %"
        and edge["target"] == "report_visual:Executive Sales/Margin %"
        and edge["relationship"] == "used_by_visual"
        for edge in edges
    )
    assert any(
        edge["source"] == "report:Executive Sales"
        and edge["target"] == "report_visual:Executive Sales/Net Sales by Region"
        and edge["relationship"] == "contains_visual"
        for edge in edges
    )


def test_ingestion_select_columns_are_captured(lineage):
    edge = next(
        edge for edge in lineage["edges"]
        if edge["source"] == "source_table:erp.orders"
        and edge["relationship"] == "ingested_to"
    )
    assert "discount_amount" in edge["selected_columns"]
    assert "ship_date" in edge["selected_columns"]


def test_save_lineage_writes_json(tmp_path, lineage):
    output = save_lineage(lineage, tmp_path / "lineage.json")
    assert output.exists()
    assert '"nodes"' in output.read_text(encoding="utf-8")


def test_missing_project_directory_is_reported(tmp_path):
    with pytest.raises(FileNotFoundError, match="missing required directories"):
        build_lineage(tmp_path)


import pytest

from src.engines.schema_diff import compare_schemas


# ---------------------------------------------------------
# TEST DATA
# ---------------------------------------------------------

def make_schema(columns):
    """Create a table schema from column definitions."""
    return {
        "columns": [
            {"name": name, "type": data_type}
            for name, data_type in columns.items()
        ]
    }


# ---------------------------------------------------------
# 1. ADDED COLUMN
# ---------------------------------------------------------

def test_detect_added_column():
    before = {
        "crm.customers": make_schema({
            "customer_id": "integer",
            "name": "string"
        })
    }

    after = {
        "crm.customers": make_schema({
            "customer_id": "integer",
            "name": "string",
            "loyalty_tier": "string"
        })
    }

    changes = compare_schemas(before, after)

    assert len(changes) == 1
    assert changes[0]["change_type"] == "add"
    assert changes[0]["column_after"] == "loyalty_tier"


# ---------------------------------------------------------
# 2. DROPPED COLUMN
# ---------------------------------------------------------

def test_detect_dropped_column():
    before = {
        "crm.customers": make_schema({
            "customer_id": "integer",
            "email": "string"
        })
    }

    after = {
        "crm.customers": make_schema({
            "customer_id": "integer"
        })
    }

    changes = compare_schemas(before, after)

    assert len(changes) == 1
    assert changes[0]["change_type"] == "drop"
    assert changes[0]["column_before"] == "email"


# ---------------------------------------------------------
# 3. TYPE CHANGE
# ---------------------------------------------------------

def test_detect_type_change():
    before = {
        "erp.orders": make_schema({
            "order_id": "integer",
            "total_amount": "decimal(18,2)"
        })
    }

    after = {
        "erp.orders": make_schema({
            "order_id": "integer",
            "total_amount": "decimal(20,4)"
        })
    }

    changes = compare_schemas(before, after)

    assert len(changes) == 1
    assert changes[0]["change_type"] == "type change"
    assert changes[0]["column_before"] == "total_amount"
    assert changes[0]["type_before"] == "decimal(18,2)"
    assert changes[0]["type_after"] == "decimal(20,4)"


# ---------------------------------------------------------
# 4. RENAME WITH EXPLICIT HINT
# ---------------------------------------------------------

def test_detect_rename_with_explicit_hint():
    before = {
        "crm.customers": make_schema({
            "customer_id": "integer",
            "email": "string"
        })
    }

    after = {
        "crm.customers": make_schema({
            "customer_id": "integer",
            "email_address": "string"
        })
    }

    seeded_changes = {
        "changes": [
            {
                "change_id": "TEST01",
                "source": "crm.customers",
                "change_type": "rename",
                "detail": "email -> email_address"
            }
        ]
    }

    changes = compare_schemas(
        before,
        after,
        seeded_changes
    )

    assert len(changes) == 1
    assert changes[0]["change_type"] == "rename"
    assert changes[0]["column_before"] == "email"
    assert changes[0]["column_after"] == "email_address"


# ---------------------------------------------------------
# 5. NO SCHEMA CHANGE
# ---------------------------------------------------------

def test_no_schema_changes():
    before = {
        "crm.customers": make_schema({
            "customer_id": "integer",
            "name": "string"
        })
    }

    after = {
        "crm.customers": make_schema({
            "customer_id": "integer",
            "name": "string"
        })
    }

    changes = compare_schemas(before, after)

    assert changes == []


# ---------------------------------------------------------
# 6. MULTIPLE CHANGES IN ONE TABLE
# ---------------------------------------------------------

def test_detect_multiple_changes():
    before = {
        "crm.customers": make_schema({
            "customer_id": "integer",
            "email": "string",
            "age": "integer"
        })
    }

    after = {
        "crm.customers": make_schema({
            "customer_id": "integer",
            "email_address": "string",
            "age": "string",
            "loyalty_tier": "string"
        })
    }

    seeded_changes = {
        "changes": [
            {
                "change_id": "TEST02",
                "source": "crm.customers",
                "change_type": "rename",
                "detail": "email -> email_address"
            }
        ]
    }

    changes = compare_schemas(
        before,
        after,
        seeded_changes
    )

    change_types = {
        change["change_type"]
        for change in changes
    }

    assert len(changes) == 3
    assert "rename" in change_types
    assert "type change" in change_types
    assert "add" in change_types


# ---------------------------------------------------------
# 7. INVALID DUPLICATE COLUMN
# ---------------------------------------------------------

def test_duplicate_column_raises_error():
    before = {
        "crm.customers": {
            "columns": [
                {"name": "customer_id", "type": "integer"},
                {"name": "customer_id", "type": "string"}
            ]
        }
    }

    after = {
        "crm.customers": make_schema({
            "customer_id": "integer"
        })
    }

    with pytest.raises(ValueError):
        compare_schemas(before, after)


# ---------------------------------------------------------
# 8. INVALID COLUMN DEFINITION
# ---------------------------------------------------------

def test_invalid_column_definition_raises_error():
    before = {
        "crm.customers": {
            "columns": [
                {"name": "customer_id"}
            ]
        }
    }

    after = {
        "crm.customers": make_schema({
            "customer_id": "integer"
        })
    }

    with pytest.raises(ValueError):
        compare_schemas(before, after)


# ---------------------------------------------------------
# 9. CASE-ONLY TYPE DIFFERENCE
# ---------------------------------------------------------

def test_ignore_case_only_type_difference():
    before = {
        "crm.customers": make_schema({
            "customer_id": "STRING"
        })
    }

    after = {
        "crm.customers": make_schema({
            "customer_id": "string"
        })
    }

    changes = compare_schemas(before, after)

    assert changes == []
