
"""
Schema Drift Impact Report Generator
====================================

Inputs:
    outputs/schema_diff.json
    outputs/impact_analysis.json
    outputs/severity_analysis.json
    outputs/decision_analysis.json

Outputs:
    outputs/impact_report.csv
    outputs/evaluation_report.json

The CSV follows the official Theme 07 output contract.
The evaluation report checks coverage and policy consistency.
It does NOT claim ground-truth accuracy without independent
expected impact labels.
"""

import argparse
import csv
import json
from pathlib import Path


CSV_COLUMNS = [
    "change_id",
    "change_type",
    "object",
    "object_type",
    "impact",
    "severity",
    "proposed_fix",
]

VALID_IMPACTS = {"BREAKS", "DEGRADES", "NO IMPACT"}
VALID_SEVERITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW", "NONE"}
VALID_DECISIONS = {
    "SAFE TO LOAD",
    "SAFE WITH WARNING",
    "HOLD THE LOAD",
}


def load_json(path):
    with Path(path).open("r", encoding="utf-8") as file:
        return json.load(file)


def build_report_rows(
    schema_changes,
    severity_analysis,
):
    """
    Create one row per affected object.

    Changes with no downstream impact receive one explicit
    source-level NO IMPACT row so that all seeded changes
    appear in the report.
    """

    impacts = severity_analysis.get("impacts", [])
    summaries = severity_analysis.get("change_summaries", [])

    rows = []
    represented_changes = set()

    for item in impacts:
        change_id = item.get("change_id")

        rows.append({
            "change_id": change_id,
            "change_type": item.get("change_type", ""),
            "object": item.get("object", ""),
            "object_type": item.get("object_type", "unknown"),
            "impact": str(item.get("impact", "NO IMPACT")).upper(),
            "severity": str(item.get("severity", "NONE")).upper(),
            "proposed_fix": item.get("proposed_fix", ""),
        })

        represented_changes.add(change_id)

    # Add explicit rows for changes that have no downstream impacts.
    summary_by_id = {
        item.get("change_id"): item
        for item in summaries
    }

    for change in schema_changes:
        change_id = change.get("change_id")

        if change_id in represented_changes:
            continue

        summary = summary_by_id.get(change_id, {})

        rows.append({
            "change_id": change_id,
            "change_type": change.get("change_type", ""),
            "object": change.get("source", ""),
            "object_type": "source_table",
            "impact": summary.get("impact", "NO IMPACT"),
            "severity": summary.get("severity", "NONE"),
            "proposed_fix": (
                "No downstream change required based on the "
                "currently extracted lineage."
            ),
        })

    # Stable ordering.
    seed_order = {
        item.get("change_id"): index
        for index, item in enumerate(schema_changes)
    }

    rows.sort(
        key=lambda row: (
            seed_order.get(row["change_id"], 999),
            row["object"],
        )
    )

    return rows


