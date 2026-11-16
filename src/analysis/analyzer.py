# src/analysis/analyzer.py

from src.engines.schema_diff import compare_schemas
from src.engines.lineage_engine import build_lineage
from src.engines.impact_engine import build_impact_report
from src.engines.severity_engine import assign_severity
from src.engines.decision_engine import make_decisions


def run_analysis(before_schema, after_schema, seeded_changes=None,
                 project_root="starter_kit/project"):
    """
    Run the full analysis pipeline:
        schema diff → lineage → impact → severity → decision

    Returns a dict with all results keyed for the UI and report engine.
    """

    schema_changes = compare_schemas(
        before_schema,
        after_schema,
        seeded_changes,
    )

    lineage = build_lineage(project_root)

    impact_report = build_impact_report(
        schema_changes,
        lineage,
    )

    severity_report = assign_severity(impact_report)

    decision_report = make_decisions(severity_report)

    return {
        "schema_changes": schema_changes,
        "lineage": lineage,
        "impact_report": impact_report,
        "severity_report": severity_report,
        "decision_report": decision_report,
        # Flattened keys for backward compatibility
        "impacts": severity_report.get("impacts", []),
        "change_summaries": severity_report.get("change_summaries", []),
        "decisions": decision_report.get("decisions", []),
    }
