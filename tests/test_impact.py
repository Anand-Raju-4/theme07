import pytest

from src.engines.impact_engine import analyze_impacts


def make_lineage():
    return {
        "nodes": [
            {"id": "source_table:crm.customers", "name": "crm.customers", "type": "source_table", "metadata": {}},
            {"id": "lakehouse_table:bronze.crm_customers", "name": "bronze.crm_customers", "type": "lakehouse_table", "metadata": {}},
            {"id": "notebook:nb02_silver_customers", "name": "nb02_silver_customers", "type": "notebook", "metadata": {}},
            {"id": "lakehouse_table:silver.customers", "name": "silver.customers", "type": "lakehouse_table", "metadata": {}},
            {"id": "lakehouse_table:gold.dim_customer", "name": "gold.dim_customer", "type": "lakehouse_table", "metadata": {}},
        ],
        "edges": [
            {
                "source": "source_table:crm.customers",
                "target": "lakehouse_table:bronze.crm_customers",
                "relationship": "ingested_to",
                "evidence": "ingest config",
                "selected_columns": None,
            },
            {
                "source": "lakehouse_table:bronze.crm_customers",
                "target": "notebook:nb02_silver_customers",
                "relationship": "read_by",
                "evidence": "notebook reads email",
                "columns": ["email", "customer_id"],
            },
            {
                "source": "notebook:nb02_silver_customers",
                "target": "lakehouse_table:silver.customers",
                "relationship": "writes_to",
                "evidence": "writes silver",
            },
            {
                "source": "lakehouse_table:silver.customers",
                "target": "lakehouse_table:gold.dim_customer",
                "relationship": "transformed_to",
                "evidence": "silver to gold",
                "referenced_columns": ["email"],
            },
        ],
    }


def test_rename_used_downstream_is_breaking():
    change = {
        "change_id": "T01", "source": "crm.customers", "change_type": "rename",
        "column_before": "email", "column_after": "email_address",
        "type_before": "string", "type_after": "string",
    }
    rows = analyze_impacts([change], make_lineage())
    assert rows
    assert {row["impact"] for row in rows} == {"breaks"}
    assert {row["decision"] for row in rows} == {"HOLD THE LOAD"}
    assert "nb02_silver_customers" in {row["object"] for row in rows}


def test_added_unused_column_has_no_impact():
    change = {
        "change_id": "T02", "source": "crm.customers", "change_type": "add",
        "column_before": None, "column_after": "loyalty_tier",
        "type_before": None, "type_after": "string",
    }
    rows = analyze_impacts([change], make_lineage())
    assert len(rows) == 1
    assert rows[0]["impact"] == "no impact"
    assert rows[0]["decision"] == "SAFE TO LOAD"


def test_explicit_ingestion_projection_drop_is_breaking():
    lineage = make_lineage()
    lineage["edges"][0]["selected_columns"] = ["customer_id", "email"]
    change = {
        "change_id": "T03", "source": "crm.customers", "change_type": "drop",
        "column_before": "email", "column_after": None,
        "type_before": "string", "type_after": None,
    }
    rows = analyze_impacts([change], lineage)
    assert rows
    assert all(row["impact"] == "breaks" for row in rows)
    assert all(row["severity"] == "high" for row in rows)


def test_decimal_precision_widening_is_safe():
    change = {
        "change_id": "T04", "source": "crm.customers", "change_type": "type change",
        "column_before": "amount", "column_after": "amount",
        "type_before": "decimal(18,2)", "type_after": "decimal(20,4)",
    }
    rows = analyze_impacts([change], make_lineage())
    assert rows[0]["impact"] == "no impact"
    assert rows[0]["decision"] == "SAFE TO LOAD"

