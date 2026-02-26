"""
OmniRoute — Pydantic schemas for request/response models.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Enums ────────────────────────────────────────────────────────────────────

class PayloadType(str, Enum):
    TEXT = "text"
    VISION = "vision"


class RouteTarget(str, Enum):
    CLOUD = "cloud"
    EDGE = "edge"


# ── Telemetry ────────────────────────────────────────────────────────────────

class TelemetrySnapshot(BaseModel):
    """Point-in-time reading of system telemetry."""
    ping_ms: Optional[float] = Field(None, description="Latency to 8.8.8.8 in ms, None if offline")
    is_online: bool = Field(default=True)
    battery_percent: Optional[float] = Field(None, description="Battery %, None if no battery")
    battery_plugged: bool = Field(default=True)
    ram_available_gb: float = Field(description="Available RAM in GB")
    ram_total_gb: float = Field(description="Total RAM in GB")
    timestamp: float = Field(default_factory=time.time)


# ── Routing ──────────────────────────────────────────────────────────────────

class RoutingDecision(BaseModel):
    """Result of the routing controller's evaluation."""
    target: RouteTarget
    reasoning: str
    telemetry: TelemetrySnapshot


# ── API Request / Response ───────────────────────────────────────────────────

class ProcessRequest(BaseModel):
    """Unified request to /v1/process."""
    type: PayloadType
    payload: str = Field(description="Text prompt or base64-encoded image data")
    force_route: Optional[str] = Field(None, description="Force 'cloud' or 'edge' routing (overrides telemetry)")


class DetectionBox(BaseModel):
    """Single object detection result."""
    label: str
    confidence: float
    bbox: list[float] = Field(description="[x1, y1, x2, y2] normalized coords")


class ProcessResponse(BaseModel):
    """Unified response from /v1/process."""
    success: bool = True
    type: PayloadType
    route: RouteTarget
    reasoning: str
    result: Any = Field(description="Text string or list of DetectionBox dicts")
    latency_ms: float
    telemetry: TelemetrySnapshot
    cost_saved_usd: float = Field(0.0, description="Estimated cost saved by edge routing")


class LogEntry(BaseModel):
    """Single routing decision log."""
    id: int
    timestamp: float
    type: PayloadType
    route: RouteTarget
    reasoning: str
    latency_ms: float
    result_preview: str = Field(description="Truncated preview of the result")


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"
    uptime_seconds: float = 0.0