def evaluate_outputs(
    schema_changes,
    report_rows,
    decision_analysis,
):
    """
    Check whether all seeded changes are represented and
    whether their classifications and decisions are valid.

    This is structural and policy validation, not ground-truth
    accuracy measurement.
    """

    expected_ids = {
        item.get("change_id")
        for item in schema_changes
    }

    represented_ids = {
        row["change_id"]
        for row in report_rows
    }

    decision_items = decision_analysis.get("decisions", [])

    decision_by_id = {
        item.get("change_id"): item
        for item in decision_items
    }

    missing_ids = sorted(expected_ids - represented_ids)

    invalid_impacts = [
        row for row in report_rows
        if row["impact"] not in VALID_IMPACTS
    ]

    invalid_severities = [
        row for row in report_rows
        if row["severity"] not in VALID_SEVERITIES
    ]

    invalid_decisions = [
        item for item in decision_items
        if item.get("decision") not in VALID_DECISIONS
    ]

    decision_mismatches = []

    for change_id in expected_ids:
        decision = decision_by_id.get(change_id)

        if not decision:
            decision_mismatches.append(change_id)
            continue

        impact = str(decision.get("impact", "")).upper()
        severity = str(decision.get("severity", "")).upper()
        actual_decision = decision.get("decision")

        if impact == "BREAKS" or severity in {"HIGH", "CRITICAL"}:
            expected_decision = "HOLD THE LOAD"
        elif impact == "DEGRADES" or severity == "MEDIUM":
            expected_decision = "SAFE WITH WARNING"
        elif impact == "NO IMPACT":
            expected_decision = "SAFE TO LOAD"
        else:
            expected_decision = None

        if actual_decision != expected_decision:
            decision_mismatches.append(change_id)

    coverage_passed = not missing_ids
    classification_passed = (
        not invalid_impacts and not invalid_severities
    )
    decision_passed = (
        not invalid_decisions
        and not decision_mismatches
        and len(decision_items) == len(expected_ids)
    )

    return {
        "evaluation_type": "STRUCTURAL_AND_POLICY_CONSISTENCY",
        "ground_truth_accuracy_measured": False,
        "ground_truth_note": (
            "Independent expected impact labels have not yet been "
            "provided. Coverage and decision-policy checks do not "
            "prove predictive accuracy."
        ),
        "summary": {
            "total_seeded_changes": len(expected_ids),
            "represented_changes": len(represented_ids),
            "report_rows": len(report_rows),
            "coverage_passed": coverage_passed,
            "classification_values_valid": classification_passed,
            "decision_policy_consistent": decision_passed,
            "structural_validation_passed": (
                coverage_passed
                and classification_passed
                and decision_passed
            ),
        },
        "checks": {
            "missing_change_ids": missing_ids,
            "invalid_impact_rows": len(invalid_impacts),
            "invalid_severity_rows": len(invalid_severities),
            "invalid_decision_rows": len(invalid_decisions),
            "decision_mismatch_ids": sorted(set(decision_mismatches)),
        },
        "change_results": [
            {
                "change_id": change_id,
                "impact": decision_by_id.get(
                    change_id, {}
                ).get("impact"),
                "severity": decision_by_id.get(
                    change_id, {}
                ).get("severity"),
                "decision": decision_by_id.get(
                    change_id, {}
                ).get("decision"),
                "report_object_count": sum(
                    row["change_id"] == change_id
                    for row in report_rows
                ),
            }
            for change_id in sorted(expected_ids)
        ],
    }


def main():
    parser = argparse.ArgumentParser(
        description="Generate Theme 07 impact report and evaluation."
    )

    parser.add_argument(
        "--changes",
        default="outputs/schema_diff.json",
    )

    parser.add_argument(
        "--severity",
        default="outputs/severity_analysis.json",
    )

    parser.add_argument(
        "--decisions",
        default="outputs/decision_analysis.json",
    )

    parser.add_argument(
        "--csv",
        default="outputs/impact_report.csv",
    )

    parser.add_argument(
        "--evaluation",
        default="outputs/evaluation_report.json",
    )

    args = parser.parse_args()

    changes = load_json(args.changes)
    severity = load_json(args.severity)
    decisions = load_json(args.decisions)

    rows = build_report_rows(changes, severity)

    # Generate the official CSV.
    csv_path = Path(args.csv)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    with csv_path.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=CSV_COLUMNS,
            extrasaction="ignore",
        )

        writer.writeheader()
        writer.writerows(rows)

    # Generate structural evaluation.
    evaluation = evaluate_outputs(
        changes,
        rows,
        decisions,
    )

    evaluation_path = Path(args.evaluation)
    evaluation_path.parent.mkdir(parents=True, exist_ok=True)

    with evaluation_path.open("w", encoding="utf-8") as file:
        json.dump(evaluation, file, indent=2)

    print("\nIMPACT REPORT GENERATED")
    print("=" * 55)
    print(f"Seeded changes: {len(changes)}")
    print(f"Report rows:    {len(rows)}")
    print(f"CSV:            {csv_path}")
    print(f"Evaluation:     {evaluation_path}")

    print("\nSTRUCTURAL VALIDATION")
    print("-" * 55)

    for key, value in evaluation["summary"].items():
        print(f"{key}: {value}")

    print("\nCHANGE COVERAGE")
    print("-" * 55)

    for item in evaluation["change_results"]:
        print(
            f"{item['change_id']} | "
            f"{item['impact']} | "
            f"{item['severity']} | "
            f"{item['decision']} | "
            f"Objects: {item['report_object_count']}"
        )

    if not evaluation["summary"]["structural_validation_passed"]:
        print("\nWARNING: Structural validation needs attention.")

    #print("\nGround-truth predictive accuracy: NOT YET MEASURED")


if __name__ == "__main__":
    main()
