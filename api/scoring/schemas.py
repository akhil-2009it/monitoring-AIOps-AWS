"""Pydantic schemas for the Anomaly Scoring API."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class CommonEvent(BaseModel):
    """The common-schema event from ml/parsers/. We accept extra fields permissively."""
    ts: str
    source: str
    host: Optional[str] = ""
    severity: Optional[str] = None
    status: Optional[int] = None
    latency_ms: Optional[float] = None
    bytes: Optional[int] = None
    src_ip: Optional[str] = None
    user: Optional[str] = None
    path: Optional[str] = None
    user_agent: Optional[str] = None
    message: Optional[str] = ""
    attrs: dict[str, Any] = Field(default_factory=dict)


class ScoreResponse(BaseModel):
    score: float
    is_anomaly: bool
    detector: str
    explanation: dict
    metric_key: str


class Alert(BaseModel):
    id: str
    detector: str
    metric_key: str
    source: Optional[str] = None
    severity: Optional[str] = None
    score: float
    value: float
    baseline: float
    explanation: str
    ts_seen: float
    created_at: str
    label: Optional[str] = None  # true_positive | false_positive | ignored


class FeedbackBody(BaseModel):
    alert_id: str
    label: str = Field(..., pattern=r"^(true_positive|false_positive|ignored)$")


class HealthResponse(BaseModel):
    status: str
    streaming_detector_ready: bool
    sagemaker_endpoints: list[str]


class SourceHealth(BaseModel):
    source: str
    last_seen: Optional[str]
    count: int
