"""Add status column to sessions table."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "202511300001"
down_revision = "202511260002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add column if it doesn't exist
    op.execute("""
        ALTER TABLE sessions
        ADD COLUMN IF NOT EXISTS status VARCHAR(20)
    """)
    # Add check constraint if it doesn't exist
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'chk_session_status'
            ) THEN
                ALTER TABLE sessions
                ADD CONSTRAINT chk_session_status
                CHECK (status IN ('success', 'unattended', 'early_exit', 'error_exit'));
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.drop_constraint("chk_session_status", "sessions", type_="check")
    op.drop_column("sessions", "status")
