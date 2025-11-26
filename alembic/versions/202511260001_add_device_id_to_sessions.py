"""Add device_id column to sessions table."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "202511260001"
down_revision = "202511250001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("device_id", sa.Text(), nullable=True))
    op.create_index("idx_sessions_device_id", "sessions", ["device_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_sessions_device_id", table_name="sessions")
    op.drop_column("sessions", "device_id")
