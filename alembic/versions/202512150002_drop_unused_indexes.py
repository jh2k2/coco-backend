"""Drop unused indexes to reduce write overhead.

This migration removes indexes that are not being used according to pg_stat_user_indexes:

1. idx_device_latest_heartbeat_received_at (0 times used)
   - The list_heartbeat_statuses query does ORDER BY server_received_at DESC,
     but with only 4 rows in the table, PostgreSQL prefers a sequential scan + sort.
   - Monitor after deploy - if the table grows significantly, this index may need
     to be recreated.

2. idx_device_commands_created_at (1 time used)
   - Superseded by the new idx_device_commands_polling composite index which
     includes created_at as the third column.

Removing these indexes reduces write overhead since every INSERT/UPDATE no longer
needs to maintain these unused index structures.

Revision ID: 202512150002
Revises: 202512150001
Create Date: 2025-12-15
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "202512150002"
down_revision = "202512150001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop unused indexes to reduce write overhead
    op.drop_index("idx_device_latest_heartbeat_received_at", table_name="device_latest_heartbeat", if_exists=True)
    op.drop_index("idx_device_commands_created_at", table_name="device_commands", if_exists=True)


def downgrade() -> None:
    # Restore indexes if rollback is needed
    op.create_index(
        "idx_device_commands_created_at",
        "device_commands",
        ["created_at"],
        unique=False,
        postgresql_ops={"created_at": "DESC"},
        if_not_exists=True,
    )
    op.create_index(
        "idx_device_latest_heartbeat_received_at",
        "device_latest_heartbeat",
        ["server_received_at"],
        unique=False,
        postgresql_ops={"server_received_at": "DESC"},
        if_not_exists=True,
    )
