"""
Schema Drift Impact Analyzer — FastAPI Backend
================================================

Exposes the full engine pipeline as REST endpoints.

Endpoints:
    GET  /api/health        → Health check
    POST /api/schema-diff   → Compare before/after schemas
    GET  /api/lineage       → Build lineage graph
    POST /api/analyze       → Full pipeline: diff → lineage → impact → severity → decision
    GET  /api/report        → Download impact_report.csv
"""

from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

# ── Ensure project root is importable ──────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.models import (
    AnalyzeRequest,
    AnalyzeResponse,
    ChangeSummary,
    HealthResponse,
    ImpactRow,
    LineageResponse,
    PipelineSummary,
    SchemaDiffRequest,
    SchemaDiffResponse,
    SchemaChange,
)
from src.engines.schema_diff import compare_schemas
from src.engines.lineage_engine import build_lineage
from src.engines.impact_engine import build_impact_report
from src.engines.severity_engine import assign_severity
from src.engines.decision_engine import make_decisions

# ── App ────────────────────────────────────────────────

app = FastAPI(
    title="Schema Drift Impact Analyzer",
    description="Detect schema changes, trace lineage, and assess downstream impact — all the way to Power BI visuals.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory state (per-session, single-user hackathon) ──

_state: dict[str, Any] = {}

OUTPUTS_DIR = PROJECT_ROOT / "outputs"


# ── Helpers ────────────────────────────────────────────

def _schema_to_dict(schema_model: dict) -> dict:
    """Convert Pydantic TableSchema models back to raw dicts for the engine."""
    result = {}
    for table_name, table_schema in schema_model.items():
        if hasattr(table_schema, "columns"):
            result[table_name] = {
                "columns": [
                    {"name": col.name, "type": col.type}
                    for col in table_schema.columns
                ]
            }
        elif isinstance(table_schema, dict):
            result[table_name] = table_schema
        else:
            result[table_name] = table_schema
    return result


# ── Endpoints ──────────────────────────────────────────

@app.get("/api/health", response_model=HealthResponse)
def health_check():
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        engines=[
            "schema_diff",
            "lineage_engine",
            "impact_engine",
            "severity_engine",
            "decision_engine",
            "report_engine",
        ],
    )


