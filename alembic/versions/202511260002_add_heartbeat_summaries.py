"""Add device_heartbeat_summaries table for compacted hourly data."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "202511260002"
down_revision = "202511260001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "device_heartbeat_summaries",
        sa.Column("device_id", sa.Text(), nullable=False),
        sa.Column("hour_bucket", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_count", sa.Integer(), nullable=False),
        sa.Column("avg_latency_ms", sa.Integer(), nullable=True),
        sa.Column("min_latency_ms", sa.Integer(), nullable=True),
        sa.Column("max_latency_ms", sa.Integer(), nullable=True),
        sa.Column("connectivity_mode", sa.String(20), nullable=False),
        sa.Column("agent_status_ok_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("agent_status_degraded_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("device_id", "hour_bucket"),
    )
    op.create_index(
        "idx_heartbeat_summaries_device_hour",
        "device_heartbeat_summaries",
        ["device_id", sa.text("hour_bucket DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_heartbeat_summaries_device_hour", table_name="device_heartbeat_summaries")
    op.drop_table("device_heartbeat_summaries")
