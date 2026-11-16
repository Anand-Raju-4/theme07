import json
from pathlib import Path
import pytest

from api.main import health_check, schema_diff, lineage, analyze, download_report
from api.models import SchemaDiffRequest, AnalyzeRequest, TableSchema, SchemaColumn

ROOT = Path(__file__).resolve().parents[1]


def test_health_check_handler():
    res = health_check()
    assert res.status == "healthy"
    assert "schema_diff" in res.engines
    assert "lineage_engine" in res.engines
    assert "impact_engine" in res.engines
    assert "severity_engine" in res.engines
    assert "decision_engine" in res.engines


def test_schema_diff_handler():
    before_path = ROOT / "starter_kit" / "schemas" / "sources_before.json"
    after_path = ROOT / "starter_kit" / "schemas" / "sources_after.json"
    seeds_path = ROOT / "starter_kit" / "schemas" / "seeded_changes.json"

    with open(before_path, "r", encoding="utf-8") as f:
        before = json.load(f)
    with open(after_path, "r", encoding="utf-8") as f:
        after = json.load(f)
    with open(seeds_path, "r", encoding="utf-8") as f:
        seeds = json.load(f)

    req = SchemaDiffRequest(
        before=before,
        after=after,
        seeded_changes=seeds,
    )

    res = schema_diff(req)
    assert res.total_changes == 10
    assert len(res.changes) == 10


def test_lineage_handler():
    res = lineage(project_root="starter_kit/project")
    assert len(res.nodes) > 0
    assert len(res.edges) > 0


def test_analyze_and_download_report_handler():
    before_path = ROOT / "starter_kit" / "schemas" / "sources_before.json"
    after_path = ROOT / "starter_kit" / "schemas" / "sources_after.json"
    seeds_path = ROOT / "starter_kit" / "schemas" / "seeded_changes.json"

    with open(before_path, "r", encoding="utf-8") as f:
        before = json.load(f)
    with open(after_path, "r", encoding="utf-8") as f:
        after = json.load(f)
    with open(seeds_path, "r", encoding="utf-8") as f:
        seeds = json.load(f)

    req = AnalyzeRequest(
        before=before,
        after=after,
        seeded_changes=seeds,
        project_root="starter_kit/project",
    )

    res = analyze(req)
    assert res.summary.total_changes == 10
    assert res.summary.hold_the_load > 0
    assert len(res.change_summaries) == 10
    assert len(res.impacts) > 0

    # Test CSV report download
    rep_response = download_report()
    content = rep_response.body.decode("utf-8")
    assert "change_id,change_type,object,object_type,impact,severity,proposed_fix" in content