@app.post("/api/schema-diff", response_model=SchemaDiffResponse)
def schema_diff(request: SchemaDiffRequest):
    """Compare before/after schemas and return detected changes."""
    try:
        before = _schema_to_dict(request.before)
        after = _schema_to_dict(request.after)

        seeded = request.seeded_changes
        if seeded is None:
            default_seeds = PROJECT_ROOT / "starter_kit" / "schemas" / "seeded_changes.json"
            if default_seeds.exists():
                try:
                    seeded = json.loads(default_seeds.read_text(encoding="utf-8"))
                except Exception:
                    seeded = None

        changes = compare_schemas(
            before,
            after,
            seeded,
        )

        _state["schema_changes"] = changes
        _state["before"] = before
        _state["after"] = after

        return SchemaDiffResponse(
            total_changes=len(changes),
            changes=[SchemaChange(**c) for c in changes],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Schema diff failed: {exc}")


@app.get("/api/lineage", response_model=LineageResponse)
def lineage(
    project_root: str = Query(
        default="starter_kit/project",
        description="Path to the project directory.",
    )
):
    """Build the end-to-end lineage graph."""
    try:
        resolved = (PROJECT_ROOT / project_root).resolve()
        graph = build_lineage(str(resolved))

        _state["lineage"] = graph

        return LineageResponse(
            nodes=graph["nodes"],
            edges=graph["edges"],
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Lineage build failed: {exc}")


@app.post("/api/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest):
    """
    Full pipeline: schema diff → lineage → impact → severity → decision.

    Returns the complete analysis result in a single call.
    """
    try:
        # 1. Schema diff
        before = _schema_to_dict(request.before)
        after = _schema_to_dict(request.after)

        seeded = request.seeded_changes
        if seeded is None:
            default_seeds = PROJECT_ROOT / "starter_kit" / "schemas" / "seeded_changes.json"
            if default_seeds.exists():
                try:
                    seeded = json.loads(default_seeds.read_text(encoding="utf-8"))
                except Exception:
                    seeded = None

        schema_changes = compare_schemas(
            before,
            after,
            seeded,
        )

        # 2. Lineage
        resolved = (PROJECT_ROOT / request.project_root).resolve()
        lineage_graph = build_lineage(str(resolved))

        # 3. Impact analysis (produces summary, change_summaries, impacts)
        impact_report = build_impact_report(schema_changes, lineage_graph)

        # 4. Severity scoring
        severity_report = assign_severity(impact_report)

        # 5. Decisions
        decision_report = make_decisions(severity_report)

        # ── Persist to state + disk ──
        _state["schema_changes"] = schema_changes
        _state["lineage"] = lineage_graph
        _state["impact_report"] = impact_report
        _state["severity_report"] = severity_report
        _state["decision_report"] = decision_report

        OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
        (OUTPUTS_DIR / "schema_diff.json").write_text(
            json.dumps(schema_changes, indent=2), encoding="utf-8"
        )
        (OUTPUTS_DIR / "lineage.json").write_text(
            json.dumps(lineage_graph, indent=2), encoding="utf-8"
        )
        (OUTPUTS_DIR / "impact_analysis.json").write_text(
            json.dumps(impact_report, indent=2), encoding="utf-8"
        )
        (OUTPUTS_DIR / "severity_analysis.json").write_text(
            json.dumps(severity_report, indent=2), encoding="utf-8"
        )
        (OUTPUTS_DIR / "decision_analysis.json").write_text(
            json.dumps(decision_report, indent=2), encoding="utf-8"
        )

        # ── Build the response ──

        decisions = decision_report.get("decisions", [])
        decision_by_id = {d["change_id"]: d for d in decisions}

        # Build change summaries with decision
        change_summaries = []
        for cs in severity_report.get("change_summaries", []):
            cid = cs.get("change_id")
            dec = decision_by_id.get(cid, {})
            change_summaries.append(
                ChangeSummary(
                    change_id=cid,
                    source=cs.get("source", ""),
                    change_type=cs.get("change_type", ""),
                    column_before=cs.get("column_before"),
                    column_after=cs.get("column_after"),
                    impact=cs.get("impact", "NO IMPACT"),
                    severity=cs.get("severity", "NONE"),
                    decision=dec.get("decision", cs.get("decision", "SAFE TO LOAD")),
                    affected_object_count=cs.get("affected_object_count", 0),
                )
            )

        # Build impact rows with decision
        impact_rows = []
        for row in severity_report.get("impacts", []):
            impact_val = str(row.get("impact", "NO IMPACT")).upper()
            if impact_val == "BREAKS":
                row_decision = "HOLD THE LOAD"
            elif impact_val == "DEGRADES":
                row_decision = "SAFE WITH WARNING"
            else:
                row_decision = "SAFE TO LOAD"

            impact_rows.append(
                ImpactRow(
                    change_id=row.get("change_id", ""),
                    change_type=row.get("change_type", ""),
                    object=row.get("object", ""),
                    object_type=row.get("object_type", ""),
                    impact=impact_val,
                    severity=str(row.get("severity", "NONE")).upper(),
                    proposed_fix=row.get("proposed_fix", ""),
                    evidence=row.get("evidence", ""),
                    decision=row_decision,
                )
            )

        # Summary counters
        sev_summary = severity_report.get("summary", {})
        dec_summary = decision_report.get("summary", {})
        impact_summary = impact_report.get("summary", {})

        summary = PipelineSummary(
            total_changes=impact_summary.get("total_changes", len(schema_changes)),
            total_impacted_objects=impact_summary.get("total_impacted_objects", 0),
            breaks=impact_summary.get("breaks", 0),
            degrades=impact_summary.get("degrades", 0),
            no_impact=impact_summary.get("no_impact", 0),
            high_severity=sev_summary.get("high_severity_changes", 0),
            medium_severity=sev_summary.get("medium_severity_changes", 0),
            safe_to_load=dec_summary.get("safe_to_load", 0),
            safe_with_warning=dec_summary.get("safe_with_warning", 0),
            hold_the_load=dec_summary.get("hold_the_load", 0),
        )

        return AnalyzeResponse(
            summary=summary,
            change_summaries=change_summaries,
            impacts=impact_rows,
            lineage=LineageResponse(
                nodes=lineage_graph["nodes"],
                edges=lineage_graph["edges"],
            ),
        )

    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}")


@app.get("/api/report")
def download_report():
    """Download the impact report as CSV."""
    csv_path = OUTPUTS_DIR / "impact_report.csv"

    # If analysis was run via API, generate CSV from state
    if "severity_report" in _state and "schema_changes" in _state:
        from src.engines.report_engine import build_report_rows, CSV_COLUMNS

        rows = build_report_rows(
            _state["schema_changes"],
            _state["severity_report"],
        )

        buffer = io.StringIO()
        writer = csv.DictWriter(
            buffer,
            fieldnames=CSV_COLUMNS,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)

        # Also persist to disk
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_path.write_text(buffer.getvalue(), encoding="utf-8-sig")

        return Response(
            content=buffer.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=impact_report.csv"},
        )

    # Fallback: serve from disk if it exists
    if csv_path.exists():
        content = csv_path.read_text(encoding="utf-8-sig")
        return Response(
            content=content,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=impact_report.csv"},
        )

    raise HTTPException(
        status_code=404,
        detail="No report available. Run /api/analyze first.",
    )
