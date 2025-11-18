"""Add device heartbeats table for uptime monitoring."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "202409080001"
down_revision = "202407090001"
branch_labels = None
depends_on = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_index("idx_device_heartbeats_last_seen", table_name="device_heartbeats")
    op.drop_table("device_heartbeats")
