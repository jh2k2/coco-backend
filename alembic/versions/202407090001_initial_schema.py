"""Initial schema for Family Engagement Dashboard."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "202407090001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("external_id", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('utc', now())"),
        ),
    )

    op.create_table(
        "sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("sentiment_score", sa.Numeric(precision=4, scale=2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('utc', now())"),
        ),
        sa.UniqueConstraint("session_id", name="uq_sessions_session_id"),
        sa.CheckConstraint("duration_seconds BETWEEN 0 AND 86400", name="chk_duration_range"),
        sa.CheckConstraint("sentiment_score >= 0 AND sentiment_score <= 1", name="chk_sentiment_range"),
    )

    op.create_table(
        "dashboard_rollups",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("last_session_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("daily_activity", postgresql.ARRAY(sa.Boolean()), nullable=False),
        sa.Column("daily_durations", postgresql.ARRAY(sa.Integer()), nullable=False),
        sa.Column("daily_sentiment", postgresql.ARRAY(sa.Numeric(precision=4, scale=2)), nullable=False),
        sa.Column("avg_duration_minutes", sa.Integer(), nullable=False),
        sa.Column("current_tone", sa.String(length=255), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('utc', now())"),
        ),
        sa.CheckConstraint("current_tone IN ('positive','neutral','negative')", name="chk_current_tone"),
    )

    op.create_index(
        "idx_sessions_user_started",
        "sessions",
        ["user_id", "started_at"],
        unique=False,
        postgresql_ops={"started_at": "DESC"},
    )


def downgrade() -> None:
    op.drop_index("idx_sessions_user_started", table_name="sessions")
    op.drop_table("dashboard_rollups")
    op.drop_table("sessions")
    op.drop_table("users")
