"""Align heartbeat storage with final specification."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "202502110001"
down_revision = "202409080001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("idx_device_heartbeats_last_seen", table_name="device_heartbeats")
    op.drop_table("device_heartbeats")

    op.create_table(
        "device_latest_heartbeat",
        sa.Column("device_id", sa.Text(), primary_key=True, nullable=False),
        sa.Column("agent_version", sa.Text(), nullable=False),
        sa.Column("connectivity", sa.String(length=255), nullable=False),
        sa.Column("signal_rssi", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("agent_status", sa.String(length=255), nullable=False),
        sa.Column("last_session_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("server_received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_device_latest_heartbeat_received_at",
        "device_latest_heartbeat",
        ["server_received_at"],
        unique=False,
        postgresql_ops={"server_received_at": "DESC"},
    )

    op.create_table(
        "device_heartbeat_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("device_id", sa.Text(), nullable=False),
        sa.Column(
            "raw_payload",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("server_received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_device_heartbeat_events_device_ts",
        "device_heartbeat_events",
        ["device_id", "server_received_at"],
        unique=False,
        postgresql_ops={"server_received_at": "DESC"},
    )


def downgrade() -> None:
    op.drop_index("idx_device_heartbeat_events_device_ts", table_name="device_heartbeat_events")
    op.drop_table("device_heartbeat_events")
    op.drop_index("idx_device_latest_heartbeat_received_at", table_name="device_latest_heartbeat")
    op.drop_table("device_latest_heartbeat")

    op.create_table(
        "device_heartbeats",
        sa.Column("device_id", sa.Text(), primary_key=True, nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("connectivity", sa.String(length=255), nullable=False),
        sa.Column("agent_status", sa.String(length=255), nullable=False),
        sa.Column("last_session_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('utc', now())"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('utc', now())"),
        ),
    )
    op.create_index(
        "idx_device_heartbeats_last_seen",
        "device_heartbeats",
        ["last_seen_at"],
        unique=False,
        postgresql_ops={"last_seen_at": "DESC"},
    )
