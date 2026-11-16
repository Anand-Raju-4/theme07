from pathlib import Path

import pytest

from src.engines.lineage_engine import build_lineage, save_lineage

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "starter_kit" / "project"


@pytest.fixture(scope="module")
def lineage():
    return build_lineage(PROJECT)


def _transform_edge(lineage, source, target):
    return next(
        edge for edge in lineage["edges"]
        if edge["source"] == f"lakehouse_table:{source}"
        and edge["target"] == f"lakehouse_table:{target}"
        and edge["relationship"] == "transformed_to"
    )


def test_builds_non_empty_graph(lineage):
    assert lineage["nodes"]
    assert lineage["edges"]


def test_existing_ingestion_lineage_is_preserved(lineage):
    assert any(
        edge["source"] == "source_table:erp.orders"
        and edge["target"] == "lakehouse_table:bronze.erp_orders"
        and edge["relationship"] == "ingested_to"
        for edge in lineage["edges"]
    )


def test_customer_notebook_read_write_lineage_is_preserved(lineage):
    assert any(
        edge["source"] == "lakehouse_table:bronze.crm_customers"
        and edge["target"] == "notebook:nb02_silver_customers"
        and edge["relationship"] == "read_by"
        for edge in lineage["edges"]
    )
    assert any(
        edge["source"] == "notebook:nb02_silver_customers"
        and edge["target"] == "lakehouse_table:silver.customers"
        and edge["relationship"] == "writes_to"
        for edge in lineage["edges"]
    )


def test_region_code_join_key_is_extracted(lineage):
    edge = _transform_edge(lineage, "silver.customers", "gold.dim_customer")
    assert edge["join_columns"] == ["region_code"]
    assert "region_code" in edge["referenced_columns"]


def test_region_name_output_depends_on_region_code(lineage):
    edge = _transform_edge(lineage, "silver.customers", "gold.dim_customer")
    assert edge["column_dependencies"]["region_name"] == ["region_code"]


def test_customer_email_pass_through_dependency_is_extracted(lineage):
    edge = _transform_edge(lineage, "bronze.crm_customers", "silver.customers")
    assert edge["column_dependencies"]["email"] == ["email"]


def test_full_name_expression_dependencies_are_extracted(lineage):
    edge = _transform_edge(lineage, "bronze.crm_customers", "silver.customers")
    assert edge["column_dependencies"]["full_name"] == ["first_name", "last_name"]


def test_existing_pipeline_and_powerbi_edges_are_preserved(lineage):
    assert any(edge["relationship"] == "pipeline_dependency" for edge in lineage["edges"])
    assert any(edge["relationship"] == "modelled_as" for edge in lineage["edges"])
    assert any(edge["relationship"] == "used_by_visual" for edge in lineage["edges"])


def test_ingestion_sql_selected_columns_are_preserved(lineage):
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