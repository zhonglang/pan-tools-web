"""library items previous episode

Revision ID: 017_library_previous_episode
Revises: 016_linked_rename
Create Date: 2026-10-26
"""

from alembic import op
import sqlalchemy as sa

revision = "017_library_previous_episode"
down_revision = "016_linked_rename"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "library_items",
        sa.Column("previous_episode", sa.Integer(), nullable=True),
    )


def downgrade():
    op.drop_column("library_items", "previous_episode")
