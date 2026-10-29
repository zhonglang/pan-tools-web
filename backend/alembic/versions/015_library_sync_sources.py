"""library sync sources for episode progress

Revision ID: 015_library_sync_sources
Revises: 014_library_episode
Create Date: 2026-10-19
"""

from alembic import op
import sqlalchemy as sa

revision = "015_library_sync_sources"
down_revision = "014_library_episode"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "library_sync_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("pan_accounts.id"), nullable=False),
        sa.Column("directory", sa.String(length=1024), nullable=False),
        sa.Column("label", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("library_sync_sources")
