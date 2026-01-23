"""Add audio recordings table

Revision ID: 202601230001
Revises: 202512150002_drop_unused_indexes
Create Date: 2026-01-23

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "202601230001"
down_revision = "202512150002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audio_recordings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", sa.Text(), nullable=False),
        sa.Column("participant_id", sa.Text(), nullable=True),
        sa.Column("turn_number", sa.Integer(), nullable=False),
        sa.Column("activity_id", sa.String(100), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("codec", sa.String(20), nullable=False, server_default="opus"),
        sa.Column("sample_rate", sa.Integer(), nullable=False, server_default="24000"),
        sa.Column("channels", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("bitrate_kbps", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("storage_url", sa.Text(), nullable=False),
        sa.Column("storage_provider", sa.String(50), nullable=False, server_default="r2"),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "turn_number", name="uq_audio_session_turn"),
    )
    op.create_index("idx_audio_device", "audio_recordings", ["device_id"])
    op.create_index("idx_audio_participant", "audio_recordings", ["participant_id"])
    op.create_index("idx_audio_session", "audio_recordings", ["session_id"])
    op.create_index("idx_audio_recorded", "audio_recordings", ["recorded_at"], postgresql_ops={"recorded_at": "DESC"})


def downgrade() -> None:
    op.drop_index("idx_audio_recorded", table_name="audio_recordings")
    op.drop_index("idx_audio_session", table_name="audio_recordings")
    op.drop_index("idx_audio_participant", table_name="audio_recordings")
    op.drop_index("idx_audio_device", table_name="audio_recordings")
    op.drop_table("audio_recordings")
