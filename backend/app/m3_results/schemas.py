"""
Pydantic schemas for Module M3 (Results, History, Explainability, Reports, and Admin).
"""
from __future__ import annotations
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class ExplainabilityItem(BaseModel):
    branch: Literal["semantic", "frequency"]
    technique: str
    visualization_url: str
    generated_at: datetime


class PredictionResultView(BaseModel):
    prediction_id: int
    image_id: int
    predicted_class: Literal["Real", "AI Generated"]
    confidence_score: float
    confidence_percentage: float  # confidence_score * 100
    confidence_band: Literal["High", "Moderate", "Low"]
    semantic_score: float
    frequency_score: float | None  # null when the frequency branch had no evidence
    fusion_score: float
    original_image_url: str
    visualizations: list[ExplainabilityItem]
    model_name: str
    model_version: str
    prediction_timestamp: datetime
    interpretive_caption: str = (
        "Highlighted regions indicate where the model focused and are not proof of manipulation."
    )


class HistoryItem(BaseModel):
    prediction_id: int
    image_id: int
    thumbnail_url: str
    predicted_class: Literal["Real", "AI Generated"]
    confidence_score: float
    confidence_percentage: float
    confidence_band: Literal["High", "Moderate", "Low"]
    prediction_timestamp: datetime


class PaginatedHistory(BaseModel):
    items: list[HistoryItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class LogItem(BaseModel):
    log_id: int
    user_id: int | None
    event_type: str
    event_detail: str
    severity: str
    request_id: str | None
    log_timestamp: datetime


class PaginatedLogs(BaseModel):
    items: list[LogItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class AdminSummaryTile(BaseModel):
    total_predictions: int
    predictions_last_24h: int
    class_distribution: dict[str, int]  # e.g. {"Real": 120, "AI Generated": 85}
    error_count_last_24h: int
    active_models: list[dict[str, str]]


class TimeSeriesPoint(BaseModel):
    date: str
    predictions_count: int
    active_users: int


class ConfidenceHistogramBin(BaseModel):
    bin_range: str  # e.g. "0.0 - 0.1", "0.1 - 0.2"
    count: int


class SystemAnalytics(BaseModel):
    total_predictions: int
    class_distribution: dict[str, int]
    usage_over_time: list[TimeSeriesPoint]
    confidence_distribution: list[ConfidenceHistogramBin]
    error_rate_percentage: float
    total_logs: int


class UserStatusActionRequest(BaseModel):
    action: Literal["enable", "disable", "remove"]


class UserStatusResponse(BaseModel):
    user_id: int
    account_status: str


class AdminUserItem(BaseModel):
    user_id: int
    full_name: str
    email: str
    role: str
    account_status: str
    registered_at: datetime


class CreateMockPredictionRequest(BaseModel):
    category: Literal["real_landscape", "real_street", "ai_portrait", "ai_diffusion_surreal", "branch_disagreement"] = "ai_portrait"
    force_class: Literal["Real", "AI Generated"] | None = None
    width: int = 800
    height: int = 600

