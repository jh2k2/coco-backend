import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
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
