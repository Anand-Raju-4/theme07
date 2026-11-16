
"""
Pipeline Decision Engine
========================

Input:
    outputs/severity_analysis.json

Output:
    outputs/decision_analysis.json

Purpose:
    Convert impact and severity into deterministic pipeline decisions.

This engine does not execute, modify, or release any pipeline.
It produces a recommendation for an external orchestrator or human reviewer.
"""

import argparse
import json
from pathlib import Path
from typing import Any


def normalise(value: Any) -> str:
    return str(value or "").strip().upper()


def decide(impact: str, severity: str) -> tuple[str, str, str]:
    """
    Return:
        decision, reason, requires_approval
    """

    impact = normalise(impact)
    severity = normalise(severity)

    if impact in {"NO IMPACT", "NO_IMPACT"}:
        return (
            "SAFE TO LOAD",
            "No downstream impact was identified.",
            "NO",
        )

    if impact == "BREAKS" or severity in {"HIGH", "CRITICAL"}:
        return (
            "HOLD THE LOAD",
            "A breaking or high-severity dependency requires remediation.",
            "YES",
        )

    if impact == "DEGRADES" or severity == "MEDIUM":
        return (
            "SAFE WITH WARNING",
            "A downstream dependency may be degraded. Validation is required.",
            "YES",
        )

    return (
        "SAFE WITH WARNING",
        "Impact classification is uncertain. Review before proceeding.",
        "YES",
    )


def make_decisions(severity_analysis: dict) -> dict:
    """
    Generate a decision for each schema change.
    """

    output = {
        "decision_policy": {
            "policy_name": "Schema Drift Pipeline Load Gate",
            "policy_version": "1.0",
            "automatic_execution": False,
            "rules": {
                "NO IMPACT": "SAFE TO LOAD",
                "BREAKS or HIGH": "HOLD THE LOAD",
                "DEGRADES or MEDIUM": "SAFE WITH WARNING",
                "UNKNOWN": "SAFE WITH WARNING",
            },
        },
        "summary": {},
        "decisions": [],
    }

    for item in severity_analysis.get("change_summaries", []):
        impact = item.get("impact")
        severity = item.get("severity")

        decision, reason, approval = decide(impact, severity)

        output["decisions"].append({
            "change_id": item.get("change_id"),
            "source": item.get("source"),
            "change_type": item.get("change_type"),
            "column_before": item.get("column_before"),
            "column_after": item.get("column_after"),
            "impact": impact,
            "severity": severity,
            "decision": decision,
            "reason": reason,
            "requires_human_approval": approval,
        })

    decisions = output["decisions"]

    output["summary"] = {
        "total_changes": len(decisions),
        "safe_to_load": sum(
            x["decision"] == "SAFE TO LOAD" for x in decisions
        ),
        "safe_with_warning": sum(
            x["decision"] == "SAFE WITH WARNING" for x in decisions
        ),
        "hold_the_load": sum(
            x["decision"] == "HOLD THE LOAD" for x in decisions
        ),
        "human_approval_required": sum(
            x["requires_human_approval"] == "YES" for x in decisions
        ),
    }

    return output


def save_decisions(data: dict, output_path: str | Path):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser(
        description="Generate schema drift pipeline decisions."
    )

    parser.add_argument(
        "--input",
        default="outputs/severity_analysis.json",
    )

    parser.add_argument(
        "--output",
        default="outputs/decision_analysis.json",
    )

    args = parser.parse_args()

    input_path = Path(args.input)

    if not input_path.exists():
        raise FileNotFoundError(
            f"Severity analysis not found: {input_path}. "
            "Run severity_engine.py first."
        )

    with input_path.open("r", encoding="utf-8") as file:
        severity_analysis = json.load(file)

    decisions = make_decisions(severity_analysis)
    save_decisions(decisions, args.output)

    print("\nPIPELINE DECISION ANALYSIS")
    print("=" * 55)

    for key, value in decisions["summary"].items():
        print(f"{key}: {value}")

    print("\nCHANGE-WISE DECISIONS")
    print("-" * 55)

    for item in decisions["decisions"]:
        print(
            f"{item['change_id']} | "
            f"{item['impact']} | "
            f"{item['severity']} | "
            f"{item['decision']}"
        )

    print(f"\nSaved: {args.output}")


if __name__ == "__main__":
    main()
