"""linked rename group members

Revision ID: 016_linked_rename
Revises: 015_library_sync_sources
Create Date: 2026-10-21
"""

from alembic import op
import sqlalchemy as sa

revision = "016_linked_rename"
down_revision = "015_library_sync_sources"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "linked_rename_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("pan_accounts.id"), nullable=False),
        sa.Column("directory", sa.String(length=1024), nullable=False),
        sa.Column("label", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("linked_rename_members")
