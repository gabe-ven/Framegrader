"""API contract for persisted analyses and their background jobs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.analysis import AIAnalysis, AnalysisResponse, ColorGradeResponse

JobStatus = Literal["queued", "running", "succeeded", "failed"]


class StageView(BaseModel):
    name: str
    label: str
    status: Literal["pending", "running", "done", "skipped", "failed"]
    duration_ms: float | None = None


class JobView(BaseModel):
    id: str
    kind: str
    status: JobStatus
    stage: str | None = None
    progress: float = Field(..., ge=0.0, le=1.0, description="Weighted stage progress.")
    stages: list[StageView]
    error: str | None = None
    queue_position: int | None = Field(
        default=None, description="Jobs ahead of this one; only set while queued."
    )


class AnalysisSnapshot(BaseModel):
    """Everything known about one analysis right now.

    Fields fill in as the job advances: ``measurements`` arrive a couple of
    seconds in, ``ai`` once the critique finishes, ``color_grade`` only after
    one is requested.
    """

    id: str
    filename: str
    status: JobStatus
    created_at: float
    is_public: bool
    is_owner: bool
    version: int
    image_url: str | None = None
    thumb_url: str | None = None
    measurements: AnalysisResponse | None = None
    ai: AIAnalysis | None = None
    color_grade: ColorGradeResponse | None = None
    jobs: dict[str, JobView] = Field(default_factory=dict)
    error: str | None = None


class CreatedAnalysis(BaseModel):
    id: str
    job: JobView
    client_id: str | None = Field(
        default=None,
        description="Minted when the request carried no X-Client-Id; send it as "
        "that header on later requests to act as this analysis's owner.",
    )


class HistoryItem(BaseModel):
    id: str
    filename: str
    status: JobStatus
    created_at: float
    is_public: bool
    thumb_url: str | None = None
    scene_summary: str | None = None
    composition_score: float | None = None


class HistoryPage(BaseModel):
    items: list[HistoryItem]
    next_before: float | None = None


class VisibilityUpdate(BaseModel):
    public: bool
