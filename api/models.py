"""
Pydantic models for the Schema Drift Impact Analyzer API.
"""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


# ─── Request Models ───────────────────────────────────────


class SchemaColumn(BaseModel):
    name: str
    type: str


class TableSchema(BaseModel):
    columns: list[SchemaColumn]


class SchemaDiffRequest(BaseModel):
    """Before/after source schema snapshots for comparison."""

    before: dict[str, TableSchema]
    after: dict[str, TableSchema]
    seeded_changes: Optional[dict[str, Any]] = None


class AnalyzeRequest(BaseModel):
    """Full pipeline analysis request."""

    before: dict[str, TableSchema]
    after: dict[str, TableSchema]
    seeded_changes: Optional[dict[str, Any]] = None
    project_root: str = Field(
        default="starter_kit/project",
        description="Path to the project directory containing config/, notebooks/, pipelines/, powerbi/.",
    )


# ─── Response Models ─────────────────────────────────────


class SchemaChange(BaseModel):
    change_id: Optional[str] = None
    source: str
    change_type: str
    column_before: Optional[str] = None
    column_after: Optional[str] = None
    type_before: Optional[str] = None
    type_after: Optional[str] = None
    description: str


class SchemaDiffResponse(BaseModel):
    total_changes: int
    changes: list[SchemaChange]


class LineageResponse(BaseModel):
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]


class ImpactRow(BaseModel):
    change_id: str
    change_type: str
    object: str
    object_type: str
    impact: str
    severity: str
    proposed_fix: str
    evidence: str
    decision: str


class ChangeSummary(BaseModel):
    change_id: str
    source: str
    change_type: str
    column_before: Optional[str] = None
    column_after: Optional[str] = None
    impact: str
    severity: str
    decision: str
    affected_object_count: int


class PipelineSummary(BaseModel):
    total_changes: int
    total_impacted_objects: int
    breaks: int
    degrades: int
    no_impact: int
    high_severity: int
    medium_severity: int
    safe_to_load: int
    safe_with_warning: int
    hold_the_load: int


class AnalyzeResponse(BaseModel):
    summary: PipelineSummary
    change_summaries: list[ChangeSummary]
    impacts: list[ImpactRow]
    lineage: LineageResponse


class HealthResponse(BaseModel):
    status: str = "healthy"
    version: str = "1.0.0"
    engines: list[str]
