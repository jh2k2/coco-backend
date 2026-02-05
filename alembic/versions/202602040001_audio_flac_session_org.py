"""Add role and transcript to audio recordings, switch to FLAC

Revision ID: 202602040001
Revises: 202601230001
Create Date: 2026-02-04

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "202602040001"
down_revision = "202601230001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add role column (user/assistant)
    op.add_column(
        "audio_recordings",
        sa.Column("role", sa.String(20), nullable=False, server_default="user"),
    )

    # Add transcript column
    op.add_column(
        "audio_recordings",
        sa.Column("transcript", sa.Text(), nullable=True),
    )

    # Make bitrate_kbps nullable (FLAC doesn't use bitrate)
    op.alter_column(
        "audio_recordings",
        "bitrate_kbps",
        existing_type=sa.Integer(),
        nullable=True,
    )

    # Update default codec to flac
    op.alter_column(
        "audio_recordings",
        "codec",
        server_default="flac",
    )

    # Drop old unique constraint (session_id, turn_number) - use IF EXISTS for idempotency
    op.execute("ALTER TABLE audio_recordings DROP CONSTRAINT IF EXISTS uq_audio_session_turn")

    # Create new unique constraint including role (session_id, turn_number, role)
    # Drop first if exists (for idempotency), then create
    op.execute("ALTER TABLE audio_recordings DROP CONSTRAINT IF EXISTS uq_audio_session_turn_role")
    op.create_unique_constraint(
        "uq_audio_session_turn_role",
        "audio_recordings",
        ["session_id", "turn_number", "role"],
    )

    # Add check constraint for role values (drop first if exists for idempotency)
    op.execute("ALTER TABLE audio_recordings DROP CONSTRAINT IF EXISTS chk_audio_role")
    op.create_check_constraint(
        "chk_audio_role",
        "audio_recordings",
        "role IN ('user', 'assistant')",
    )


def downgrade() -> None:
    # Drop check constraint
    op.drop_constraint("chk_audio_role", "audio_recordings", type_="check")

    # Drop new unique constraint
    op.drop_constraint("uq_audio_session_turn_role", "audio_recordings", type_="unique")

    # Recreate old unique constraint
    op.create_unique_constraint(
        "uq_audio_session_turn",
        "audio_recordings",
        ["session_id", "turn_number"],
    )

    # Revert codec default to opus
    op.alter_column(
        "audio_recordings",
        "codec",
        server_default="opus",
    )

    # Make bitrate_kbps non-nullable again
    op.alter_column(
        "audio_recordings",
        "bitrate_kbps",
        existing_type=sa.Integer(),
        nullable=False,
    )

    # Drop transcript column
    op.drop_column("audio_recordings", "transcript")

    # Drop role column
    op.drop_column("audio_recordings", "role")
