"""Add device_commands and device_log_snapshots tables."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "202511250001"
down_revision = "202502110001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "device_commands",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("device_id", sa.Text(), nullable=False),
        sa.Column("command_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column(
            "payload",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "command_type IN ('REBOOT', 'RESTART_SERVICE', 'UPLOAD_LOGS', 'UPDATE_NOW')",
            name="chk_command_type",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'PICKED_UP', 'COMPLETED', 'FAILED')",
            name="chk_command_status",
        ),
    )
    op.create_index(
        "idx_device_commands_device_status",
        "device_commands",
        ["device_id", "status"],
        unique=False,
    )
    op.create_index(
        "idx_device_commands_created_at",
        "device_commands",
        ["created_at"],
        unique=False,
        postgresql_ops={"created_at": "DESC"},
    )

    op.create_table(
        "device_log_snapshots",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("device_id", sa.Text(), nullable=False),
        sa.Column("log_content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_device_log_snapshots_device_created",
        "device_log_snapshots",
        ["device_id", "created_at"],
        unique=False,
        postgresql_ops={"created_at": "DESC"},
    )


def downgrade() -> None:
    op.drop_index("idx_device_log_snapshots_device_created", table_name="device_log_snapshots")
    op.drop_table("device_log_snapshots")
    op.drop_index("idx_device_commands_created_at", table_name="device_commands")
    op.drop_index("idx_device_commands_device_status", table_name="device_commands")
    op.drop_table("device_commands")
