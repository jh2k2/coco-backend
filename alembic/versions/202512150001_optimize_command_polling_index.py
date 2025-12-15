"""Optimize command polling with composite index.

This migration adds a composite index to improve command polling query performance.
The existing idx_device_commands_device_status index only covers (device_id, status),
but the polling query also orders by created_at, causing additional sorting overhead.

The new idx_device_commands_polling index covers (device_id, status, created_at)
which allows the query planner to use a single index scan for the full query:
SELECT ... WHERE device_id = ? AND status = 'PENDING' ORDER BY created_at ASC LIMIT 1

Revision ID: 202512150001
Revises: 202512050002
Create Date: 2025-12-15
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "202512150001"
down_revision = "202512050002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add composite index for efficient command polling query
    op.create_index(
        "idx_device_commands_polling",
        "device_commands",
        ["device_id", "status", "created_at"],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("idx_device_commands_polling", table_name="device_commands", if_exists=True)
