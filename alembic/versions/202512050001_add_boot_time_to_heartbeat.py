"""Add boot_time column to device_latest_heartbeat table."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "202512050001"
down_revision = "202511300001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "device_latest_heartbeat",
        sa.Column("boot_time", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("device_latest_heartbeat", "boot_time")
