import json
import pandas as pd
from pathlib import Path


OUTPUTS = Path("outputs")


def load_dashboard_data():

    data = {}

    files = {
        "schema_diff": "schema_diff.json",
        "lineage": "lineage.json",
        "impact_analysis": "impact_analysis.json",
        "severity_analysis": "severity_analysis.json",
        "decision_analysis": "decision_analysis.json",
        "evaluation_report": "evaluation_report.json"
    }

    for key, filename in files.items():

        path = OUTPUTS / filename

        if path.exists():

            with open(path, "r", encoding="utf-8") as f:
                data[key] = json.load(f)

        else:
            data[key] = None

    csv_path = OUTPUTS / "impact_report.csv"

    data["impact_report"] = (
        pd.read_csv(csv_path)
        if csv_path.exists()
        else pd.DataFrame()
    )

    return data