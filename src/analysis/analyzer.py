# src/analysis/analyzer.py

from src.engines.schema_diff import compare_schemas
from src.engines.lineage_engine import build_lineage
from src.engines.impact_engine import analyze_impacts
# from src.engines.severity_engine import SeverityEngine
# from src.engines.decision_engine import DecisionEngine

def run_analysis(before_schema, after_schema):

    schema_changes = compare_schemas(
        before_schema,
        after_schema
    )

    lineage = build_lineage("starter_kit/project")

    impact = analyze_impacts(
        schema_changes,
        lineage
    )

    # severity = SeverityEngine.score(
    #     impact
    # )

    # recommendation = DecisionEngine.recommend(
    #     severity
    # )

    return {
        "schema_changes": schema_changes,
        "lineage": lineage,
        "impact": impact,
        # "severity": severity,
        # "recommendation": recommendation
    }