import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from .database import Base
from .db_types import BooleanArray, DecimalArray, IntegerArray


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    external_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    sessions: Mapped[list["Session"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    dashboard_rollup: Mapped["DashboardRollup"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("session_id", name="uq_sessions_session_id"),
        CheckConstraint("duration_seconds BETWEEN 0 AND 86400", name="chk_duration_range"),
        CheckConstraint("sentiment_score >= 0 AND sentiment_score <= 1", name="chk_sentiment_range"),
        CheckConstraint("status IN ('success', 'unattended', 'early_exit', 'error_exit')", name="chk_session_status"),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    device_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_id: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    sentiment_score: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False)
    status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="sessions")


class DashboardRollup(Base):
    __tablename__ = "dashboard_rollups"
    __table_args__ = (
        CheckConstraint("current_tone IN ('positive','neutral','negative')", name="chk_current_tone"),
    )

    user_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    last_session_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    daily_activity: Mapped[list[bool]] = mapped_column(BooleanArray(), nullable=False)
    daily_durations: Mapped[list[int]] = mapped_column(IntegerArray(), nullable=False)
    daily_sentiment: Mapped[list[float | None]] = mapped_column(DecimalArray(), nullable=False)
    avg_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    current_tone: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="dashboard_rollup")


Index("idx_sessions_user_started", Session.user_id, Session.started_at.desc())
Index("idx_sessions_device_id", Session.device_id)


json_type = JSON().with_variant(JSONB, "postgresql")


class DeviceLatestHeartbeat(Base):
    __tablename__ = "device_latest_heartbeat"

    device_id: Mapped[str] = mapped_column(Text, primary_key=True)
    agent_version: Mapped[str] = mapped_column(Text, nullable=False)
    connectivity: Mapped[str] = mapped_column(String, nullable=False)
    signal_rssi: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agent_status: Mapped[str] = mapped_column(String, nullable=False)
    last_session_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    boot_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    server_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# NOTE: idx_device_latest_heartbeat_received_at was removed in migration 202512150002
# as it had 0 uses. Monitor table growth - may need to recreate if table grows large.


class DeviceHeartbeatEvent(Base):
    __tablename__ = "device_heartbeat_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    device_id: Mapped[str] = mapped_column(Text, nullable=False)
    raw_payload: Mapped[dict] = mapped_column(json_type, nullable=False)
    server_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


Index(
    "idx_device_heartbeat_events_device_ts",
    DeviceHeartbeatEvent.device_id,
    DeviceHeartbeatEvent.server_received_at.desc(),
)


class DeviceCommand(Base):
    __tablename__ = "device_commands"
    __table_args__ = (
        CheckConstraint(
            "command_type IN ('REBOOT', 'RESTART_SERVICE', 'UPLOAD_LOGS', 'UPDATE_NOW')",
            name="chk_command_type",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'PICKED_UP', 'COMPLETED', 'FAILED')",
            name="chk_command_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    device_id: Mapped[str] = mapped_column(Text, nullable=False)
    command_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", server_default="PENDING")
    payload: Mapped[dict | None] = mapped_column(json_type, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


Index("idx_device_commands_device_status", DeviceCommand.device_id, DeviceCommand.status)
# Composite index for efficient command polling: WHERE device_id=? AND status='PENDING' ORDER BY created_at
Index("idx_device_commands_polling", DeviceCommand.device_id, DeviceCommand.status, DeviceCommand.created_at)
# NOTE: idx_device_commands_created_at was removed in migration 202512150002 - superseded by idx_device_commands_polling


class DeviceLogSnapshot(Base):
    __tablename__ = "device_log_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    device_id: Mapped[str] = mapped_column(Text, nullable=False)
    log_content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


Index("idx_device_log_snapshots_device_created", DeviceLogSnapshot.device_id, DeviceLogSnapshot.created_at.desc())


class DeviceHeartbeatSummary(Base):
    """Hourly aggregated heartbeat data for historical analysis."""

    __tablename__ = "device_heartbeat_summaries"

    device_id: Mapped[str] = mapped_column(Text, primary_key=True)
    hour_bucket: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    heartbeat_count: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    connectivity_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    agent_status_ok_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    agent_status_degraded_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    uptime_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reboot_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


Index("idx_heartbeat_summaries_device_hour", DeviceHeartbeatSummary.device_id, DeviceHeartbeatSummary.hour_bucket.desc())


class AudioRecording(Base):
    """Audio recordings from device sessions, stored in R2."""

    __tablename__ = "audio_recordings"
    __table_args__ = (
        UniqueConstraint("session_id", "turn_number", name="uq_audio_session_turn"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    device_id: Mapped[str] = mapped_column(Text, nullable=False)
    participant_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)
    activity_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    codec: Mapped[str] = mapped_column(String(20), nullable=False, default="opus")
    sample_rate: Mapped[int] = mapped_column(Integer, nullable=False, default=24000)
    channels: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    bitrate_kbps: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    storage_url: Mapped[str] = mapped_column(Text, nullable=False)
    storage_provider: Mapped[str] = mapped_column(String(50), nullable=False, default="r2")
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


Index("idx_audio_device", AudioRecording.device_id)
Index("idx_audio_participant", AudioRecording.participant_id)
Index("idx_audio_session", AudioRecording.session_id)
Index("idx_audio_recorded", AudioRecording.recorded_at.desc())
