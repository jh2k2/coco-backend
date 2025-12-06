"""Add uptime tracking to heartbeat summaries."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "202512050002"
down_revision = "202512050001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "device_heartbeat_summaries",
        sa.Column("uptime_seconds", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "device_heartbeat_summaries",
        sa.Column("reboot_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("device_heartbeat_summaries", "reboot_count")
    op.drop_column("device_heartbeat_summaries", "uptime_seconds")
