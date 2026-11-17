
"""Independent change-level ground-truth evaluation for Theme 07."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _normalise(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).strip().upper()


def _index_by_change_id(records: list[dict]):
    indexed = {}
    duplicates = []

    for record in records:
        change_id = str(record.get("change_id") or "").strip()

        if not change_id:
            continue

        if change_id in indexed:
            duplicates.append(change_id)
        else:
            indexed[change_id] = record

    return indexed, sorted(set(duplicates))


def evaluate_ground_truth(
    schema_changes: list[dict],
    severity_analysis: dict,
    decision_analysis: dict,
    ground_truth: dict,
) -> dict:
    """Compare predicted impact, severity and decision with expected labels."""

    expected_records = ground_truth.get("changes", [])

    expected_by_id, duplicate_expected = _index_by_change_id(
        expected_records
    )

    impact_predictions, duplicate_impact = _index_by_change_id(
        severity_analysis.get("change_summaries", [])
    )

    severity_predictions = impact_predictions

    decision_predictions, duplicate_decisions = _index_by_change_id(
        decision_analysis.get("decisions", [])
    )

    seeded_by_id, duplicate_seeded = _index_by_change_id(
        schema_changes
    )

    expected_ids = set(expected_by_id)
    seeded_ids = set(seeded_by_id)

    result_rows = []

    correct = {
        "impact": 0,
        "severity": 0,
        "decision": 0,
    }

    missing = {
        "impact": [],
        "severity": [],
        "decision": [],
    }

    incorrect = {
        "impact": [],
        "severity": [],
        "decision": [],
    }

    for change_id in sorted(expected_ids):

        expected = expected_by_id[change_id]

        impact_record = impact_predictions.get(change_id)
        severity_record = severity_predictions.get(change_id)
        decision_record = decision_predictions.get(change_id)

        predicted = {
            "impact": _normalise(
                (impact_record or {}).get("impact")
            ),
            "severity": _normalise(
                (severity_record or {}).get("severity")
            ),
            "decision": _normalise(
                (decision_record or {}).get("decision")
            ),
        }

        expected_labels = {
            "impact": _normalise(
                expected.get("expected_impact")
            ),
            "severity": _normalise(
                expected.get("expected_severity")
            ),
            "decision": _normalise(
                expected.get("expected_decision")
            ),
        }

        matches = {}

        for label in ("impact", "severity", "decision"):

            if predicted[label] is None:
                missing[label].append(change_id)
                matches[label] = False

            elif predicted[label] == expected_labels[label]:
                correct[label] += 1
                matches[label] = True

            else:
                incorrect[label].append(change_id)
                matches[label] = False

        result_rows.append({
            "change_id": change_id,
            "source": expected.get("source"),
            "column": expected.get("column"),
            "expected": expected_labels,
            "predicted": predicted,
            "matches": matches,
            "status": (
                "PASS" if all(matches.values()) else "FAIL"
            ),
        })

    total = len(expected_ids)

    def metric(label: str) -> dict:

        predicted_count = total - len(missing[label])

        accuracy = (
            correct[label] / total * 100
            if total
            else 0.0
        )

        return {
            "expected_count": total,
            "predicted_count": predicted_count,
            "correct_count": correct[label],
            "incorrect_count": len(incorrect[label]),
            "missing_count": len(missing[label]),
            "accuracy_percentage": round(accuracy, 2),
            "correct_change_ids": [
                row["change_id"]
                for row in result_rows
                if row["matches"][label]
            ],
            "incorrect_change_ids": incorrect[label],
            "missing_change_ids": missing[label],
        }

    all_duplicates = {
        "ground_truth": duplicate_expected,
        "seeded_changes": duplicate_seeded,
        "impact": duplicate_impact,
        "severity": duplicate_impact,
        "decision": duplicate_decisions,
    }

    missing_seed_ids = sorted(expected_ids - seeded_ids)
    extra_seed_ids = sorted(seeded_ids - expected_ids)

    coverage_complete = all(
        not missing[label] for label in missing
    )

    duplicates_found = any(all_duplicates.values())

    all_metrics_perfect = all(
        correct[label] == total
        and not missing[label]
        and not incorrect[label]
        for label in correct
    )

    passed = (
        coverage_complete
        and not duplicates_found
        and not missing_seed_ids
        and not extra_seed_ids
        and all_metrics_perfect
    )

    return {
        "evaluation_type": "INDEPENDENT_GROUND_TRUTH_EVALUATION",
        "evaluation_scope": ground_truth.get(
            "metadata", {}
        ).get("evaluation_scope", "change_level"),

        "ground_truth_accuracy_measured": True,

        "ground_truth_version": ground_truth.get(
            "metadata", {}
        ).get("version"),

        "summary": {
            "total_expected_changes": total,
            "seeded_changes_received": len(seeded_ids),
            "prediction_coverage_complete": coverage_complete,
            "duplicate_predictions_found": duplicates_found,
            "missing_seed_change_ids": missing_seed_ids,
            "extra_seed_change_ids": extra_seed_ids,

            "impact_accuracy_percentage":
                metric("impact")["accuracy_percentage"],

            "severity_accuracy_percentage":
                metric("severity")["accuracy_percentage"],

            "decision_accuracy_percentage":
                metric("decision")["accuracy_percentage"],

            "evaluation_status": "PASS" if passed else "FAIL",
        },

        "checks": {
            "duplicate_ids": all_duplicates,
            "missing_impact_ids": missing["impact"],
            "missing_severity_ids": missing["severity"],
            "missing_decision_ids": missing["decision"],
        },

        "metrics": {
            "impact": metric("impact"),
            "severity": metric("severity"),
            "decision": metric("decision"),
        },

        "change_results": result_rows,
    }


def _load_json(path: str | Path):
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main():

    parser = argparse.ArgumentParser(
        description="Evaluate Theme 07 against independent ground truth."
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
        "--ground-truth",
        default="tests/fixtures/ground_truth.json",
    )

    parser.add_argument(
        "--output",
        default="outputs/ground_truth_evaluation.json",
    )

    args = parser.parse_args()

    result = evaluate_ground_truth(
        _load_json(args.changes),
        _load_json(args.severity),
        _load_json(args.decisions),
        _load_json(args.ground_truth),
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("\nINDEPENDENT GROUND-TRUTH EVALUATION")
    print("=" * 55)

    for key in (
        "total_expected_changes",
        "impact_accuracy_percentage",
        "severity_accuracy_percentage",
        "decision_accuracy_percentage",
        "evaluation_status",
    ):
        print(f"{key}: {result['summary'][key]}")

    print(f"Saved: {output_path}")

    if result["summary"]["evaluation_status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
