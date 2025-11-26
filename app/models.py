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
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    sentiment_score: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False)
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
    server_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


Index("idx_device_latest_heartbeat_received_at", DeviceLatestHeartbeat.server_received_at.desc())


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
Index("idx_device_commands_created_at", DeviceCommand.created_at.desc())


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
