from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SessionSummaryIngestRequest(BaseModel):
    session_id: str
    user_external_id: str
    started_at: datetime
    duration_seconds: int = Field(ge=0, le=86400)
    sentiment_score: float = Field(ge=0, le=1)

    model_config = ConfigDict(use_enum_values=True)

    @field_validator("started_at", mode="after")
    @classmethod
    def ensure_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("started_at must include timezone information")
        return value.astimezone(timezone.utc)


def _normalize_datetime(value: datetime | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{field_name} must include timezone information")
    return value.astimezone(timezone.utc)


class HeartbeatNetwork(BaseModel):
    interface: str = Field(min_length=1)
    ip: str = Field(min_length=1)
    signal_rssi: int | None = None
    latency_ms: int | None = None


class HeartbeatRequest(BaseModel):
    device_id: str = Field(min_length=1)
    agent_version: str = Field(min_length=1)
    connectivity: Literal["wifi", "lte", "offline"]
    network: HeartbeatNetwork
    agent_status: Literal["ok", "degraded", "crashed"]
    last_session_at: datetime | None = None
    timestamp: datetime | None = None

    @field_validator("last_session_at", mode="after")
    @classmethod
    def normalize_last_session(cls, value: datetime | None) -> datetime | None:
        return _normalize_datetime(value, "last_session_at")

    @field_validator("timestamp", mode="after")
    @classmethod
    def normalize_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        normalized = _normalize_datetime(value, "timestamp")
        assert normalized is not None
        return normalized


class HeartbeatStatus(BaseModel):
    deviceId: str
    status: Literal["healthy", "degraded", "dead"]
    lastSeen: datetime
    connectivity: str
    agentVersion: str
    signalRssi: int | None
    latencyMs: int | None
    lastSessionAt: datetime | None


class HeartbeatSummaryResponse(BaseModel):
    devices: list[HeartbeatStatus]
    asOf: datetime
    staleThresholdMinutes: int

    model_config = ConfigDict(use_enum_values=True)


class LastSession(BaseModel):
    timestamp: datetime | None


class Streak(BaseModel):
    days: int
    dailyActivity: list[bool]

    @model_validator(mode="after")
    def validate_length(self) -> "Streak":
        if len(self.dailyActivity) != 7:
            raise ValueError("dailyActivity must contain 7 elements")
        return self


class AvgDuration(BaseModel):
    minutes: int
    dailyDurations: list[int]

    @model_validator(mode="after")
    def validate_length(self) -> "AvgDuration":
        if len(self.dailyDurations) != 7:
            raise ValueError("dailyDurations must contain 7 elements")
        return self


class ToneTrend(BaseModel):
    current: Literal["positive", "neutral", "negative"]
    dailySentiment: list[float | None]

    @model_validator(mode="after")
    def validate_length(self) -> "ToneTrend":
        if len(self.dailySentiment) != 7:
            raise ValueError("dailySentiment must contain 7 elements")
        return self


class DashboardResponse(BaseModel):
    lastSession: LastSession
    streak: Streak
    avgDuration: AvgDuration
    toneTrend: ToneTrend
    lastUpdated: datetime

    model_config = ConfigDict(use_enum_values=True)
