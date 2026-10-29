"""library items episode progress

Revision ID: 014_library_episode
Revises: 013_upload_tasks
Create Date: 2026-10-19
"""

from alembic import op
import sqlalchemy as sa

revision = "014_library_episode"
down_revision = "013_upload_tasks"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "library_items",
        sa.Column("finished", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "library_items",
        sa.Column("latest_episode", sa.Integer(), nullable=True),
    )


def downgrade():
    op.drop_column("library_items", "latest_episode")
    op.drop_column("library_items", "finished")
