
"""
Deterministic Severity Engine
=============================

Input:
    outputs/impact_analysis.json

Output:
    outputs/severity_analysis.json

Responsibilities:
    1. Assign consistent severity to every impacted object.
    2. Aggregate the highest severity for each schema change.
    3. Preserve the original impact evidence.
    4. Record the policy used for each classification.

This module does not modify schema or pipeline data.
"""

import argparse
import json
from pathlib import Path
from typing import Any


SEVERITY_RANK = {
    "NONE": 0,
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
    "CRITICAL": 4,
}


def normalise(value: Any) -> str:
    return str(value or "").strip().upper()


def classify_severity(
    impact: str,
    dependency_kind: str = "",
    object_type: str = "",
) -> tuple[str, str]:
    """
    Deterministic severity policy.

    BREAKS   -> HIGH
    DEGRADES -> MEDIUM
    NO IMPACT -> NONE

    The dependency metadata is retained for future policy refinement.
    """

    impact = normalise(impact)
    dependency_kind = normalise(dependency_kind)

    if impact in {"NO IMPACT", "NO_IMPACT"}:
        return "NONE", "No downstream impact was identified."

    if impact == "BREAKS":
        if dependency_kind == "DERIVED":
            return (
                "HIGH",
                "A breaking change affects a derived column or calculation.",
            )

        return (
            "HIGH",
            "A breaking change affects a downstream dependency.",
        )

    if impact == "DEGRADES":
        if dependency_kind == "JOIN_KEY":
            return (
                "MEDIUM",
                "A join-key change may cause missing or unmatched records.",
            )

        return (
            "MEDIUM",
            "A downstream dependency may experience degraded behaviour.",
        )

    return (
        "LOW",
        "The impact requires additional validation.",
    )


def highest_severity(values: list[str]) -> str:
    if not values:
        return "NONE"

    return max(
        values,
        key=lambda value: SEVERITY_RANK.get(normalise(value), 0),
    )


def assign_severity(impact_analysis: dict) -> dict:
    """
    Assign severity to individual impact rows and aggregate by change.
    """

    result = {
        **impact_analysis,
        "severity_policy": {
            "policy_name": "Deterministic Schema Drift Severity Policy",
            "policy_version": "1.0",
            "rules": {
                "BREAKS": "HIGH",
                "DEGRADES": "MEDIUM",
                "NO IMPACT": "NONE",
                "UNKNOWN": "LOW",
            },
        },
    }

    updated_impacts = []

    for original_row in impact_analysis.get("impacts", []):
        row = dict(original_row)

        severity, reason = classify_severity(
            row.get("impact"),
            row.get("dependency_kind", ""),
            row.get("object_type", ""),
        )

        row["severity"] = severity
        row["severity_reason"] = reason

        updated_impacts.append(row)

    result["impacts"] = updated_impacts

    # Recalculate severity at schema-change level.
    updated_summaries = []

    for original_summary in impact_analysis.get(
        "change_summaries", []
    ):
        summary = dict(original_summary)

        change_id = summary.get("change_id")

        matching_rows = [
            row
            for row in updated_impacts
            if row.get("change_id") == change_id
        ]

        if matching_rows:
            severity = highest_severity([
                row["severity"] for row in matching_rows
            ])
        else:
            severity = "NONE"

        summary["severity"] = severity

        updated_summaries.append(summary)

    result["change_summaries"] = updated_summaries

    # Refresh summary counts.
    result["summary"] = {
        **impact_analysis.get("summary", {}),
        "high_severity_changes": sum(
            item["severity"] in {"HIGH", "CRITICAL"}
            for item in updated_summaries
        ),
        "medium_severity_changes": sum(
            item["severity"] == "MEDIUM"
            for item in updated_summaries
        ),
        "low_severity_changes": sum(
            item["severity"] == "LOW"
            for item in updated_summaries
        ),
        "no_severity_changes": sum(
            item["severity"] == "NONE"
            for item in updated_summaries
        ),
    }

    return result


def save_analysis(analysis: dict, output_path: str | Path):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as file:
        json.dump(
            analysis,
            file,
            indent=2,
            ensure_ascii=False,
        )


def main():
    parser = argparse.ArgumentParser(
        description="Run deterministic severity classification."
    )

    parser.add_argument(
        "--input",
        default="outputs/impact_analysis.json",
    )

    parser.add_argument(
        "--output",
        default="outputs/severity_analysis.json",
    )

    args = parser.parse_args()

    input_path = Path(args.input)

    if not input_path.exists():
        raise FileNotFoundError(
            f"Impact analysis not found: {input_path}. "
            "Run impact_engine.py first."
        )

    with input_path.open("r", encoding="utf-8") as file:
        impact_analysis = json.load(file)

    severity_analysis = assign_severity(impact_analysis)

    save_analysis(severity_analysis, args.output)

    print("\nSEVERITY ANALYSIS")
    print("=" * 55)

    print(
        "High severity:",
        severity_analysis["summary"]["high_severity_changes"],
    )
    print(
        "Medium severity:",
        severity_analysis["summary"]["medium_severity_changes"],
    )
    print(
        "Low severity:",
        severity_analysis["summary"]["low_severity_changes"],
    )
    print(
        "No impact:",
        severity_analysis["summary"]["no_severity_changes"],
    )

    print("\nCHANGE-WISE SEVERITY")
    print("-" * 55)

    for item in severity_analysis["change_summaries"]:
        print(
            f"{item['change_id']} | "
            f"{item['impact']} | "
            f"{item['severity']}"
        )

    print(f"\nSaved: {args.output}")


if __name__ == "__main__":
    main()
